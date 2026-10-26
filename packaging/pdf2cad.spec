# -*- coding: utf-8 -*-
"""
PyInstaller 打包配置（由 packaging/build_exe.py 调用，也可直接
`pyinstaller packaging/pdf2cad.spec`）。

目标：单目录 exe，只带必要依赖
    解析：numpy / opencv / Pillow / pdfplumber / pypdf
    OCR ：rapidocr_onnxruntime + onnxruntime（模型权重以数据文件随包分发）
    GUI ：wxPython（极简桌面界面，与 pdf2cad_pro.py 一致）
默认不含：Tkinter / PaddleOCR / Tesseract / torch / tensorflow（PaddleOCR 为可选引擎，见 excludes）

刻意不做两件事：
    - 不启用 UPX：避免杀软误报，启动也更快；
    - 不用 optimize=2：保留 docstring 与断言，行为与源码完全一致。
"""
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

NAME = "PDF2CAD"

here = os.path.dirname(os.path.abspath(SPEC))   # noqa: F821  PyInstaller 注入 spec 文件路径
ROOT = os.path.dirname(here)                     # 项目根目录
PKG = os.path.join(ROOT, "pdf2cad")

# ---------------------------------------------------------------- 数据文件
datas = []
# RapidOCR：config.yaml + models/*.onnx（约 16 MB）。
# 该库按自身 __file__ 定位模型，collect_data_files 会保持相对目录结构，冻结后可直接命中。
datas += collect_data_files("rapidocr_onnxruntime")

binaries = []
try:
    binaries += collect_dynamic_libs("onnxruntime")
except Exception:
    pass

hiddenimports = [
    "rapidocr_onnxruntime",
    "onnxruntime",
    "pyclipper",
    "shapely",
    "yaml",
    "pypdfium2",
    # wxPython GUI（PyInstaller 自带 wx 钩子）
    "wx",
]

# ---------------------------------------------------------------- 排除项
# 明确排除旧的识别/界面链路，防止被间接引入而撑大体积
excludes = [
    # 百度 PaddleOCR 是「可选」引擎（--ocr paddleocr）：
    # 仅当用户自行 pip install paddleocr paddlepaddle 后才可用，故不进 exe。
    # 源码通过 importlib 延迟导入，排除它不会影响默认 RapidOCR / LLM 链路。
    "paddleocr", "paddle", "paddlepaddle",
    "pytesseract",
    # 旧 Tkinter 界面已由 wxPython 取代，整体排除
    "tkinter",
    "torch", "torchvision", "torchaudio", "transformers", "tokenizers",
    "tensorflow", "tensorboard", "keras", "jax",
    "PyQt5", "PySide2", "PySide6", "gi",
    "matplotlib", "scipy", "sklearn", "pandas", "sympy", "mpmath",
    "notebook", "IPython", "jupyter", "pytest",
    "unittest", "pydoc_data",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(here, "runtime_hook.py")],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

# ---------------------------------------------------------------- 体积裁剪
# 本程序只用到 cv2 的图像算子（threshold / findContours / HoughCircles / polylines /
# GaussianBlur / morphology），完全不做视频与摄像头读写。PyInstaller 的 opencv 钩子会把
# opencv_videoio_ffmpeg*.dll（约 29 MB）一并收进来，这里剔除。
# numpy 的 MKL/OpenBLAS 后端保留（矩阵最小二乘拟合需要），不做裁剪以免影响数值行为。
def _drop(binaries, *keywords):
    keep = []
    for item in binaries:
        dest = str(item[0]).lower()
        if any(k in dest for k in keywords):
            continue
        keep.append(item)
    return keep


_before = len(a.binaries)
a.binaries = _drop(a.binaries, "videoio", "ffmpeg")
print("PDF2CAD spec: 剔除视频后端二进制 %d 个（%d -> %d）" % (_before - len(a.binaries), _before, len(a.binaries)))

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # GUI 程序：不弹黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)

# 注：LICENSE / README 由 build_exe.copy_release_files() 在构建后复制到 exe 同级目录。
# 不放在 datas 里，是因为 datas 会把文件塞进 _internal/，用户看不到。
