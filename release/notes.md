Convert printed or exported PDF drawings into editable CAD DXF, rebuilding dimensions, annotation blocks, engineering tables and geometry with no garbled Chinese or CAD symbols.

Repository: **https://github.com/zly258/PDF2CAD**
(`git@github.com:zly258/PDF2CAD.git`)

## Highlights

- **Reference-faithful engine** — the package is split strictly from the reference
  implementation `pdf2cad_pro.py`: each module maps 1:1 to §1–§9 of that script and the
  wxPython GUI is an isomorphic port of its §10. Conversion output is byte-identical
  to the reference (verified on 4 real drawings, SHA-256 equal).
- **Engine / GUI separated** — `pdf2cad.core` and `pdf2cad.ocr` have no GUI dependency and
  can be used as a library; the wxPython UI reaches them only through `core.converter`.
- **Three recognition engines** — built-in RapidOCR (default, offline, models bundled),
  Baidu PaddleOCR (optional, better Chinese accuracy) and an LLM/VLM endpoint
  (OpenAI-compatible, DeepSeek-OCR, Ollama).
- **Geometric topology first** — pure digits and single-stroke engineering glyphs are
  decoded with no model call.
- **Zero-garbage encoding** — GBK (ANSI_936) output bound to `txt.shx` / `gbcbig.shx`;
  characters outside GB2312 become AutoCAD `\U+XXXX` escapes.
- **Full engineering coverage** — native `DIMENSION`, weld / leader / slope / elevation /
  section / roughness / FCF / datum blocks, engineering tables, title blocks and hatch
  regions.
- **Block reuse** — duplicate symbol blocks are normalised and re-instanced via `INSERT`
  to shrink the DXF.
- **Raster pipeline** — Otsu binarisation, morphological skeleton tracing and Hough
  circle detection for scanned and image input.
- **One-command packaging** — environment check, product verification and a real
  end-to-end smoke conversion.

## Toolchain

| Tool | Version | Role |
|------|---------|------|
| [Python](https://www.python.org/) | 3.12 | Runtime (3.9+ supported) |
| [numpy](https://numpy.org/) | 2.5.4 | Least-squares circle/arc fitting, SVD point-cloud reconstruction |
| [OpenCV (headless)](https://opencv.org/) | 5.0.0 | Raster pipeline: Otsu binarisation, skeleton tracing, Hough circles |
| [Pillow](https://python-pillow.org/) | 13.0.0 | Image I/O and stroke rendering for OCR |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | 0.11.10 | Native PDF text/char extraction with transformation matrices |
| [pypdf](https://github.com/py-pdf/pypdf) | 6.21.2 | PDF content-stream parsing (`m/l/re/c/v/y/h`, Form XObjects, `/OC` layers) |
| [RapidOCR (ONNXRuntime)](https://github.com/RapidAI/RapidOCR) | 1.4.4 | Default offline OCR, PP-OCRv4 models bundled |
| [ONNX Runtime](https://onnxruntime.ai/) | 1.31.0 | Inference backend for RapidOCR |
| [wxPython](https://wxpython.org/) | 4.3.2 | Native minimal desktop GUI ("打印PDF图纸转DXF") |
| [PyInstaller](https://pyinstaller.org/) | 6.22.3 | One-directory Windows exe packaging |
| [pyflakes](https://github.com/PyCQA/pyflakes) | 4.0.3 | Static import/undefined-name checks |

LLM mode uses only the Python standard library (`urllib`) — no extra dependency.
Optional PaddleOCR is not bundled and not required.

## Package layout

```
pdf2cad/
├─ core/    encoding · geometry · text_extract · annotations · contour ·
│           blocks · vector_pdf · raster · dxf_writer · converter · config
├─ ocr/     recognizer (RapidOCR / PaddleOCR / LLM + SHX topology)
└─ ui/      app (wxPython) · helpers · convert_api
```

## Assets

| File | Contents |
|------|----------|
| `PDF2CAD-1.0.0-win64.zip` | Portable Windows build (255 MB unpacked), no Python required. Unzip and run `PDF2CAD.exe`. |
| `PDF2CAD-1.0.0-source.zip` | Source code (English `README.md` plus `README.zh-CN.md`). |

## Requirements

- Windows 10/11 for the GUI and the packaged exe; the engine itself is cross-platform.
- Python 3.9+ when running from source (`pip install -r requirements.txt`).

## License

GPL-3.0. Copyright (C) 2026 zhangly1403 <zhangly1403@gmail.com>
