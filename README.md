# PDF2CAD — Print PDF Drawings to DXF

[English](#english) | [简体中文](README.zh-CN.md)

Convert printed / exported **vector PDFs, scans and image drawings** into editable
standard **CAD (DXF)**, automatically rebuilding dimensions, annotation blocks,
engineering tables and geometry — with zero garbled Chinese or engineering symbols.

The GUI (wxPython) and the conversion engine (`pdf2cad.core` / `pdf2cad.ocr`) are fully
separated, so the engine can be used as a standalone library. Text recognition supports
**built-in RapidOCR / Baidu PaddleOCR / LLM**, and the project packages into a Windows
exe in one command.

> Architecture note: this project is split strictly from the reference implementation
> `pdf2cad_pro.py` — each engine module maps 1:1 to §1–§9 of that script, the GUI is an
> isomorphic port of its §10 wxPython interface, and conversion output is byte-identical
> to the reference.

---

## English

### Features

| Capability | Details |
|------|------|
| Zero-garbage encoding | Writes GBK (ANSI_936) and binds the `txt.shx` / `gbcbig.shx` national fonts; characters outside GB2312 become `\U+XXXX` escapes |
| Native dimensions | `DIMENSION` entities (linear / aligned / diameter / angular) plus weld, leader, slope and elevation symbol blocks |
| Engineering coverage | Section marks, surface roughness, FCF frames, datum symbols, tech-note blocks, engineering tables and title blocks |
| High-accuracy geometry | True circles, arcs / fillets, intersection curves; SVD-based centre-line and arc reconstruction from micro-segment point clouds |
| Block reuse | Duplicate symbol blocks are normalised and re-instanced via `INSERT`, shrinking the DXF |
| Hatch regions | Section-hatch areas are detected and reassembled as `HATCH_REGION` |
| Text recognition | RapidOCR (offline, models bundled, default), PaddleOCR (optional, better on Chinese), or an LLM/VLM endpoint |
| Bilingual GUI | English (default) / 简体中文, switchable from the "Language" menu; the choice is remembered in `~/.pdf2cad/gui.json` |
| Scanned / image input | Raster pipeline: Otsu binarisation, morphological skeleton tracing and Hough circle detection; scanned PDFs without vector paths fall back to it automatically |

### Requirements

- Python 3.9+
- Windows 10/11 (the GUI and exe packaging are verified on Windows; the engine itself is cross-platform)

### Installation

```bash
pip install -r requirements.txt

# Optional: Baidu PaddleOCR (better on Chinese engineering drawings; large download)
pip install paddleocr paddlepaddle
```

### Usage

**GUI**

```bash
python -m pdf2cad
```

Add drawings to the minimalist file list (drag-and-drop, multi-select, files or folders —
no single/batch switch), then click "Start". Progress and results appear in the log below.
Generated DXF files get a shared batch timestamp suffix. OCR engine and LLM endpoint live
under menu "OCR Config". Switch the interface language under menu "Language"
(English by default; the choice is remembered for the next launch).

**Command line**

```bash
# Single file (explicit output name)
python -m pdf2cad drawing.pdf -o out.dxf

# Batch / whole directory (a shared batch timestamp suffix is appended)
python -m pdf2cad drawing_dir -o out_dir

# LLM / VLM endpoint
python -m pdf2cad a.pdf --ocr llm \
    --llm-url http://localhost:8000/v1/chat/completions \
    --llm-model deepseek-ai/DeepSeek-OCR --llm-key sk-xxx
```

**As a library**

```python
import pdf2cad

cfg = pdf2cad.EngineConfig(ocr_mode="rapidocr")
stats = pdf2cad.convert_any_to_dxf("drawing.pdf", "out.dxf", config=cfg)
print(stats)
```

### Recognition modes

| `--ocr` | Engine | Notes |
|---------|--------|-------|
| `rapidocr` (default) | RapidOCR + ONNX Runtime | Fully offline, models bundled |
| `paddleocr` | Baidu PaddleOCR | Better Chinese accuracy; install separately, falls back to RapidOCR when absent |
| `llm` | OpenAI-compatible / DeepSeek-OCR / Ollama | Only needs URL, model name and key |

Pure digits and single-stroke engineering glyphs are decoded first by the built-in
geometric topology engine (exact, no model calls). Legacy names `builtin_1` / `auto` /
`builtin_2` remain accepted.

### Output naming

All outputs of one batch share a single timestamp suffix:
`drawing_YYYYMMDD_HHMMSS.dxf`, written next to each source drawing, so repeated
runs never overwrite each other.

### Building the exe

```bash
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\python packaging\build_exe.py
```

Output: `dist/PDF2CAD/PDF2CAD.exe` (about 240 MB with OCR models). Double-click to run,
no Python required on the target machine. `build_exe.py` checks the environment first,
then verifies the product and runs a real end-to-end smoke conversion.

### Project layout

```
PDF2DXF/
├─ pdf2cad/                     # Main package (engine has no GUI dependency)
│  ├─ version.py                #   Version & copyright (single source of truth)
│  ├─ cli.py                    #   CLI entry (no args → GUI)
│  ├─ core/                     #   Conversion engine (maps to reference §1–§9)
│  │  ├─ config.py              #     EngineConfig
│  │  ├─ encoding.py            #     §1 matrices, colours, GB2312 bounds, anti-mojibake
│  │  ├─ geometry.py            #     §2 circle / arc / fillet fitting, collinear reduction
│  │  ├─ text_extract.py        #     §4 native PDF text baseline clustering
│  │  ├─ annotations.py         #     §5 DIMENSION assembly
│  │  ├─ contour.py             #     §6a contour cleanup, dashed / centreline rebuild
│  │  ├─ blocks.py              #     §6b weld / table / hatch / INSERT-reuse blocks
│  │  ├─ vector_pdf.py          #     §7 PDF content-stream main pipeline
│  │  ├─ raster.py              #     §8 scan / raster-image pipeline
│  │  ├─ dxf_writer.py          #     §9 DXF writer (GBK + national fonts)
│  │  └─ converter.py           #     Single entry point convert_any_to_dxf
│  ├─ ocr/                      #   Text recognition (maps to reference §3)
│  │  └─ recognizer.py          #     UniversalTextRecognizer: RapidOCR/PaddleOCR/LLM + SHX topology
│  └─ ui/                       #   UI layer (maps to reference §10, wxPython)
│     ├─ app.py                 #     Main window (file list + one-click convert)
│     ├─ helpers.py             #     Folder scan / timestamp naming / DPI / open folder
│     └─ convert_api.py         #     Thin engine forwarder
├─ packaging/                   # Packaging (spec / build_exe / runtime_hook)
├─ app.py                       # PyInstaller entry point
├─ pyproject.toml               # Packaging & metadata
├─ requirements.txt
├─ LICENSE
└─ README.md / README.zh-CN.md
```

**Layering rule**: `core/` and `ocr/` must not import wx; `ui/` reaches the engine
only through `core.converter`, so the GUI can be replaced without touching the engine.

### Development

```bash
pip install -e ".[dev]"

python -m pyflakes pdf2cad app.py     # static check
python -m pdf2cad --version           # smoke test
```

`packaging/build_exe.py` performs an environment check, product verification and a real
end-to-end smoke conversion. Point `PDF2CAD_SMOKE_PDF` at a drawing to choose the sample.

### License

Released under the **GNU General Public License v3.0** — see [LICENSE](LICENSE).
You may use, modify and redistribute it freely, but derivative works must also be
open-sourced under GPL-3.0.

### Copyright

Copyright (C) 2026 zhangly1403 &lt;zhangly1403@gmail.com&gt;
