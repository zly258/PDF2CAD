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
"""光栅图像 / 扫描件 PDF 转 CAD 重绘管线（含 OCR 文字剥离与正交/圆弧/共线轮廓重构）（参考脚本 §8）。"""
import math
import os

import cv2
import numpy as np
import pdfplumber

from .contour import merge_collinear_lines
from .dxf_writer import write_standard_dxf
from .geometry import fit_circle_or_arc, simplify_collinear_pts
from ..ocr.recognizer import UniversalTextRecognizer
from .config import EngineConfig


def convert_pdf_page_via_raster_fallback(pdf_path, out_dxf_path, config: EngineConfig = None, page_index: int = 0):
    """当输入 PDF 为扫描件（无矢量路径）时，自动提取/渲染页面图像并交由光栅转 CAD 管线处理。"""
    import tempfile
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[min(page_index, len(pdf.pages) - 1)]
        pil_img = p.to_image(resolution=250).original
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_png = tf.name
    try:
        pil_img.save(tmp_png)
        return convert_raster_image_to_dxf(tmp_png, out_dxf_path, config=config)
    finally:
        if os.path.exists(tmp_png):
            os.remove(tmp_png)


def convert_raster_image_to_dxf(img_path, out_dxf_path, config: EngineConfig = None, target_width_mm=841.0):
    cfg = config or EngineConfig()
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Cannot read image: {img_path}")
    h, w = img.shape
    scale = cfg.user_scale if cfg.user_scale is not None else (target_width_mm / float(w))

    # 采用自适应光照不变的 Otsu 二值化阈值，兼容暗底/灰底扫描图纸与手机拍照图纸
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    texts_out = []

    # 检测光栅图中的文字框并将其转换为原生 TEXT，同时从二值图中抹除文字像素以免产生碎骨架线（支持 RapidOCR 与 百度 PaddleOCR）
    recognizer = UniversalTextRecognizer(cfg)
    mode_low = cfg.ocr_mode.lower()
    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if mode_low in ("rapidocr", "rapid", "builtin_1", "auto"):
        rapid_inst = recognizer.get_rapid_ocr()
        if rapid_inst is not None:
            try:
                out_r = rapid_inst(img_rgb)
                res_r = out_r[0] if isinstance(out_r, tuple) else out_r
                if res_r and isinstance(res_r, list):
                    for item in res_r:
                        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], (list, tuple)):
                            box, txt = item[0], str(item[1])
                            if txt and txt.strip():
                                bx = [pt[0] for pt in box]
                                by = [pt[1] for pt in box]
                                x0, x1 = int(max(0, min(bx) - 2)), int(min(w, max(bx) + 2))
                                y0, y1 = int(max(0, min(by) - 2)), int(min(h, max(by) + 2))
                                bw[y0:y1, x0:x1] = 0
                                tx_mm = float(min(bx)) * scale
                                ty_mm = float(h - max(by)) * scale
                                th_mm = max(2.5, float(max(by) - min(by)) * scale * 0.75)
                                texts_out.append(("TEXT", 3, txt.strip(), tx_mm, ty_mm, th_mm, 0.0))
            except Exception:
                pass
    elif mode_low in ("paddleocr", "paddle", "builtin_2"):
        paddle_inst = recognizer.get_paddle_ocr()
        if paddle_inst is not None:
            try:
                res = paddle_inst.ocr(img_rgb)
                if res and res[0] and isinstance(res[0], list):
                    for item in res[0]:
                        if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], list):
                            box = item[0]
                            txt = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                            if txt and txt.strip():
                                bx = [pt[0] for pt in box]
                                by = [pt[1] for pt in box]
                                x0, x1 = int(max(0, min(bx) - 2)), int(min(w, max(bx) + 2))
                                y0, y1 = int(max(0, min(by) - 2)), int(min(h, max(by) + 2))
                                bw[y0:y1, x0:x1] = 0
                                tx_mm = float(min(bx)) * scale
                                ty_mm = float(h - max(by)) * scale
                                th_mm = max(2.5, float(max(by) - min(by)) * scale * 0.75)
                                texts_out.append(("TEXT", 3, txt.strip(), tx_mm, ty_mm, th_mm, 0.0))
            except Exception:
                pass

    skel = np.zeros(bw.shape, np.uint8)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    temp = bw.copy()
    while True:
        eroded = cv2.erode(temp, element)
        dilated = cv2.dilate(eroded, element)
        skel = cv2.bitwise_or(skel, cv2.subtract(temp, dilated))
        temp = eroded
        if cv2.countNonZero(temp) == 0:
            break

    raw_lines, circles_out, arcs_out, polylines_out = [], [], [], []

    blurred = cv2.GaussianBlur(img, (5, 5), 1.2)
    detected_circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=25, param1=100, param2=38, minRadius=8, maxRadius=80
    )
    if detected_circles is not None:
        for c in np.round(detected_circles[0, :]).astype("int"):
            cx_mm = float(c[0]) * scale
            cy_mm = float(h - c[1]) * scale
            r_mm = float(c[2]) * scale
            circles_out.append(("MAIN_PLAN", 4, cx_mm, cy_mm, r_mm))

    contours, _ = cv2.findContours(skel, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    for cnt in contours:
        if len(cnt) < 4:
            continue
        raw_pts = [(float(pt[0][0]) * scale, float(h - pt[0][1]) * scale) for pt in cnt]
        if len(raw_pts) >= 12:
            fit_res = fit_circle_or_arc(raw_pts, rel_tol=0.04, layer_name="MAIN_PLAN", scale_Hint=scale)
            if fit_res is not None:
                kind, cx, cy, r, a0, a1 = fit_res
                if kind == 'CIRCLE':
                    circles_out.append(("MAIN_PLAN", 4, cx, cy, r))
                else:
                    arcs_out.append(("MAIN_PLAN", 4, cx, cy, r, a0, a1))
                continue

        approx = cv2.approxPolyDP(cnt, 1.5, False)
        pts = [(float(pt[0][0]) * scale, float(h - pt[0][1]) * scale) for pt in approx]
        pts = simplify_collinear_pts(pts, tol=0.5 * scale)
        for i in range(1, len(pts)):
            dx = pts[i][0] - pts[i - 1][0]
            dy = pts[i][1] - pts[i - 1][1]
            seg_len = math.hypot(dx, dy)
            if seg_len > 1.0:
                if abs(dy) / seg_len < 0.045:
                    pts[i] = (pts[i][0], pts[i - 1][1])
                elif abs(dx) / seg_len < 0.045:
                    pts[i] = (pts[i - 1][0], pts[i][1])
        if len(pts) == 2:
            raw_lines.append(("MAIN_PLAN", 4, pts[0], pts[1]))
        elif len(pts) > 2:
            polylines_out.append(("MAIN_PLAN", 4, pts, False))

    lines_out = merge_collinear_lines(raw_lines, angle_tol_sin=0.02, perp_tol=1.2 * scale, gap_tol=2.5 * scale)
    all_layers = ["0", "MAIN_PLAN", "TEXT"]
    write_standard_dxf(out_dxf_path, all_layers, lines_out, circles_out, arcs_out, polylines_out, [], texts_out, [], [])
    return {
        "mode": "raster_image",
        "lines": len(lines_out),
        "circles": len(circles_out),
        "arcs": len(arcs_out),
        "polylines": len(polylines_out),
        "texts": len(texts_out),
    }
