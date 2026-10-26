# PDF2CAD — 打印 PDF 图纸转 DXF

[English](README.md) | [简体中文](#中文)

把打印 / 导出的 **矢量 PDF、扫描件与图像图纸** 转换为可编辑的标准 **CAD (DXF)**，
自动还原尺寸标注、符号块、工程表格与几何轮廓，中文与工程符号零乱码。

界面（wxPython）与转换引擎（`pdf2cad.core` / `pdf2cad.ocr`）彻底分离，引擎可独立作为库调用；
文字识别支持 **内置 RapidOCR / 百度 PaddleOCR / LLM** 三条链路，并支持一键打包 Windows exe。

> 架构说明：本项目按参考实现 `pdf2cad_pro.py` 的逻辑严格拆分——引擎各模块与该脚本
> 的 §1–§9 章节一一对应，GUI 为其 §10 wxPython 界面的同构移植，转换结果与参考实现逐字节一致。

---

## 中文

### 功能特性

| 能力 | 说明 |
|------|------|
| 全自动防乱码 | GBK (ANSI_936) 写入 + `txt.shx` / `gbcbig.shx` 国标双字库绑定；GB2312 边界外的字符自动转 `\U+XXXX` |
| 原生标注重建 | `DIMENSION`（线性 / 对齐 / 直径 / 角度）、焊缝 / 引出 / 坡度 / 标高符号块 |
| 工程元素覆盖 | 剖切符号、表面粗糙度、形位公差框 (FCF)、基准符号、技术要求块、工程表格与标题栏 |
| 几何高精度拟合 | 真圆、圆弧 / 倒圆角、相贯线；SVD 微线段点云重建中心线与圆弧 |
| 块定义复用 | 重复符号块归一化 + `INSERT` 实例化，显著减小 DXF 体积 |
| 剖面填充 | 剖面线区域识别并重组为 `HATCH_REGION` |
| 文字识别 | RapidOCR（离线、随包分发，默认）、PaddleOCR（可选，中文更优）、LLM/VLM 接口 |
| 双语界面 | 英文（默认）/ 简体中文，菜单 Language 一键切换；选择记忆于 `~/.pdf2cad/gui.json`，下次启动自动恢复 |
| 扫描件 / 图像输入 | 光栅管线：Otsu 二值化、形态学骨架细化与 Hough 圆检测；无矢量路径的 PDF 自动回退至此 |

### 环境要求

- Python 3.9+
- Windows 10/11（GUI 与 exe 打包在 Windows 上验证；引擎本身跨平台）

### 安装

```bash
pip install -r requirements.txt

# 可选：百度 PaddleOCR（中文工程图纸识别率更高，体积较大）
pip install paddleocr paddlepaddle
```

### 使用

**图形界面**

```bash
python -m pdf2cad
```

主界面为极简文件列表（支持拖拽与多选添加文件/文件夹，不区分单张或批量），
点「开始转换」后进度与结果见下方日志。生成的 DXF 自动附加同一批次统一的
时间戳后缀；OCR 引擎与 LLM 接口在菜单「OCR配置」中调整；界面语言在菜单
「Language」中一键切换（默认英文，选择自动记忆、下次启动恢复）。

**命令行**

```bash
# 单个文件（显式输出名）
python -m pdf2cad 图纸.pdf -o 输出.dxf

# 批量 / 整个目录（自动附加批次时间戳后缀）
python -m pdf2cad 图纸目录 -o 输出目录

# 接入视觉大模型
python -m pdf2cad a.pdf --ocr llm \
    --llm-url http://localhost:8000/v1/chat/completions \
    --llm-model deepseek-ai/DeepSeek-OCR --llm-key sk-xxx
```

**作为库调用**

```python
import pdf2cad

cfg = pdf2cad.EngineConfig(ocr_mode="rapidocr")
stats = pdf2cad.convert_any_to_dxf("图纸.pdf", "输出.dxf", config=cfg)
print(stats)
```

### 识别方式

| `--ocr` | 引擎 | 说明 |
|---------|------|------|
| `rapidocr`（默认） | RapidOCR + ONNX Runtime | 离线运行，模型随包分发 |
| `paddleocr` | 百度 PaddleOCR | 中文识别率更高，需自行安装；未安装时自动退回 RapidOCR |
| `llm` | OpenAI 兼容 / DeepSeek-OCR / Ollama | 只需接口地址、模型名、秘钥 |

纯数字与工程单线符号优先走内置几何拓扑解析（零误差、不调用模型）；
兼容旧写法 `builtin_1` / `auto` / `builtin_2`。

### 输出命名

同一批次的输出共用同一时间戳后缀：`图纸名_YYYYMMDD_HHMMSS.dxf`，
统一保存到各原图所在目录，重复转换不会互相覆盖。

### 打包 exe

```bash
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\python packaging\build_exe.py
```

产物 `dist/PDF2CAD/PDF2CAD.exe`（约 240 MB，含 OCR 模型），双击即用，目标机无需 Python。
`build_exe.py` 会先做环境体检，构建后自动校验产物并执行一次真实图纸端到端冒烟。

### 项目结构

```
PDF2DXF/
├─ pdf2cad/                     # 主包（引擎不依赖 GUI 框架）
│  ├─ version.py                #   版本与版权（唯一来源）
│  ├─ cli.py                    #   命令行入口（无参数自动进 GUI）
│  ├─ core/                     #   转换引擎（对应参考脚本 §1–§9）
│  │  ├─ config.py              #     EngineConfig
│  │  ├─ encoding.py            #     §1 矩阵/颜色/GB2312 边界/防乱码编码器
│  │  ├─ geometry.py            #     §2 圆/圆弧/倒圆角拟合、共线化简
│  │  ├─ text_extract.py        #     §4 PDF 原生文本基线聚类
│  │  ├─ annotations.py         #     §5 DIMENSION 组装
│  │  ├─ contour.py             #     §6a 轮廓优化、虚线/中心线点云重建
│  │  ├─ blocks.py              #     §6b 焊缝/表格/剖面填充/INSERT 复用
│  │  ├─ vector_pdf.py          #     §7 PDF 内容流解析主流程
│  │  ├─ raster.py              #     §8 扫描件/图像矢量化管线
│  │  ├─ dxf_writer.py          #     §9 DXF 写入（GBK + 国标字库）
│  │  └─ converter.py           #     统一入口 convert_any_to_dxf
│  ├─ ocr/                      #   文字识别（对应参考脚本 §3）
│  │  └─ recognizer.py          #     UniversalTextRecognizer：RapidOCR/PaddleOCR/LLM + SHX 拓扑
│  └─ ui/                       #   界面层（对应参考脚本 §10，wxPython）
│     ├─ app.py                 #     主窗口（文件列表 + 一键开始转换）
│     ├─ helpers.py             #     目录扫描/时间戳命名/DPI/打开目录
│     └─ convert_api.py         #     引擎转发薄层
├─ packaging/                   # 打包（spec / build_exe / runtime_hook）
├─ app.py                       # PyInstaller 入口
├─ pyproject.toml               # 安装与元数据
├─ requirements.txt
├─ LICENSE
└─ README.md / README.zh-CN.md
```

**分层规则**：`core/` 与 `ocr/` 不得 import wx；
`ui/` 只通过 `core.converter` 调用引擎，可替换为其它 GUI 框架而不动引擎。

### 开发

```bash
pip install -e ".[dev]"

python -m pyflakes pdf2cad app.py     # 静态检查
python -m pdf2cad --version           # 冒烟
```

打包脚本 `packaging/build_exe.py` 自带环境体检、产物校验与一次真实图纸端到端冒烟；
冒烟所用图纸可用环境变量 `PDF2CAD_SMOKE_PDF` 指定。

### 许可证

本项目采用 **GNU General Public License v3.0** 发布，全文见 [LICENSE](LICENSE)。
你可以自由使用、修改与再分发，但衍生作品同样必须以 GPL-3.0 开源。

### 版权

Copyright (C) 2026 zhangly1403 &lt;zhangly1403@gmail.com&gt;
