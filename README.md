# Introduction-to-Parsers
New Neo SSAFY Coach Session

## 파서학개론

### PDF 해석 순서
`Parsing → Decoding → Parsing → Resourcing → Rendering`

### 첫 번째 `Parsing`
**PDF 파일 구조 파싱**

PDF 파일을 “문서 객체들의 집합”으로 해석하는 것이 목표.

여기서는 아직 페이지를 그리지 않음.

바이트 파일 안에서 PDF의 기본 구조를 찾는다.

주요 작업은 다음과 같이 6개로 구성됨.

1. PDF header 확인
   예: `%PDF-1.7`

2. `xref` 또는 xref stream 해석
   각 객체 번호가 파일의 어느 위치에 있는지 찾습니다.

3. `trailer` 해석
   `/Root`, `/Info`, `/Size`, `/Encrypt` 같은 전역 정보를 읽습니다.

4. indirect object 파싱
   예:

   ```pdf
   12 0 obj
   << /Type /Page ... >>
   endobj
   ```

5. object graph 구성
   `/Catalog → /Pages → /Page` 구조를 따라가며 페이지 목록을 만듭니다.

6. 각 페이지의 `/Contents`, `/Resources`, `/MediaBox`, `/CropBox`, `/Rotate` 등을 찾습니다.

이 단계의 출력은 대략 다음 형태입니다.

```text
PDFDocument
 ├─ Catalog
 ├─ Pages
 ├─ Page objects
 ├─ Content stream references
 └─ Resource dictionaries
```

즉, “PDF 안에 어떤 객체가 있고, 각 페이지가 무엇을 참조하는가”를 알아내는 단계입니다.

두 번째 `Decoding`은 **stream 데이터 복호화/압축 해제**입니다.

역할은 PDF stream 객체의 raw bytes를 실제로 읽을 수 있는 바이트열로 바꾸는 것입니다. PDF의 `/Contents`, 이미지, 폰트 파일 등은 대부분 stream으로 들어 있고, 압축되어 있을 수 있습니다.

주요 작업은 다음입니다.

1. stream 객체의 `/Filter` 확인
   예: `/FlateDecode`, `/ASCII85Decode`, `/DCTDecode`, `/JPXDecode`

2. `/DecodeParms` 적용
   예: PNG predictor, LZW predictor 등

3. 여러 filter가 배열로 연결된 경우 순서대로 적용
   예:

   ```pdf
   /Filter [/ASCII85Decode /FlateDecode]
   ```

4. 암호화된 PDF라면 object 단위 복호화 적용

5. content stream 병합
   `/Contents`가 배열일 수 있으므로 여러 stream을 하나의 명령 스트림으로 합칩니다.

이 단계의 출력은 대략 다음입니다.

```text
decoded content stream bytes
```

예를 들면 압축 해제 전에는 바이너리였던 데이터가 다음처럼 바뀝니다.

```pdf
BT
/F1 12 Tf
100 700 Td
(Hello) Tj
ET
```

즉, “압축된 stream을 읽을 수 있는 명령 바이트열로 만든다”가 이 단계의 목적입니다.

세 번째 `Parsing`은 **content stream 파싱**입니다.

역할은 압축 해제된 content stream을 PDF drawing operator 단위로 해석하는 것입니다. 첫 번째 Parsing이 PDF 파일 구조를 읽는 단계라면, 이 Parsing은 페이지 안의 그리기 명령을 읽는 단계입니다.

주요 작업은 다음입니다.

1. tokenization
   숫자, 이름, 문자열, 배열, 딕셔너리, operator를 분리합니다.

2. graphics operator 파싱
   예:

   ```pdf
   100 100 m
   200 100 l
   S
   ```

3. text operator 파싱
   예:

   ```pdf
   BT
   /F1 12 Tf
   100 700 Td
   (Hello) Tj
   ET
   ```

4. graphics state stack 처리
   `q`, `Q` 처리

5. current transformation matrix 처리
   `cm`, text matrix, line matrix 등

6. operator와 operand를 묶어 중간 표현으로 변환
   예:

   ```python
   Operator("Tf", [Name("F1"), Number(12)])
   Operator("Td", [Number(100), Number(700)])
   Operator("Tj", [String("Hello")])
   ```

이 단계의 출력은 대략 다음입니다.

```text
PageDisplayList
 ├─ SetFont(F1, 12)
 ├─ MoveTextPosition(100, 700)
 ├─ ShowText(...)
 ├─ DrawPath(...)
 └─ PaintImage(...)
```

즉, “페이지 내부의 PDF 명령어를 실행 가능한 형태로 정리한다”가 이 단계의 목적입니다.

네 번째 `Resourcing`은 **리소스 해석 및 연결**입니다.

역할은 content stream 안에서 참조된 이름들을 실제 객체와 연결하는 것입니다. content stream에는 `/F1`, `/Im0`, `/GS1` 같은 이름만 등장합니다. 이 이름들이 실제로 어떤 폰트, 이미지, 그래픽 상태인지 `/Resources`에서 찾아야 합니다.

주요 작업은 다음입니다.

1. font resource 해석
   `/Font` 딕셔너리에서 `/F1`이 어떤 폰트인지 찾습니다.

2. glyph mapping 구성
   `/Encoding`, `/ToUnicode`, `/CIDToGIDMap`, CMap 등을 사용해서 character code를 Unicode 또는 glyph id로 변환합니다.

3. image XObject 해석
   `/XObject`에서 `/Im0` 같은 이미지 객체를 찾고, 이미지 크기, 색공간, bits per component 등을 확인합니다.

4. Form XObject 해석
   다른 content stream을 재귀적으로 렌더링할 수 있게 준비합니다.

5. color space 해석
   `/ColorSpace`, ICC profile, Indexed color space 등을 처리합니다.

6. ExtGState 해석
   투명도, blend mode, line width, overprint 등 그래픽 상태 확장을 연결합니다.

7. resource inheritance 처리
   페이지에 `/Resources`가 없으면 상위 `/Pages` 노드에서 상속받을 수 있습니다.

이 단계의 출력은 대략 다음입니다.

```text
ResolvedPage
 ├─ DisplayList
 ├─ Fonts
 │   └─ F1 → actual font program + encoding + ToUnicode
 ├─ Images
 │   └─ Im0 → decoded image object
 ├─ ColorSpaces
 └─ ExtGStates
```

즉, “명령어 안의 이름 참조를 실제 렌더링 가능한 자원으로 바꾼다”가 이 단계의 목적입니다.

다섯 번째 `Rendering`은 **최종 이미지 생성**입니다.

역할은 앞 단계에서 만든 display list와 resolved resources를 실제 픽셀, 벡터 캔버스, SVG, HTML canvas 등으로 그리는 것입니다.

주요 작업은 다음입니다.

1. page coordinate system 설정
   PDF 좌표계는 보통 왼쪽 아래가 원점이므로 이미지 좌표계와 변환해야 합니다.

2. `/MediaBox`, `/CropBox`, `/Rotate` 적용

3. CTM 적용
   scale, translate, rotate, skew를 실제 좌표에 반영합니다.

4. path 렌더링
   `m`, `l`, `c`, `re`, `S`, `f`, `B` 등 처리

5. text 렌더링
   font, glyph id, text matrix, character spacing, word spacing, horizontal scaling 등을 반영합니다.

6. image 렌더링
   이미지 XObject를 현재 변환 행렬에 맞춰 배치합니다.

7. clipping 처리
   `W`, `W*` 등

8. transparency, blend mode 처리

9. 최종 raster image 또는 vector output 생성
   예: PNG, JPEG, SVG, canvas draw call 등

이 단계의 출력은 최종적으로 사용자가 보는 이미지입니다.

```text
Rendered bitmap / canvas / SVG
```

---

## 다양한 파서들

### Parser

- <https://docs.langchain.com/oss/python/integrations/document_loaders/index#pdfs>
- <https://reference.langchain.com/python/langchain-community/document_loaders/parsers/pdf>
- <https://github.com/pymupdf/PyMuPDF>
- <https://github.com/jsvine/pdfplumber>
- <https://github.com/py-pdf/pypdf>
- <https://github.com/pypdfium2-team/pypdfium2>
- <https://github.com/pdfminer/pdfminer.six>
- <https://github.com/ispras/dedoc>
- <https://github.com/getomni-ai/zerox>
- <https://github.com/bytedance/Dolphin>
- <https://github.com/docling-project/docling>
- <https://github.com/datalab-to/marker>
- <https://github.com/Filimoa/open-parse>
- <https://github.com/Layout-Parser/layout-parser>
- <https://github.com/opendatalab/mineru>
- <https://github.com/opendatalab/PDF-Extract-Kit>

- <https://github.com/run-llama/liteparse> // TypeScript + Python

- <https://github.com/apache/tika> // 자바 parser
- <https://github.com/grobidOrg/grobid> // 자바 parser
- <https://github.com/opendataloader-project/opendataloader-pdf> // 자바 parser

- <https://github.com/Unstructured-IO/unstructured> // 애매함

### OCR

- <https://github.com/allenai/olmocr>
- <https://github.com/aqntks/Easy-Yolo-OCR>
- <https://github.com/deepseek-ai/DeepSeek-OCR>
- <https://github.com/deepseek-ai/DeepSeek-OCR-2>
- <https://github.com/datalab-to/chandra>
- <https://github.com/datalab-to/surya>s
- <https://github.com/ocrmypdf/ocrmypdf>
- <https://github.com/opendatalab/MinerU-Diffusion>
- <https://github.com/PADDLEPADDLE/PADDLEOCR>
- <https://github.com/posicube-services/KolmOCR>
- <https://github.com/tesseract-ocr/tesseract>
- <https://github.com/Tencent-Hunyuan/HunyuanOCR>
- <https://github.com/yuliang-liu/monkeyocr>
- <https://github.com/zai-org/GLM-OCR>
- <https://huggingface.co/nvidia/nemotron-ocr-v2>

### Doc Layout

- <https://github.com/opendatalab/DocLayout-YOLO>

### Table

- <https://github.com/deepdoctection/deepdoctection>
- <https://github.com/microsoft/table-transformer>
- <https://github.com/DevashishPrasad/CascadeTabNet>
