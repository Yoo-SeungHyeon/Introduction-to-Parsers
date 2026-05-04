#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
itp_sbs.py

사용법:
    python itp_sbs.py <pdf_path>

필요 패키지:
    pip install pypdf pymupdf

역할:
    입력 PDF를 5단계로 처리하면서 각 단계의 역할, 처리 결과, 중간 산출물을 터미널에 출력합니다.

주의:
    이 코드는 "교육용 step-by-step introspection" 코드입니다.
    실제 Rendering은 PDF 렌더링 엔진인 PyMuPDF(fitz)를 사용합니다.
    즉, 1~4단계는 PDF 구조/스트림/명령/리소스를 관찰하고,
    5단계에서 최종 이미지는 검증된 렌더링 백엔드로 생성합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


REQUIRED_IMPORT_ERRORS: List[str] = []

try:
    from pypdf import PdfReader
    from pypdf.generic import (
        ArrayObject,
        ContentStream,
        DictionaryObject,
        EncodedStreamObject,
        DecodedStreamObject,
        IndirectObject,
        NameObject,
        TextStringObject,
        ByteStringObject,
        NumberObject,
        FloatObject,
        BooleanObject,
        NullObject,
    )
except Exception as exc:  # pragma: no cover
    PdfReader = None  # type: ignore
    REQUIRED_IMPORT_ERRORS.append(f"pypdf import 실패: {exc}")

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover
    fitz = None  # type: ignore
    REQUIRED_IMPORT_ERRORS.append(f"pymupdf import 실패: {exc}")


LINE = "-" * 54
HASH = "#" * 35


STEP_DESCRIPTIONS = {
    1: {
        "title": "Parsing",
        "subtitle": "PDF 파일 구조 파싱",
        "tasks": [
            "PDF header를 확인합니다.",
            "xref / trailer를 통해 indirect object 위치와 문서 전역 정보를 확인합니다.",
            "Catalog → Pages → Page 객체 그래프를 따라 페이지 목록을 만듭니다.",
            "각 Page의 /Contents, /Resources, /MediaBox, /CropBox, /Rotate를 확인합니다.",
            "아직 페이지 내부 drawing operator를 실행하거나 렌더링하지 않습니다.",
        ],
    },
    2: {
        "title": "Decoding",
        "subtitle": "stream 압축 해제 및 filter 적용",
        "tasks": [
            "각 Page의 /Contents stream을 찾습니다.",
            "/Filter와 /DecodeParms를 적용해 압축된 stream을 decoded bytes로 바꿉니다.",
            "/Contents가 배열이면 여러 content stream을 순서대로 병합합니다.",
            "결과는 아직 의미 단위로 파싱되지 않은 PDF content stream 바이트열입니다.",
        ],
    },
    3: {
        "title": "Parsing",
        "subtitle": "content stream operator 파싱",
        "tasks": [
            "decoded content stream을 token/operator 단위로 해석합니다.",
            "BT, ET, Tf, Tj, TJ 같은 text operator를 식별합니다.",
            "m, l, c, re, S, f 같은 path/paint operator를 식별합니다.",
            "q, Q, cm 같은 graphics state / transformation operator를 식별합니다.",
            "operator와 operand를 묶어 display list에 가까운 중간 표현으로 정리합니다.",
        ],
    },
    4: {
        "title": "Resourcing",
        "subtitle": "resource dictionary 해석 및 연결",
        "tasks": [
            "content stream에서 참조하는 /F1, /Im0, /GS1 같은 이름을 실제 resource와 연결합니다.",
            "/Font resource의 subtype, base font, encoding, ToUnicode 여부를 확인합니다.",
            "/XObject resource의 Image/Form 여부와 이미지 속성을 확인합니다.",
            "/ColorSpace, /ExtGState 등 렌더링에 필요한 보조 리소스를 확인합니다.",
            "Page에 /Resources가 없으면 상위 /Pages 노드에서 상속된 resource를 확인합니다.",
        ],
    },
    5: {
        "title": "Rendering",
        "subtitle": "최종 페이지 이미지 생성",
        "tasks": [
            "MediaBox/CropBox/Rotate와 PDF 좌표계를 반영해 페이지 캔버스를 구성합니다.",
            "path, text, image, clipping, transparency 등을 최종 출력 장치에 그립니다.",
            "이 스크립트에서는 PyMuPDF 렌더링 엔진을 사용해 PNG 이미지를 생성합니다.",
            "생성된 PNG 파일 경로와 픽셀 크기를 출력합니다.",
        ],
    },
}


TEXT_OPERATORS = {
    "BT", "ET", "Tf", "Tj", "TJ", "'", '"', "Td", "TD", "Tm", "T*", "Tc", "Tw", "Tz", "TL", "Tr", "Ts",
}
PATH_OPERATORS = {
    "m", "l", "c", "v", "y", "h", "re", "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n", "W", "W*",
}
IMAGE_OPERATORS = {"Do", "BI", "ID", "EI"}
STATE_OPERATORS = {"q", "Q", "cm", "w", "J", "j", "M", "d", "ri", "i", "gs"}
COLOR_OPERATORS = {"CS", "cs", "SC", "SCN", "sc", "scn", "G", "g", "RG", "rg", "K", "k"}


def print_header() -> None:
    print(HASH)
    print("Parsing 5단계")
    print("1. Parsing   - PDF 파일 구조 파싱")
    print("2. Decoding  - stream 압축 해제 및 filter 적용")
    print("3. Parsing   - content stream operator 파싱")
    print("4. Resourcing - resource dictionary 해석 및 연결")
    print("5. Rendering - 최종 페이지 이미지 생성")
    print(HASH)


def print_step_intro(step_no: int) -> None:
    desc = STEP_DESCRIPTIONS[step_no]
    print(f"{step_no}단계 {desc['title']}")
    for task in desc["tasks"]:
        print(f"- {task}")
    print()
    print("그 결과")


def print_step_result(step_no: int, result: Any) -> None:
    print_step_intro(step_no)
    print(to_pretty_json(result))
    print(LINE)


def to_pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def obj_ref(obj: Any) -> Optional[str]:
    """
    pypdf object의 indirect reference를 사람이 읽기 쉬운 문자열로 반환합니다.
    """
    ref = getattr(obj, "indirect_reference", None)
    if ref is None and isinstance(obj, IndirectObject):
        ref = obj

    if ref is None:
        return None

    idnum = getattr(ref, "idnum", None)
    generation = getattr(ref, "generation", None)
    if idnum is None:
        return str(ref)
    return f"{idnum} {generation or 0} R"


def deref(obj: Any) -> Any:
    """
    IndirectObject이면 실제 객체로 resolve합니다.
    """
    try:
        if isinstance(obj, IndirectObject):
            return obj.get_object()
    except Exception:
        return obj
    return obj


def pdf_name(obj: Any) -> str:
    if obj is None:
        return "null"
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def simplify_pdf_object(obj: Any, *, depth: int = 0, max_depth: int = 3) -> Any:
    """
    pypdf 객체를 JSON 직렬화 가능한 작은 형태로 변환합니다.
    너무 깊거나 큰 객체는 요약합니다.
    """
    if depth > max_depth:
        return f"<{type(obj).__name__}>"

    if isinstance(obj, IndirectObject):
        return obj_ref(obj)

    obj = deref(obj)

    if isinstance(obj, (NameObject, TextStringObject)):
        return str(obj)

    if isinstance(obj, ByteStringObject):
        raw = bytes(obj)
        return {
            "type": "ByteString",
            "length": len(raw),
            "preview_hex": raw[:32].hex(),
        }

    if isinstance(obj, (NumberObject, FloatObject)):
        try:
            if isinstance(obj, FloatObject):
                return float(obj)
            return int(obj)
        except Exception:
            return str(obj)

    if isinstance(obj, BooleanObject):
        return bool(obj)

    if isinstance(obj, NullObject):
        return None

    if isinstance(obj, ArrayObject) or isinstance(obj, list) or isinstance(obj, tuple):
        arr = list(obj)
        simplified = [simplify_pdf_object(x, depth=depth + 1, max_depth=max_depth) for x in arr[:10]]
        if len(arr) > 10:
            simplified.append(f"... {len(arr) - 10} more")
        return simplified

    if isinstance(obj, DictionaryObject) or isinstance(obj, dict):
        out = {}
        items = list(obj.items())
        for k, v in items[:20]:
            key = str(k)
            if key in {"/Contents", "/Resources", "/Parent"}:
                out[key] = obj_ref(v) or f"<{type(deref(v)).__name__}>"
            elif isinstance(deref(v), (EncodedStreamObject, DecodedStreamObject)):
                stream = deref(v)
                out[key] = {
                    "type": type(stream).__name__,
                    "ref": obj_ref(v),
                    "filter": simplify_pdf_object(stream.get("/Filter"), depth=depth + 1, max_depth=max_depth),
                }
            else:
                out[key] = simplify_pdf_object(v, depth=depth + 1, max_depth=max_depth)
        if len(items) > 20:
            out["..."] = f"{len(items) - 20} more keys"
        return out

    if isinstance(obj, (EncodedStreamObject, DecodedStreamObject)):
        return {
            "type": type(obj).__name__,
            "ref": obj_ref(obj),
            "filter": simplify_pdf_object(obj.get("/Filter"), depth=depth + 1, max_depth=max_depth),
            "length": simplify_pdf_object(obj.get("/Length"), depth=depth + 1, max_depth=max_depth),
        }

    if isinstance(obj, bytes):
        return {
            "type": "bytes",
            "length": len(obj),
            "preview": safe_text_preview(obj, 120),
        }

    return str(obj)


def inherited_page_value(page: Any, key: str) -> Any:
    """
    Page dictionary에서 key를 찾고, 없으면 /Parent를 따라 올라가며 inherited value를 찾습니다.
    PDF에서 /Resources, /MediaBox 등은 상위 Pages 노드에서 상속될 수 있습니다.
    """
    current = page
    seen = set()

    while current is not None:
        current = deref(current)
        current_id = id(current)
        if current_id in seen:
            return None
        seen.add(current_id)

        try:
            if key in current:
                return current[key]
        except Exception:
            return None

        try:
            parent = current.get("/Parent")
        except Exception:
            parent = None

        if parent is None:
            return None
        current = parent

    return None


def stream_filter_summary(stream: Any) -> Any:
    stream = deref(stream)
    if stream is None:
        return None
    try:
        return simplify_pdf_object(stream.get("/Filter"))
    except Exception:
        return None


def get_content_objects(page: Any) -> List[Any]:
    """
    Page의 /Contents를 stream 객체 리스트로 반환합니다.
    /Contents는 단일 stream일 수도 있고 stream 배열일 수도 있습니다.
    """
    contents = inherited_page_value(page, "/Contents")
    if contents is None:
        return []

    contents = deref(contents)
    if isinstance(contents, ArrayObject) or isinstance(contents, list):
        return [deref(x) for x in contents]
    return [contents]


def safe_box(page: Any, key: str) -> Any:
    value = inherited_page_value(page, key)
    if value is None:
        return None
    return simplify_pdf_object(value)


def safe_text_preview(raw: bytes, limit: int = 800) -> str:
    """
    PDF content stream은 기본적으로 ASCII operator + 임의 bytes 문자열이 섞일 수 있습니다.
    깨지지 않게 latin-1로 1:1 decode한 뒤 제어문자를 일부 정리합니다.
    """
    if raw is None:
        return ""
    text = raw[:limit].decode("latin-1", errors="replace")
    text = text.replace("\r", "\\r")
    text = text.replace("\x00", "\\x00")
    if len(raw) > limit:
        text += f"\n... <{len(raw) - limit} bytes 생략>"
    return text


def load_reader(pdf_path: Path) -> Any:
    if PdfReader is None:
        raise RuntimeError("pypdf를 import할 수 없습니다. `pip install pypdf` 후 다시 실행하세요.")

    reader = PdfReader(str(pdf_path), strict=False)
    if getattr(reader, "is_encrypted", False):
        try:
            ok = reader.decrypt("")
            if ok == 0:
                raise RuntimeError("암호화된 PDF입니다. 빈 암호로 복호화할 수 없습니다.")
        except Exception as exc:
            raise RuntimeError(f"암호화된 PDF를 복호화하지 못했습니다: {exc}") from exc
    return reader


def parse_pdf_structure(pdf_path: Path, reader: Any) -> Dict[str, Any]:
    raw = pdf_path.read_bytes()
    header_match = re.search(rb"%PDF-[0-9.]+", raw[:1024])
    header = header_match.group(0).decode("ascii", errors="replace") if header_match else "<PDF header not found>"

    trailer = getattr(reader, "trailer", {})
    root = deref(trailer.get("/Root")) if trailer else None
    info = deref(trailer.get("/Info")) if trailer else None

    pages = []
    for idx, page in enumerate(reader.pages, start=1):
        content_objects = get_content_objects(page)
        resources = deref(inherited_page_value(page, "/Resources"))

        pages.append(
            {
                "page": idx,
                "page_ref": obj_ref(page),
                "media_box": safe_box(page, "/MediaBox"),
                "crop_box": safe_box(page, "/CropBox"),
                "rotate": simplify_pdf_object(inherited_page_value(page, "/Rotate")),
                "contents": {
                    "count": len(content_objects),
                    "refs": [obj_ref(x) for x in content_objects],
                    "filters": [stream_filter_summary(x) for x in content_objects],
                },
                "resource_keys": list(map(str, resources.keys())) if isinstance(resources, DictionaryObject) else [],
            }
        )

    summary = {
        "pdf_path": str(pdf_path.resolve()),
        "file_size_bytes": len(raw),
        "header": header,
        "is_encrypted": bool(getattr(reader, "is_encrypted", False)),
        "page_count": len(reader.pages),
        "trailer_keys": list(map(str, trailer.keys())) if trailer else [],
        "root_keys": list(map(str, root.keys())) if isinstance(root, DictionaryObject) else [],
        "info": simplify_pdf_object(info) if info else None,
        "pages": pages,
    }
    return summary


def decode_page_content_streams(reader: Any) -> Dict[str, Any]:
    page_results = []

    for idx, page in enumerate(reader.pages, start=1):
        content_objects = get_content_objects(page)
        decoded_parts: List[bytes] = []
        stream_items = []

        for stream_idx, stream in enumerate(content_objects, start=1):
            stream = deref(stream)
            filter_before = stream_filter_summary(stream)

            try:
                data = stream.get_data()
            except Exception as exc:
                data = b""
                error = str(exc)
            else:
                error = None

            decoded_parts.append(data)

            stream_items.append(
                {
                    "stream_no": stream_idx,
                    "ref": obj_ref(stream),
                    "filter": filter_before,
                    "decoded_size_bytes": len(data),
                    "error": error,
                    "decoded_preview": safe_text_preview(data, 500),
                }
            )

        merged = b"\n".join(decoded_parts)
        page_results.append(
            {
                "page": idx,
                "stream_count": len(content_objects),
                "merged_decoded_size_bytes": len(merged),
                "streams": stream_items,
                "merged_decoded_preview": safe_text_preview(merged, 900),
            }
        )

    return {
        "pages": page_results,
    }


def operator_category(op: str) -> str:
    if op in TEXT_OPERATORS:
        return "text"
    if op in PATH_OPERATORS:
        return "path"
    if op in IMAGE_OPERATORS:
        return "image_or_xobject"
    if op in STATE_OPERATORS:
        return "graphics_state"
    if op in COLOR_OPERATORS:
        return "color"
    return "other"


def sanitize_operand(value: Any) -> Any:
    """
    ContentStream operands를 출력하기 좋은 형태로 축약합니다.
    """
    value = deref(value)

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "length": len(value),
            "preview": safe_text_preview(value, 80),
        }

    if isinstance(value, (NameObject, TextStringObject)):
        return str(value)

    if isinstance(value, ByteStringObject):
        raw = bytes(value)
        return {
            "type": "ByteString",
            "length": len(raw),
            "preview": safe_text_preview(raw, 80),
        }

    if isinstance(value, (NumberObject, FloatObject)):
        try:
            return float(value) if isinstance(value, FloatObject) else int(value)
        except Exception:
            return str(value)

    if isinstance(value, ArrayObject) or isinstance(value, list) or isinstance(value, tuple):
        arr = list(value)
        out = [sanitize_operand(x) for x in arr[:8]]
        if len(arr) > 8:
            out.append(f"... {len(arr) - 8} more")
        return out

    if isinstance(value, DictionaryObject):
        return simplify_pdf_object(value, max_depth=2)

    if isinstance(value, IndirectObject):
        return obj_ref(value)

    return str(value)


def parse_content_streams(reader: Any, max_ops_preview: int = 30) -> Dict[str, Any]:
    page_results = []

    for idx, page in enumerate(reader.pages, start=1):
        operations = []
        parse_error = None

        try:
            contents = inherited_page_value(page, "/Contents")
            if contents is None:
                content_stream = None
                parsed_ops = []
            else:
                content_stream = ContentStream(contents, reader)
                parsed_ops = content_stream.operations
        except Exception as exc:
            parsed_ops = []
            parse_error = str(exc)

        counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()

        for operands, operator in parsed_ops:
            if isinstance(operator, bytes):
                op = operator.decode("latin-1", errors="replace")
            else:
                op = str(operator)
            counts[op] += 1
            category_counts[operator_category(op)] += 1

            if len(operations) < max_ops_preview:
                operations.append(
                    {
                        "op": op,
                        "category": operator_category(op),
                        "operands": [sanitize_operand(x) for x in operands],
                    }
                )

        page_results.append(
            {
                "page": idx,
                "operation_count": len(parsed_ops),
                "operator_counts": dict(counts.most_common()),
                "category_counts": dict(category_counts.most_common()),
                "first_operations": operations,
                "parse_error": parse_error,
            }
        )

    return {
        "pages": page_results,
    }


def summarize_font_resource(name: str, font_obj: Any) -> Dict[str, Any]:
    font = deref(font_obj)
    out = {
        "name": name,
        "ref": obj_ref(font_obj),
        "subtype": pdf_name(font.get("/Subtype")) if isinstance(font, DictionaryObject) else None,
        "base_font": pdf_name(font.get("/BaseFont")) if isinstance(font, DictionaryObject) else None,
        "encoding": simplify_pdf_object(font.get("/Encoding"), max_depth=2) if isinstance(font, DictionaryObject) else None,
        "has_to_unicode": bool(font.get("/ToUnicode")) if isinstance(font, DictionaryObject) else False,
    }

    if isinstance(font, DictionaryObject) and font.get("/DescendantFonts"):
        descendants = deref(font.get("/DescendantFonts"))
        if isinstance(descendants, ArrayObject) and len(descendants) > 0:
            descendant = deref(descendants[0])
            if isinstance(descendant, DictionaryObject):
                out["descendant"] = {
                    "subtype": pdf_name(descendant.get("/Subtype")),
                    "base_font": pdf_name(descendant.get("/BaseFont")),
                    "cid_system_info": simplify_pdf_object(descendant.get("/CIDSystemInfo"), max_depth=2),
                    "cid_to_gid_map": simplify_pdf_object(descendant.get("/CIDToGIDMap"), max_depth=1),
                }

    return out


def summarize_xobject_resource(name: str, xobj: Any) -> Dict[str, Any]:
    obj = deref(xobj)

    if not isinstance(obj, DictionaryObject):
        return {"name": name, "ref": obj_ref(xobj), "type": type(obj).__name__}

    subtype = pdf_name(obj.get("/Subtype"))

    out = {
        "name": name,
        "ref": obj_ref(xobj),
        "subtype": subtype,
        "filter": simplify_pdf_object(obj.get("/Filter"), max_depth=2),
    }

    if subtype == "/Image":
        out.update(
            {
                "width": simplify_pdf_object(obj.get("/Width")),
                "height": simplify_pdf_object(obj.get("/Height")),
                "color_space": simplify_pdf_object(obj.get("/ColorSpace"), max_depth=2),
                "bits_per_component": simplify_pdf_object(obj.get("/BitsPerComponent")),
                "image_mask": simplify_pdf_object(obj.get("/ImageMask")),
            }
        )
    elif subtype == "/Form":
        out.update(
            {
                "bbox": simplify_pdf_object(obj.get("/BBox")),
                "matrix": simplify_pdf_object(obj.get("/Matrix")),
                "resource_keys": list(map(str, deref(obj.get("/Resources", {})).keys()))
                if isinstance(deref(obj.get("/Resources", {})), DictionaryObject)
                else [],
            }
        )

    return out


def summarize_extgstate_resource(name: str, gs_obj: Any) -> Dict[str, Any]:
    gs = deref(gs_obj)
    if not isinstance(gs, DictionaryObject):
        return {"name": name, "ref": obj_ref(gs_obj), "type": type(gs).__name__}

    interesting_keys = ["/CA", "/ca", "/BM", "/SMask", "/LW", "/LC", "/LJ", "/ML", "/D", "/OP", "/op", "/OPM"]
    return {
        "name": name,
        "ref": obj_ref(gs_obj),
        "values": {
            key: simplify_pdf_object(gs.get(key), max_depth=2)
            for key in interesting_keys
            if key in gs
        },
    }


def resolve_resources(reader: Any) -> Dict[str, Any]:
    page_results = []

    for idx, page in enumerate(reader.pages, start=1):
        resources = deref(inherited_page_value(page, "/Resources"))

        if not isinstance(resources, DictionaryObject):
            page_results.append(
                {
                    "page": idx,
                    "has_resources": False,
                    "fonts": [],
                    "xobjects": [],
                    "color_spaces": [],
                    "extgstates": [],
                }
            )
            continue

        fonts_dict = deref(resources.get("/Font", {}))
        xobjects_dict = deref(resources.get("/XObject", {}))
        colorspaces_dict = deref(resources.get("/ColorSpace", {}))
        extgstates_dict = deref(resources.get("/ExtGState", {}))

        fonts = []
        if isinstance(fonts_dict, DictionaryObject):
            for name, font_obj in fonts_dict.items():
                fonts.append(summarize_font_resource(str(name), font_obj))

        xobjects = []
        if isinstance(xobjects_dict, DictionaryObject):
            for name, xobj in xobjects_dict.items():
                xobjects.append(summarize_xobject_resource(str(name), xobj))

        color_spaces = []
        if isinstance(colorspaces_dict, DictionaryObject):
            for name, cs_obj in colorspaces_dict.items():
                color_spaces.append(
                    {
                        "name": str(name),
                        "definition": simplify_pdf_object(cs_obj, max_depth=3),
                    }
                )

        extgstates = []
        if isinstance(extgstates_dict, DictionaryObject):
            for name, gs_obj in extgstates_dict.items():
                extgstates.append(summarize_extgstate_resource(str(name), gs_obj))

        page_results.append(
            {
                "page": idx,
                "has_resources": True,
                "resource_keys": list(map(str, resources.keys())),
                "fonts": fonts,
                "xobjects": xobjects,
                "color_spaces": color_spaces,
                "extgstates": extgstates,
            }
        )

    return {
        "pages": page_results,
    }


def render_pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 144) -> Dict[str, Any]:
    if fitz is None:
        raise RuntimeError("PyMuPDF를 import할 수 없습니다. `pip install pymupdf` 후 다시 실행하세요.")

    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    rendered = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        out_path = out_dir / f"page_{page_index + 1:03d}.png"
        pix.save(str(out_path))

        rendered.append(
            {
                "page": page_index + 1,
                "output_png": str(out_path.resolve()),
                "width_px": pix.width,
                "height_px": pix.height,
                "dpi": dpi,
            }
        )

    doc.close()

    return {
        "output_dir": str(out_dir.resolve()),
        "rendered_page_count": len(rendered),
        "pages": rendered,
    }


def write_summary_json(out_dir: Path, all_results: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "itp_sbs_summary.json"
    summary_path.write_text(to_pretty_json(all_results), encoding="utf-8")
    return summary_path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PDF를 Parsing → Decoding → Parsing → Resourcing → Rendering 5단계로 처리하고 중간 결과를 출력합니다."
    )
    parser.add_argument("pdf_path", help="입력 PDF 파일 경로")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="렌더링 결과 PNG와 summary JSON을 저장할 디렉터리. 기본값: ./<pdf_stem>_itp_sbs_output",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=144,
        help="렌더링 DPI. 기본값: 144",
    )
    parser.add_argument(
        "--max-ops-preview",
        type=int,
        default=30,
        help="3단계에서 페이지별로 출력할 operator preview 개수. 기본값: 30",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if REQUIRED_IMPORT_ERRORS:
        print("필수 패키지를 import하지 못했습니다.", file=sys.stderr)
        for err in REQUIRED_IMPORT_ERRORS:
            print(f"- {err}", file=sys.stderr)
        print("\n설치 명령:", file=sys.stderr)
        print("  pip install pypdf pymupdf", file=sys.stderr)
        return 1

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}", file=sys.stderr)
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"입력 파일 확장자가 .pdf가 아닙니다: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else Path.cwd() / f"{pdf_path.stem}_itp_sbs_output"

    try:
        reader = load_reader(pdf_path)

        print_header()

        all_results: Dict[str, Any] = {
            "pdf_path": str(pdf_path),
            "steps": {},
        }

        step1 = parse_pdf_structure(pdf_path, reader)
        all_results["steps"]["1_parsing_pdf_structure"] = step1
        print_step_result(1, step1)

        step2 = decode_page_content_streams(reader)
        all_results["steps"]["2_decoding_streams"] = step2
        print_step_result(2, step2)

        step3 = parse_content_streams(reader, max_ops_preview=args.max_ops_preview)
        all_results["steps"]["3_parsing_content_streams"] = step3
        print_step_result(3, step3)

        step4 = resolve_resources(reader)
        all_results["steps"]["4_resourcing"] = step4
        print_step_result(4, step4)

        step5 = render_pdf_to_pngs(pdf_path, out_dir=out_dir, dpi=args.dpi)
        all_results["steps"]["5_rendering"] = step5
        print_step_result(5, step5)

        summary_path = write_summary_json(out_dir, all_results)
        print("최종 결과")
        print(f"- 렌더링 이미지 디렉터리: {out_dir.resolve()}")
        print(f"- 전체 단계 요약 JSON: {summary_path.resolve()}")
        print(LINE)

        return 0

    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("처리 중 오류가 발생했습니다.", file=sys.stderr)
        print(f"- 오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
