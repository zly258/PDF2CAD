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
"""原生 PDF 文本提取与基线聚类器（支持表格竖线阻断、空格恢复、重影去重与字高校准）（参考脚本 §4）。"""
import math
import re

import pdfplumber
import numpy as np

from .encoding import (
    GDT_SYMBOL_MAP,
    auto_fix_pdf_mojibake,
    restore_english_spacing,
    rgb_to_aci,
)


# ==============================================================================
# 4. 原生 PDF 文本提取与基线聚类器（支持表格竖线阻断、空格恢复、重影去重与字高校准）
# ==============================================================================

def extract_sorted_pdf_texts(pdf_path, bt_records, escaped_slashes=None, all_strokes_pt=None, page_index=0):
    escaped_slashes = escaped_slashes or []
    all_strokes_pt = all_strokes_pt or []
    out_groups = []

    # 收集图纸中的竖直分隔线段（如标题栏/明细表单元格竖线），防止同一行不同单元格的文字跨竖线合并
    vert_barriers = []
    for st in all_strokes_pt:
        pts = st['pts']
        for k in range(len(pts) - 1):
            p0, p1 = pts[k], pts[k + 1]
            if abs(p0[0] - p1[0]) < 1.5 and abs(p1[1] - p0[1]) > 6.0:
                vx = 0.5 * (p0[0] + p1[0])
                vy0, vy1 = min(p0[1], p1[1]), max(p0[1], p1[1])
                vert_barriers.append((vx, vy0, vy1))

    def crosses_vertical_barrier(c1, c2):
        if abs(c1["angle"]) > 5.0:
            return False
        x_left = min(c1["e"], c2["e"]) + 0.5
        x_right = max(c1["e"], c2["e"]) - 0.5
        if x_right <= x_left:
            return False
        ym = 0.5 * (c1["f"] + c2["f"])
        fh = max(c1["font_h"], c2["font_h"])
        for vx, vy0, vy1 in vert_barriers:
            if x_left < vx < x_right and (vy0 + 0.5 <= ym <= vy1 - 0.5):
                return True
        return False

    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[min(page_index, len(pdf.pages) - 1)]
        char_items = []
        seen_char_pos = set()

        for ch in p.chars:
            txt_raw = auto_fix_pdf_mojibake(ch["text"])
            if not txt_raw or not txt_raw.strip():
                continue
            a, b, c_mat, d_mat, e, f_mat = ch["matrix"]
            raw_angle = math.degrees(math.atan2(b, a))
            if abs(raw_angle) < 1.5:
                angle = 0.0
            elif abs(raw_angle - 90.0) < 1.5:
                angle = 90.0
            elif abs(raw_angle + 90.0) < 1.5 or abs(raw_angle - 270.0) < 1.5:
                angle = -90.0
            else:
                angle = raw_angle

            rad = math.radians(angle)
            font_h = abs(ch["width"] * math.sin(rad)) + abs(ch["height"] * math.cos(rad))
            char_w = abs(ch["width"] * math.cos(rad)) + abs(ch["height"] * math.sin(rad))
            if txt_raw not in (".", "-", "_"):
                font_h = max(font_h, 2.0)
            fn_name = str(ch.get("fontname", "")).upper()
            c_txt = GDT_SYMBOL_MAP.get(txt_raw, txt_raw) if "GDT" in fn_name else txt_raw

            # 过滤同坐标重影字符（防止 CAD 虚拟打印加粗导致 '250x200' 变成 '225500xx220000'、'下' 变成 '下下'）
            dedup_key = (c_txt, round(e, 1), round(f_mat, 1), round(angle, 0))
            if dedup_key in seen_char_pos:
                continue
            seen_char_pos.add(dedup_key)

            color = ch.get("non_stroking_color") or (1.0, 1.0, 1.0)
            along = e * math.cos(rad) + f_mat * math.sin(rad)
            perp = -e * math.sin(rad) + f_mat * math.cos(rad)
            char_items.append({
                "txt": c_txt,
                "e": e,
                "f": f_mat,
                "angle": 90.0 if abs(angle) == 90.0 else angle,
                "rad": rad,
                "font_h": font_h,
                "char_w": max(char_w, font_h * 0.35),
                "along": along,
                "perp": perp,
                "color": color,
            })

        for sx, sy, s_ang, s_fh in escaped_slashes:
            if not any(math.hypot(c["e"] - sx, c["f"] - sy) < s_fh * 0.25 and c["txt"] == "/" for c in char_items):
                rad = math.radians(s_ang)
                along = sx * math.cos(rad) + sy * math.sin(rad)
                perp = -sx * math.sin(rad) + sy * math.cos(rad)
                char_items.append({
                    "txt": "/",
                    "e": sx,
                    "f": sy,
                    "angle": 90.0 if abs(s_ang) == 90.0 else s_ang,
                    "rad": rad,
                    "font_h": s_fh,
                    "char_w": s_fh * 0.35,
                    "along": along,
                    "perp": perp,
                    "color": (0.0, 0.0, 0.0),
                })

        used = [False] * len(char_items)
        for i in range(len(char_items)):
            if used[i]:
                continue
            seed = char_items[i]
            used[i] = True
            cluster = [seed]
            changed = True
            while changed:
                changed = False
                a_min = min(c["along"] for c in cluster)
                a_max = max(c["along"] + c["char_w"] for c in cluster)
                base_perp = float(np.median([c["perp"] for c in cluster]))
                non_dot_hs = [c["font_h"] for c in cluster if c["txt"] not in (".", "°", "/")]
                base_h = max(non_dot_hs) if non_dot_hs else max(c["font_h"] for c in cluster)
                has_pm = any("%%p" in c["txt"] for c in cluster)
                for j in range(len(char_items)):
                    if used[j]:
                        continue
                    cand = char_items[j]
                    if abs(cand["rad"] - seed["rad"]) > 0.05:
                        continue
                    if abs(cand["perp"] - base_perp) > base_h * 0.20:
                        continue
                    if cand["txt"] not in (".", "°", "/"):
                        h_ratio = min(cand["font_h"], base_h) / max(cand["font_h"], base_h)
                        allow_small = (
                            has_pm
                            or ("%%p" in cand["txt"])
                            or (cand["txt"] in ("h", "F", "H", "g", "6", "7") and any("%%c" in c["txt"] or "M" in c["txt"] for c in cluster))
                        )
                        if h_ratio < (0.62 if allow_small else 0.86):
                            continue
                    c_start = cand["along"]
                    c_end = cand["along"] + cand["char_w"]
                    max_gap = base_h * 0.44
                    if (a_min - max_gap <= c_end) and (c_start <= a_max + max_gap):
                        # 仅当字符间存在明显跨单元格间隙 (char_gap > base_h * 0.08) 时检查是否跨越表格竖线，防止工程图中紧邻字符（如 250x200）压过背景轮廓竖线时被误拆
                        nearest_c = min(cluster, key=lambda c: abs(c["along"] - cand["along"]))
                        char_gap = max(cand["along"] - (nearest_c["along"] + nearest_c["char_w"]), nearest_c["along"] - (cand["along"] + cand["char_w"]))
                        if char_gap > base_h * 0.08 and crosses_vertical_barrier(nearest_c, cand):
                            continue
                        cluster.append(cand)
                        used[j] = True
                        changed = True

            cluster.sort(key=lambda c: c["along"])
            parts = []
            for k_c, c in enumerate(cluster):
                if k_c > 0:
                    prev_c = cluster[k_c - 1]
                    gap = c["along"] - (prev_c["along"] + prev_c["char_w"])
                    if gap > prev_c["font_h"] * 0.12:
                        p_ch = prev_c["txt"][-1] if prev_c["txt"] else ""
                        n_ch = c["txt"][0] if c["txt"] else ""
                        if (p_ch.isascii() and n_ch.isascii()) and not (p_ch in "+-" or n_ch in ".,:"):
                            parts.append(" ")
                parts.append(c["txt"])
            raw_str = "".join(parts)
            if "()" in raw_str and len(raw_str) > 2:
                inner = raw_str.replace("()", "").strip()
                raw_str = f"({inner})"
            raw_str = re.sub(r'^Rc\s*(\d)/(\d)$', r'Rc \1/\2', raw_str)
            raw_str = restore_english_spacing(raw_str)

            sx, sy = cluster[0]["e"], cluster[0]["f"]
            ex = cluster[-1]["e"] + cluster[-1]["char_w"] * math.cos(seed["rad"])
            ey = cluster[-1]["f"] + cluster[-1]["char_w"] * math.sin(seed["rad"])
            non_dot_hs = [c["font_h"] for c in cluster if c["txt"] not in (".", "°", "/")]
            max_h = max(non_dot_hs) if non_dot_hs else max(c["font_h"] for c in cluster)
            best_bt = min(bt_records, key=lambda r: math.hypot(r[0] - sx, r[1] - sy)) if bt_records else (0, 0, "0", 0)
            aci = rgb_to_aci(seed["color"])
            layer = best_bt[2]
            if layer == "0" and aci == 3:
                layer = "DIM"
            out_groups.append({
                "text": raw_str,
                "x": sx,
                "y": sy,
                "end_x": ex,
                "end_y": ey,
                "cx": 0.5 * (sx + ex),
                "cy": 0.5 * (sy + ey),
                "font_h": max_h,
                "angle": seed["angle"],
                "aci": aci,
                "layer": layer,
                "stream_pos": best_bt[3],
            })
    return out_groups
