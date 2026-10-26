# -*- coding: utf-8 -*-
"""
build_exe.py — 一键打包 Windows 单目录 exe。

    python packaging/build_exe.py            # 清理并打包
    python packaging/build_exe.py --clean-only
    python packaging/build_exe.py --check    # 只校验环境与依赖是否齐全

设计要点：
    - 单目录（onedir）而非单文件：onnxruntime 与 OCR 模型解压更快、启动不卡、少被杀软盯上；
    - 打包前先做依赖体检，缺包直接报错并给出 pip 命令，而不是产出一个打不开的 exe；
    - 打包后自动校验产物（模型、体积、依赖白名单、可启动性）。
"""
import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPEC = os.path.join(HERE, "pdf2cad.spec")
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
APP_NAME = "PDF2CAD"

RUNTIME_DEPS = [
    ("numpy", "numpy"),
    ("cv2", "opencv-python"),
    ("PIL", "Pillow"),
    ("pdfplumber", "pdfplumber"),
    ("pypdf", "pypdf"),
    ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
    ("onnxruntime", "onnxruntime"),
    ("wx", "wxPython（pip install wxPython -f https://extras.wxpython.org/wxPython/4.x/）"),
]

# 明确不应出现在打包环境里的重依赖
MUST_NOT_IMPORT = ["paddleocr", "torch", "tensorflow"]


def run(cmd, **kw):
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, **kw)


def check_env(report_only=False):
    missing = []
    print("环境体检（当前解释器：%s）" % sys.executable)
    for mod, pkg in RUNTIME_DEPS:
        try:
            __import__(mod)
            print("  [OK]   %-22s" % mod)
        except Exception as exc:
            missing.append((mod, pkg))
            print("  [MISS] %-22s %s" % (mod, exc.__class__.__name__))
    for mod in MUST_NOT_IMPORT:
        try:
            __import__(mod)
            print("  [WARN] %-22s 已安装，会被间接拉入，建议卸载或换干净虚拟环境" % mod)
        except Exception:
            print("  [OK]   %-22s 未安装（符合最小依赖）" % ("not-" + mod))
    if missing:
        print("\n缺少必需依赖：")
        print("  pip install " + " ".join(p for _m, p in missing if not p.startswith("（")))
        return False
    if report_only:
        print("\n体检通过")
    return True


def clean():
    for d in (BUILD, DIST):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            print("已清理 %s" % d)
    for f in ("pdf2cad.egg-info",):
        p = os.path.join(ROOT, f)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def copy_release_files():
    """把许可证与说明复制到 exe 同级目录。

    GPL-3.0 要求随分发提供许可证副本；PyInstaller 的 `datas` 会把文件放进
    `_internal/`，用户在资源管理器里看不到，因此在构建后显式复制。
    """
    app_dir = os.path.join(DIST, APP_NAME)
    if not os.path.isdir(app_dir):
        return
    for name in ("LICENSE", "README.md", "README.zh-CN.md"):
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(app_dir, name))
            print("已复制 %s -> %s" % (name, os.path.relpath(app_dir, ROOT)))


def verify():
    """校验产物：关键文件存在、体积合理、exe 能启动并退出。"""
    app_dir = os.path.join(DIST, APP_NAME)
    exe = os.path.join(app_dir, APP_NAME + ".exe")
    ok = True
    if not os.path.isfile(exe):
        print("FAIL: 未找到 %s" % exe)
        return False
    print("产物：%s (%.1f MB)" % (exe, os.path.getsize(exe) / 1048576.0))

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(app_dir) for f in fs)
    print("总体积：%.1f MB" % (total / 1048576.0))

    internal = os.path.join(app_dir, "_internal")
    if not os.path.isdir(internal):
        internal = app_dir  # 旧版 PyInstaller 布局

    # RapidOCR 布局：config.yaml 与 models/*.onnx 不在同一目录，分开查找
    ocr_pkg = None
    for cand in (os.path.join(internal, "rapidocr_onnxruntime"),
                 os.path.join(app_dir, "rapidocr_onnxruntime")):
        if os.path.isdir(cand):
            ocr_pkg = cand
            break
    if ocr_pkg:
        cfg = os.path.join(ocr_pkg, "config.yaml")
        models = os.path.join(ocr_pkg, "models")
        onnx = sorted(f for f in os.listdir(models) if f.endswith(".onnx")) if os.path.isdir(models) else []
        print("  [%s] OCR 配置             %s" % ("OK" if os.path.isfile(cfg) else "FAIL",
                                                 os.path.relpath(cfg, app_dir)))
        print("  [%s] OCR 模型             %d 个：%s" % ("OK" if len(onnx) >= 2 else "FAIL",
                                                       len(onnx), ", ".join(onnx)))
        if len(onnx) < 2:
            ok = False
    else:
        print("  [FAIL] 未找到 rapidocr_onnxruntime 包目录")
        ok = False

    # GPL-3.0 要求随分发提供许可证副本
    lic = os.path.join(app_dir, "LICENSE")
    if os.path.isfile(lic):
        print("  [OK]   LICENSE 许可证        %s" % os.path.relpath(lic, app_dir))
    else:
        print("  [FAIL] 缺少 LICENSE（GPL-3.0 要求随分发提供）")
        ok = False

    # 不应出现的重依赖（说明排除项生效）。wx 是本程序 GUI 必需依赖，不在此列
    for junk in ("paddleocr", "torch", "PyQt5", "tensorflow", "tkinter"):
        if os.path.isdir(os.path.join(internal, junk)):
            print("  [FAIL] 意外打包了 %s" % junk)
            ok = False
    # 不应再随包分发已删除的图标资源
    if os.path.isdir(os.path.join(internal, "pdf2cad", "resources")):
        print("  [FAIL] 残留图标资源目录 pdf2cad/resources")
        ok = False

    # 端到端冒烟：用真实图纸跑一次转换。--version 只能证明进程能起，
    # 而打包最常见的失败是 numpy/cv2/onnxruntime 的原扩展在冻结环境加载不了。
    ok = smoke_convert(exe, app_dir) and ok
    err_log = os.path.join(app_dir, "error.log")
    if os.path.isfile(err_log):
        print("  [WARN] 运行产生 error.log：")
        with open(err_log, "r", encoding="utf-8", errors="replace") as fh:
            print("    " + fh.read()[-1200:].replace("\n", "\n    "))
        ok = False
    return ok


def smoke_convert(exe, app_dir):
    """调用打包后的 exe 完成一次 PDF -> DXF，校验产物为合法 GBK DXF。"""
    pdf = os.environ.get("PDF2CAD_SMOKE_PDF") or _find_sample_pdf()
    if not pdf:
        print("  [SKIP] 端到端转换：未找到测试 PDF（可用 PDF2CAD_SMOKE_PDF 指定）")
        return True
    tmp = os.path.join(app_dir, "_smoke")
    os.makedirs(tmp, exist_ok=True)
    out = os.path.join(tmp, "smoke.dxf")
    if os.path.isfile(out):
        os.remove(out)
    print("  端到端：使用 %s" % os.path.basename(pdf))
    try:
        p = subprocess.run([exe, pdf, "-o", out, "--ocr", "rapidocr"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=app_dir, timeout=600)
    except subprocess.TimeoutExpired:
        print("  [FAIL] 端到端转换超时（600s）")
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    if p.returncode != 0:
        print("  [FAIL] 退出码 %d" % p.returncode)
        print("    " + ((p.stdout or "")[-400:] + "\n" + (p.stderr or "")[-1200:]).replace("\n", "\n    "))
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    if not os.path.isfile(out) or os.path.getsize(out) < 2000:
        print("  [FAIL] 未生成有效 DXF（%s）" % (out,))
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    try:
        text = open(out, "rb").read().decode("gbk")
    except UnicodeDecodeError as exc:
        print("  [FAIL] DXF 不是合法 GBK 编码：%s" % exc)
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    good = text.rstrip().endswith("EOF") and "SECTION" in text and "txt.shx" in text
    print("  [%s] 端到端转换 生成 %.1f KB DXF，GBK 解码与结构校验%s"
          % ("OK" if good else "FAIL", os.path.getsize(out) / 1024.0,
             "通过" if good else "失败"))
    shutil.rmtree(tmp, ignore_errors=True)
    return good


def _find_sample_pdf():
    """为端到端冒烟找一个可用的 PDF。

    优先使用环境变量 `PDF2CAD_SMOKE_PDF` 指定的文件；否则在项目根目录与
    上一级目录里找尺寸合理的 PDF。找不到时冒烟步骤会跳过（不算失败）。
    """
    env = os.environ.get("PDF2CAD_SMOKE_PDF")
    if env and os.path.isfile(env):
        return env
    for d in (ROOT, os.path.dirname(ROOT)):
        if not os.path.isdir(d):
            continue
        try:
            for fn in sorted(os.listdir(d)):
                p = os.path.join(d, fn)
                if fn.lower().endswith(".pdf") and os.path.getsize(p) > 20000:
                    return p
        except OSError:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只做环境体检")
    ap.add_argument("--clean-only", action="store_true", help="只清理构建目录")
    ap.add_argument("--no-clean", action="store_true", help="跳过清理，增量构建")
    ap.add_argument("--no-verify", action="store_true", help="跳过产物校验")
    args = ap.parse_args()

    if args.clean_only:
        clean()
        return 0
    if not check_env(report_only=args.check):
        return 1
    if args.check:
        return 0

    if not args.no_clean:
        clean()

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC]
    p = run(cmd)
    if p.returncode != 0:
        print("\n打包失败，退出码 %d" % p.returncode)
        return p.returncode

    copy_release_files()

    if args.no_verify:
        return 0
    print("\n=== 产物校验 ===")
    return 0 if verify() else 1


if __name__ == "__main__":
    sys.exit(main())
