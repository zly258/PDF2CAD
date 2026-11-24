<h1 align="center">PDF2CAD</h1>

<p align="center">Convert printed vector PDFs, scans, and image engineering drawings into editable CAD (DXF) with native dimensions, symbol blocks, and GBK/SHX font support.</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square" alt="Python 3.9+"> <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-4B5563?style=flat-square" alt="Platform: Windows 10/11"> <img src="https://img.shields.io/badge/Version-1.1.0-F59E0B?style=flat-square" alt="Version 1.1.0"> <a href="./LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-22C55E?style=flat-square" alt="License: GPL-3.0"></a>
</p>

PDF2CAD converts printed or exported vector PDFs, scanned PDFs, and raster image drawings into editable DXF files while reconstructing dimensions, engineering symbols, tables, and geometric contours. The wxPython desktop interface (`pdf2cad.ui`) is decoupled from the conversion engine (`pdf2cad.core` and `pdf2cad.ocr`), allowing standalone library usage, CLI batch processing, and single-command Windows executable packaging.

## Highlights

| Highlight | Why it matters |
|---|---|
| Zero-garbage Chinese and symbol encoding | Writes GBK (`ANSI_936`) bound to `txt.shx` and `gbcbig.shx` fonts, escaping characters outside GB2312 as `\U+XXXX`. |
| Native CAD dimensions and blocks | Reconstructs `DIMENSION` entities (linear, aligned, diameter, angular), weld/leader/slope/elevation/roughness/FCF/datum symbols, engineering tables, title blocks, and `HATCH_REGION` areas. |
| High-accuracy geometry and block reuse | Fits true circles, arcs, fillets, and intersection curves; reconstructs centerlines and arcs via SVD; deduplicates repeated symbol blocks with `INSERT` references. |
| Three-tier OCR with SHX topology | Decodes pure digits and single-stroke engineering glyphs via built-in geometric topology, backed by bundled offline RapidOCR, optional PaddleOCR, or an OpenAI-compatible LLM/VLM endpoint. |
| Automatic raster fallback for scans | Processes image inputs and vector-less scanned PDFs with Otsu binarisation, morphological skeleton tracing, and Hough circle detection. |
| Bilingual desktop GUI and CLI | Ships a drag-and-drop wxPython GUI (English / Simplified Chinese, saved in `~/.pdf2cad/gui.json`) alongside a scriptable CLI and Python API. |

## Architecture

The entry layer (`pdf2cad.cli` and `pdf2cad.ui`) invokes the conversion engine exclusively through `core.converter.convert_any_to_dxf`. `core/` and `ocr/` do not import `wx`, so the GUI can be replaced or omitted in headless environments.

```text
┌─────────────────┐    ┌───────────────────┐    ┌───────────────────────┐    ┌─────────────────┐
│   Entry Layer   │    │  Dispatch Engine  │    │  Conversion Pipelines │    │   DXF Output    │
│                 │    │                   │    │                       │    │                 │
│ pdf2cad.cli     │───▶│ core.converter    │───▶│ core.vector_pdf       │───▶│ core.dxf_writer │
│ pdf2cad.ui (wx) │    │ convert_any_to_dxf│    │ (geometry, contour,   │    │ + core.encoding │
│ via convert_api │    │                   │    │  annotations, blocks) │    │ GBK + SHX fonts │
└─────────────────┘    └───────────────────┘    └───────────────────────┘    └─────────────────┘
                                 │                          │                         ▲
                                 │ images                   │ scanned PDF             │
                                 │                          ▼ fallback                │
                                 │              ┌───────────────────────┐             │
                                 └─────────────▶│ core.raster           │─────────────┘
                                                │ (Otsu, skeleton,      │
                                                │  Hough circles)       │
                                                └───────────────────────┘
                                                            ▲
                                                            │ OCR / SHX topology
                                                ┌───────────────────────┐
                                                │ ocr.recognizer        │
                                                │ RapidOCR / PaddleOCR  │
                                                │ / LLM + SHX topology  │
                                                └───────────────────────┘
```

Key package directories:

- `pdf2cad/core/`: Conversion engine (`config.py`, `encoding.py`, `geometry.py`, `text_extract.py`, `annotations.py`, `contour.py`, `blocks.py`, `vector_pdf.py`, `raster.py`, `dxf_writer.py`, `converter.py`).
- `pdf2cad/ocr/`: `recognizer.py` (`UniversalTextRecognizer` with RapidOCR, PaddleOCR, LLM, and SHX topology).
- `pdf2cad/ui/`: wxPython GUI (`app.py`, `helpers.py`, `convert_api.py`).
- `packaging/`: PyInstaller build script (`build_exe.py`), spec (`pdf2cad.spec`), and runtime hook (`runtime_hook.py`).

## Quick Install

Install runtime dependencies from source:

```bash
pip install -r requirements.txt
```

Optional extras:

```bash
# Optional: Baidu PaddleOCR (higher accuracy on Chinese engineering drawings; large download)
pip install paddleocr paddlepaddle

# Optional: editable package install with dev tools (pyinstaller, pyflakes)
pip install -e ".[dev]"
```

**Prerequisites:**

- Python 3.9 or higher.
- Windows 10/11 for the wxPython GUI and PyInstaller executable build (`wxPython` is installed automatically on `win32`). The conversion engine (`pdf2cad.core` and `pdf2cad.ocr`) is cross-platform.

## Quick Start

Launch the desktop GUI (no arguments):

```bash
python -m pdf2cad
```

Drag and drop PDF or image files (or folders) into the file list and click **Start**. Converted DXF files are written next to the source drawings with a shared batch timestamp suffix (`drawing_YYYYMMDD_HHMMSS.dxf`), and progress is printed in the log pane.

Or convert a single drawing directly from the command line:

```bash
python -m pdf2cad drawing.pdf -o out.dxf
```

The command writes `out.dxf` and prints a JSON summary of reconstructed entities and conversion statistics.

## Commands and CLI Options

If installed as a package (`pip install -e .`), the `pdf2cad` and `pdf2cad-gui` console entry points are also available in addition to `python -m pdf2cad`.

```bash
# Single file with explicit output path
python -m pdf2cad drawing.pdf -o out.dxf

# Batch conversion for a directory (appends a shared YYYYMMDD_HHMMSS timestamp suffix)
python -m pdf2cad drawing_dir -o out_dir

# Modern DXF R2000 LWPOLYLINE output for smaller files
python -m pdf2cad drawing.pdf -o out.dxf --lwpolyline

# Use an OpenAI-compatible LLM/VLM endpoint (set LLM_API_KEY in environment)
python -m pdf2cad drawing.pdf -o out.dxf --ocr llm \
  --llm-url http://localhost:8000/v1/chat/completions \
  --llm-model deepseek-ai/DeepSeek-OCR \
  --llm-key "$LLM_API_KEY"
```

| Flag | Default | Description |
|---|---|---|
| `input` | *(none)* | Input PDF/image path(s) or folder(s). Launching with no input starts the GUI. |
| `-o`, `--output` | *(none)* | Output `.dxf` file path (single file) or output directory (batch). |
| `--scale` | `None` | Manual scale factor in mm/pt. Omit for automatic 1:1 calibration from dimensions. |
| `--ocr` | `rapidocr` | OCR backend: `rapidocr`, `paddleocr`, or `llm` (legacy aliases `builtin_1`, `builtin_2`, `auto` are accepted). |
| `--llm-url` | `$LLM_API_URL` or `http://localhost:8000/v1/chat/completions` | OpenAI-compatible chat completions endpoint URL. |
| `--llm-model` | `$LLM_MODEL` or `deepseek-ai/DeepSeek-OCR` | Vision/OCR model identifier. |
| `--llm-key` | `$LLM_API_KEY` | API key for the LLM endpoint. |
| `--lwpolyline` | `False` | Emit DXF R2000 (`AC1015`) `LWPOLYLINE` entities instead of `POLYLINE` to reduce file size. |
| `--gui` | `False` | Force launching the wxPython GUI. |
| `-v`, `--version` | — | Print version and copyright information. |

### Output Naming

In GUI and batch CLI modes, all files converted in one run share a single timestamp suffix (`<name>_YYYYMMDD_HHMMSS.dxf`), written next to each source file (or inside `-o` when an output directory is specified) so repeated runs do not overwrite earlier outputs.

## Python API

```python
import pdf2cad

cfg = pdf2cad.EngineConfig(ocr_mode="rapidocr")
stats = pdf2cad.convert_any_to_dxf("drawing.pdf", "out.dxf", config=cfg)
print(stats)
```

Public entry points exported by `pdf2cad`:

- `EngineConfig`: Dataclass for OCR mode, LLM endpoint settings, `user_scale`, `use_lwpolyline`, and `output_dir`.
- `convert_any_to_dxf(input_path, output_dxf_path, config=None)`: Dispatches `.pdf` to the vector pipeline (with raster fallback) and other extensions to the raster pipeline.
- `convert_pdf_to_dxf(pdf_path, out_dxf_path, config=None)`: Vector PDF pipeline with automatic scanned-page fallback.
- `convert_image_to_dxf(img_path, out_dxf_path, config=None, target_width_mm=841.0)`: Raster image pipeline.

## Configuration and Packaging

### OCR Modes

| `--ocr` / `ocr_mode` | Backend | Notes |
|---|---|---|
| `rapidocr` (default) | RapidOCR + ONNX Runtime | Fully offline with bundled PP-OCRv4 models. |
| `paddleocr` | Baidu PaddleOCR | Optional install (`pip install paddleocr paddlepaddle`); falls back to RapidOCR when unavailable. |
| `llm` | OpenAI-compatible / DeepSeek-OCR / Ollama | Uses standard library `urllib`; requires endpoint URL, model name, and API key via flags or environment variables. |

Pure digits and single-stroke engineering glyphs are decoded first by the built-in geometric topology parser without invoking an OCR model.

### Environment Variables and GUI Settings

- `OCR_MODE`: Default `EngineConfig.ocr_mode` (default: `rapidocr`).
- `LLM_API_URL`, `LLM_MODEL`, `LLM_API_KEY`: Default LLM endpoint configuration.
- `DXF_LWPOLYLINE`: Set to `1`, `true`, or `yes` to enable `LWPOLYLINE` output by default.
- `PDF2CAD_SMOKE_PDF`: Optional path to a sample drawing used by `packaging/build_exe.py` for end-to-end smoke testing.
- `~/.pdf2cad/gui.json`: Stores GUI preferences such as the selected interface language (`Language` menu, English by default) and OCR configuration (`OCR Config` menu).

### Building the Windows Executable

```bash
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\python packaging\build_exe.py
```

This produces a standalone onedir bundle at `dist/PDF2CAD/PDF2CAD.exe` (around 240 MB including OCR models) that runs without Python installed. `build_exe.py` also supports `--check` (environment check only) and `--clean-only`.

### Development Checks

```bash
python -m pyflakes pdf2cad app.py
python -m pdf2cad --version
```

## Community & Support

- Source repository and issue tracker: [zly258/PDF2CAD](https://github.com/zly258/PDF2CAD)
- Sponsor the author: [Afdian](https://ifdian.net/order/create?user_id=3db8e630e6dc11f1b37452540025c377)

## License

Released under the **GNU General Public License v3.0**. See [LICENSE](./LICENSE) for the full text.

Copyright (C) 2026 zhangly1403 <zhangly1403@gmail.com>
