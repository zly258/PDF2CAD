# -*- coding: utf-8 -*-
# PDF2CAD — 打印 PDF 图纸转 DXF
# Copyright (C) 2026 zhangly1403 <zhangly1403@gmail.com>
#
# 本程序为自由软件：您可依据 GNU 通用公共许可证（GPL）第 3 版或您选择的
# 任何更新版本条款重新分发和/或修改它。
#
# 本程序基于“有用”之目的分发，但不提供任何担保，甚至不含适销性或
# 特定用途适用性的默示担保。详见 GNU 通用公共许可证。
#
# 您应已随本程序收到 GNU 通用公共许可证副本；若无，请见
# <https://www.gnu.org/licenses/>。
"""界面辅助：目录扫描 / 打开目录 / DPI 感知 / 时间戳输出路径（参考脚本 GUI 段同函数）。"""
import os
import sys
from datetime import datetime


SUPPORTED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def _collect_input_files_from_folder(folder_path):
    """扫描指定文件夹下的所有支持图纸文件（排除已生成的 .dxf）。"""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    files = []
    for fn in sorted(os.listdir(folder_path)):
        full_p = os.path.join(folder_path, fn)
        if os.path.isfile(full_p) and os.path.splitext(fn)[1].lower() in SUPPORTED_EXTS:
            files.append(os.path.abspath(full_p))
    return files


def generate_timestamped_dxf_path(input_path: str, batch_ts: str = None, output_dir: str = None) -> str:
    """生成带统一批次时间戳后缀的 DXF 输出路径（如 `图纸名_20261024_214500.dxf`）。"""
    ts = batch_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_name = f"{stem}_{ts}.dxf"
    target_dir = output_dir if (output_dir and os.path.isdir(output_dir)) else os.path.dirname(os.path.abspath(input_path))
    return os.path.join(target_dir, out_name)


def _open_folder_in_explorer(path_str):
    """在系统文件管理器中打开输出目录。"""
    if not path_str:
        return
    target_dir = path_str if os.path.isdir(path_str) else os.path.dirname(os.path.abspath(path_str))
    if not os.path.isdir(target_dir):
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(target_dir)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", target_dir])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target_dir])
    except Exception:
        pass
