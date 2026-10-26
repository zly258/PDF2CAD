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
"""统一转换入口：按扩展名自动分派矢量 PDF 或光栅图像管线（与参考脚本 `convert_any_to_dxf` 一致）。"""
import os

from .config import EngineConfig
from .raster import convert_raster_image_to_dxf
from .vector_pdf import convert_vector_pdf_to_dxf


def convert_pdf_to_dxf(pdf_path, out_dxf_path, config: EngineConfig = None):
    """矢量 PDF（含扫描件自动回退光栅管线）转 DXF。"""
    return convert_vector_pdf_to_dxf(pdf_path, out_dxf_path, config=config or EngineConfig())


def convert_image_to_dxf(img_path, out_dxf_path, config: EngineConfig = None, target_width_mm=841.0):
    """图像 / 扫描件转 DXF。"""
    return convert_raster_image_to_dxf(
        img_path, out_dxf_path, config=config or EngineConfig(), target_width_mm=target_width_mm
    )


def convert_any_to_dxf(input_path, output_dxf_path, config: EngineConfig = None):
    """按扩展名自动选择管线，行为与参考脚本 `convert_any_to_dxf` 完全一致。"""
    cfg = config or EngineConfig()
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".pdf":
        return convert_vector_pdf_to_dxf(input_path, output_dxf_path, config=cfg)
    return convert_raster_image_to_dxf(input_path, output_dxf_path, config=cfg)
