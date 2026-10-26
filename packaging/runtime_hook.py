# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子（在应用代码之前执行）。

做两件打包后必须处理的事：
1. 限制 BLAS/OMP 线程数（沿用原脚本行为，避免 OCR 与矩阵运算抢核）；
2. 安装全局异常钩子：窗口化 exe 没有控制台，未捕获异常会“静默失败”，
   这里把堆栈写到 exe 同级的 error.log，用户可直接反馈。

注：RapidOCR 依据自身 __file__ 定位 config.yaml 与 models/*.onnx，
spec 里 collect_data_files("rapidocr_onnxruntime") 已保持相对布局，无需额外改路径。
"""
import os
import sys


def _limit_threads():
    for var in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")


def _ensure_stdio():
    """console=False 时 sys.stdout/stderr 为 None，argparse 的 --help/--version 会崩。

    补一个空写入对象，使 CLI 参数在窗口化 exe 下仍可安全调用（输出丢弃）。
    """
    if getattr(sys, "frozen", False) and sys.stdout is None:
        class _Null:
            encoding = "utf-8"

            def write(self, *_a, **_k):
                return 0

            def flush(self):
                pass

            def isatty(self):
                return False

            def writable(self):
                return False

        sys.stdout = sys.stderr = _Null()


def _install_excepthook():
    app_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                              else __file__))
    log_path = os.path.join(app_dir, "error.log")

    def hook(exc_type, exc, tb):
        try:
            import traceback
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write("\n===== %s =====\n" % _now())
                traceback.print_exception(exc_type, exc, tb, file=fh)
        except Exception:
            pass
        # 仍交给默认处理（窗口模式下会被 PyInstaller 吞掉）
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    def _now():
        import datetime
        return datetime.datetime.now().isoformat(timespec="seconds")

    sys.excepthook = hook
    try:
        import threading
        threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)
    except Exception:
        pass


_limit_threads()
_ensure_stdio()
_install_excepthook()
