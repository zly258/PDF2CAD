<h1 align="center">PDF2CAD</h1>

<p align="center">将打印的矢量 PDF、扫描件与图像工程图纸转换为可编辑 CAD (DXF)，自动重建原生尺寸标注、符号块并支持 GBK/SHX 国标字库。</p>

<p align="center">
  <a href="./README.md">English</a> | <a href="./README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square" alt="Python 3.9+"> <img src="https://img.shields.io/badge/Platform-Windows%2010%2F11-4B5563?style=flat-square" alt="Platform: Windows 10/11"> <img src="https://img.shields.io/badge/Version-1.1.0-F59E0B?style=flat-square" alt="Version 1.1.0"> <a href="./LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-22C55E?style=flat-square" alt="License: GPL-3.0"></a>
</p>

PDF2CAD 可将打印或导出的矢量 PDF、扫描件 PDF 及光栅图像图纸转换为可编辑的标准 DXF 文件，自动还原尺寸标注、工程符号、表格与几何轮廓。项目将 wxPython 桌面界面（`pdf2cad.ui`）与转换引擎（`pdf2cad.core`、`pdf2cad.ocr`）彻底解耦，既可作为独立 Python 库与命令行工具使用，也支持一键打包为 Windows 独立可执行程序。

## 核心亮点

| 核心能力 | 实际价值 |
|---|---|
| 中文与工程符号防乱码 | 采用 GBK（`ANSI_936`）编码并绑定 `txt.shx` / `gbcbig.shx` 国标双字库，GB2312 范围外字符自动转义为 `\U+XXXX`。 |
| 原生标注与工程符号重建 | 重建线性、对齐、直径、角度 `DIMENSION` 实体，以及焊缝、引出、坡度、标高、粗糙度、形位公差框 (FCF)、基准、工程表格、标题栏与 `HATCH_REGION` 剖面填充。 |
| 高精度几何拟合与块复用 | 拟合真圆、圆弧、倒圆角与相贯线，基于 SVD 点云重建中心线与圆弧，并对重复符号块归一化后以 `INSERT` 实例化复用。 |
| 三选一 OCR 与 SHX 拓扑解析 | 纯数字与单线工程字形优先走内置几何拓扑引擎解析，复杂文本支持内置离线 RapidOCR、可选百度 PaddleOCR 或 OpenAI 兼容 LLM/VLM 接口。 |
| 扫描件自动光栅回退 | 图像输入与无矢量路径的扫描件 PDF 自动走光栅管线，执行 Otsu 二值化、形态学骨架细化与 Hough 圆检测。 |
| 双语桌面界面与命令行 | 提供支持拖拽的 wxPython 极简界面（英文/简体中文，配置保存在 `~/.pdf2cad/gui.json`），同时提供命令行批量处理与 Python API。 |

## 架构设计

入口层（`pdf2cad.cli` 与 `pdf2cad.ui`）仅通过 `core.converter.convert_any_to_dxf` 调用转换引擎。`core/` 与 `ocr/` 不导入 `wx`，可在无界面环境中独立运行或替换为其他 GUI 框架。

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

核心目录说明：

- `pdf2cad/core/`：转换引擎（`config.py`、`encoding.py`、`geometry.py`、`text_extract.py`、`annotations.py`、`contour.py`、`blocks.py`、`vector_pdf.py`、`raster.py`、`dxf_writer.py`、`converter.py`）。
- `pdf2cad/ocr/`：`recognizer.py`（`UniversalTextRecognizer`，集成 RapidOCR、PaddleOCR、LLM 与 SHX 拓扑解析）。
- `pdf2cad/ui/`：wxPython 界面层（`app.py`、`helpers.py`、`convert_api.py`）。
- `packaging/`：PyInstaller 打包脚本（`build_exe.py`）、配置（`pdf2cad.spec`）与运行期钩子（`runtime_hook.py`）。

## 快速安装

从源码安装运行依赖：

```bash
pip install -r requirements.txt
```

可选依赖：

```bash
# 可选：百度 PaddleOCR（中文工程图纸识别率更高，体积较大）
pip install paddleocr paddlepaddle

# 可选：可编辑安装并附带开发依赖（pyinstaller、pyflakes）
pip install -e ".[dev]"
```

**环境要求：**

- Python 3.9 及以上版本。
- wxPython 桌面界面与 Windows exe 打包在 Windows 10/11 上验证（`win32` 平台自动安装 `wxPython`）；转换引擎（`pdf2cad.core` 与 `pdf2cad.ocr`）本身跨平台。

## 快速开始

不带参数直接启动桌面图形界面：

```bash
python -m pdf2cad
```

将 PDF 或图像文件（或整个文件夹）拖入文件列表，点击 **开始转换** 即可。生成的 DXF 文件默认保存在原图同目录下并附加统一批次时间戳后缀（`drawing_YYYYMMDD_HHMMSS.dxf`），转换进度与统计信息显示在下方日志区。

也可以直接通过命令行转换单个图纸：

```bash
python -m pdf2cad drawing.pdf -o out.dxf
```

命令执行后会写出 `out.dxf`，并在终端输出包含图元统计信息的 JSON 摘要。

## 命令与 CLI 参数

通过 `pip install -e .` 安装后，除 `python -m pdf2cad` 外，还可直接使用 `pdf2cad` 与 `pdf2cad-gui` 命令入口。

```bash
# 单文件转换（显式指定输出路径）
python -m pdf2cad drawing.pdf -o out.dxf

# 目录批量转换（自动附加同一批次 YYYYMMDD_HHMMSS 时间戳后缀）
python -m pdf2cad drawing_dir -o out_dir

# 输出 DXF R2000 LWPOLYLINE 轻量多段线以减小文件体积
python -m pdf2cad drawing.pdf -o out.dxf --lwpolyline

# 接入 OpenAI 兼容视觉大模型接口（通过环境变量 LLM_API_KEY 传入密钥）
python -m pdf2cad drawing.pdf -o out.dxf --ocr llm \
  --llm-url http://localhost:8000/v1/chat/completions \
  --llm-model deepseek-ai/DeepSeek-OCR \
  --llm-key "$LLM_API_KEY"
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `input` | *(无)* | 输入 PDF/图像路径或目录；不提供时启动图形界面。 |
| `-o`, `--output` | *(无)* | 输出 `.dxf` 文件路径（单文件）或输出目录（批量）。 |
| `--scale` | `None` | 手动指定比例（毫米/磅）；留空时依据尺寸标注自动 1:1 标定。 |
| `--ocr` | `rapidocr` | 识别引擎：`rapidocr`、`paddleocr` 或 `llm`（兼容旧别名 `builtin_1`、`builtin_2`、`auto`）。 |
| `--llm-url` | `$LLM_API_URL` 或 `http://localhost:8000/v1/chat/completions` | OpenAI 兼容对话补全接口地址。 |
| `--llm-model` | `$LLM_MODEL` 或 `deepseek-ai/DeepSeek-OCR` | 视觉/OCR 模型名称。 |
| `--llm-key` | `$LLM_API_KEY` | LLM 接口 API 密钥。 |
| `--lwpolyline` | `False` | 使用 DXF R2000（`AC1015`）`LWPOLYLINE` 替代 `POLYLINE`，显著减小输出体积。 |
| `--gui` | `False` | 强制启动 wxPython 图形界面。 |
| `-v`, `--version` | — | 输出版本号与版权信息。 |

### 输出命名规则

在图形界面和命令行批量模式下，同一次转换的所有输出共用同一个时间戳后缀（`<原文件名>_YYYYMMDD_HHMMSS.dxf`），默认写入各自原图所在目录（或在指定 `-o` 目录时写入该目录），避免重复转换互相覆盖。

## Python API

```python
import pdf2cad

cfg = pdf2cad.EngineConfig(ocr_mode="rapidocr")
stats = pdf2cad.convert_any_to_dxf("drawing.pdf", "out.dxf", config=cfg)
print(stats)
```

`pdf2cad` 导出的公开接口：

- `EngineConfig`：配置数据类，包含 OCR 模式、LLM 接口参数、`user_scale`、`use_lwpolyline` 与 `output_dir`。
- `convert_any_to_dxf(input_path, output_dxf_path, config=None)`：按扩展名自动分派 `.pdf` 至矢量管线（含扫描件回退），其余图像分派至光栅管线。
- `convert_pdf_to_dxf(pdf_path, out_dxf_path, config=None)`：矢量 PDF 转换入口，无矢量路径时自动回退光栅管线。
- `convert_image_to_dxf(img_path, out_dxf_path, config=None, target_width_mm=841.0)`：光栅图像/扫描件转换入口。

## 配置与打包

### OCR 识别模式

| `--ocr` / `ocr_mode` | 引擎 | 说明 |
|---|---|---|
| `rapidocr`（默认） | RapidOCR + ONNX Runtime | 完全离线运行，内置 PP-OCRv4 模型随包分发。 |
| `paddleocr` | 百度 PaddleOCR | 需额外安装（`pip install paddleocr paddlepaddle`）；未安装时自动退回 RapidOCR。 |
| `llm` | OpenAI 兼容 / DeepSeek-OCR / Ollama | 仅依赖标准库 `urllib`，通过参数或环境变量配置接口地址、模型名与密钥。 |

纯数字与工程单线字形优先由内置几何拓扑解析器直接识别，无需调用 OCR 模型。

### 环境变量与界面配置

- `OCR_MODE`：`EngineConfig.ocr_mode` 默认值（默认 `rapidocr`）。
- `LLM_API_URL`、`LLM_MODEL`、`LLM_API_KEY`：LLM 接口默认配置。
- `DXF_LWPOLYLINE`：设为 `1`、`true` 或 `yes` 时默认启用 `LWPOLYLINE` 输出。
- `PDF2CAD_SMOKE_PDF`：可选，指定 `packaging/build_exe.py` 打包后进行端到端冒烟测试的示例图纸路径。
- `~/.pdf2cad/gui.json`：记录图形界面偏好，包括界面语言（`Language` 菜单，默认英文）与 OCR 配置（`OCR配置` 菜单）。

### 打包 Windows 可执行程序

```bash
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\python packaging\build_exe.py
```

构建产物位于 `dist/PDF2CAD/PDF2CAD.exe`（单目录分发，含 OCR 模型约 240 MB），目标机无需安装 Python 即可双击运行。`build_exe.py` 同时支持 `--check`（仅环境体检）与 `--clean-only`（仅清理构建产物）。

### 开发检查

```bash
python -m pyflakes pdf2cad app.py
python -m pdf2cad --version
```

## 社区与支持

- 源码仓库与问题反馈：[zly258/PDF2CAD](https://github.com/zly258/PDF2CAD)
- 赞助支持作者：[爱发电 (Afdian)](https://ifdian.net/order/create?user_id=3db8e630e6dc11f1b37452540025c377)

## 许可证

本项目基于 **GNU General Public License v3.0** 开源发布，完整条款见 [LICENSE](./LICENSE)。

Copyright (C) 2026 zhangly1403 <zhangly1403@gmail.com>
