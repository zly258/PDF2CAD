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
"""复合标注块组装器：引出线/粗糙度/形位公差/基准/标高/坡度/表格/标题栏/剖面填充块与块引用归一化（参考脚本 §6 后半）。"""
import re
import math
from collections import defaultdict

import numpy as np

from .encoding import (
    is_annotation_layer,
    is_pure_dim_or_text_layer,
    is_title_or_frame_layer,
    parse_dimension_numeric_value,
)
from .geometry import simplify_collinear_pts


def _weld_leader_geometry(polylines_rel, lines_rel, tol=0.6):
    """
    通用引出线几何拓扑焊合器：
    将引出标注块（LEADER_MARK / CALLOUT_MARK / WELD_MARK / FCF_MARK / BALLOON_MARK）内的分段开放折线与水平/斜向直线段
    自动按端点容差焊接为从引线起点 (0, 0) 到文字台面末端的连续 POLYLINE，消去共线冗余点与折线/直线割裂。
    """
    closed_polys = []
    chains = []
    default_lay = "DIM"
    default_aci = 3
    for p_lay, p_aci, pts, is_cl in polylines_rel:
        default_lay, default_aci = p_lay, p_aci
        if is_cl or len(pts) < 2:
            closed_polys.append((p_lay, p_aci, pts, is_cl))
        else:
            chains.append((p_lay, p_aci, list(pts)))
    for l_lay, l_aci, p0, p1 in lines_rel:
        default_lay, default_aci = l_lay, l_aci
        chains.append((l_lay, l_aci, [p0, p1]))

    if len(chains) <= 1:
        if len(chains) == 1 and len(chains[0][2]) >= 3:
            c_lay, c_aci, c_pts = chains[0]
            if math.hypot(c_pts[-1][0], c_pts[-1][1]) < math.hypot(c_pts[0][0], c_pts[0][1]):
                c_pts = list(reversed(c_pts))
            return closed_polys + [(c_lay, c_aci, simplify_collinear_pts(c_pts, tol=0.06), False)], []
        return polylines_rel, lines_rel

    used = [False] * len(chains)
    welded_chains = []
    for i in range(len(chains)):
        if used[i]:
            continue
        c_lay, c_aci, curr = chains[i]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(chains)):
                if used[j]:
                    continue
                _, _, cand = chains[j]
                if math.hypot(curr[-1][0] - cand[0][0], curr[-1][1] - cand[0][1]) <= tol:
                    curr = curr + cand[1:]
                    used[j] = True
                    changed = True
                elif math.hypot(curr[-1][0] - cand[-1][0], curr[-1][1] - cand[-1][1]) <= tol:
                    curr = curr + list(reversed(cand))[1:]
                    used[j] = True
                    changed = True
                elif math.hypot(curr[0][0] - cand[-1][0], curr[0][1] - cand[-1][1]) <= tol:
                    curr = cand[:-1] + curr
                    used[j] = True
                    changed = True
                elif math.hypot(curr[0][0] - cand[0][0], curr[0][1] - cand[0][1]) <= tol:
                    curr = list(reversed(cand))[:-1] + curr
                    used[j] = True
                    changed = True
        curr = simplify_collinear_pts(curr, tol=0.06)
        if math.hypot(curr[-1][0], curr[-1][1]) < math.hypot(curr[0][0], curr[0][1]):
            curr = list(reversed(curr))
        # 消除共线 180° 折返重叠段（如引线台面长短线重叠或箭头杆部与主引线在原点折返）
        fold_changed = True
        while fold_changed and len(curr) >= 3:
            fold_changed = False
            if math.hypot(curr[-1][0], curr[-1][1]) < math.hypot(curr[0][0], curr[0][1]):
                curr = list(reversed(curr))
            for idx_f in range(len(curr) - 2):
                pa, pb, pc = curr[idx_f], curr[idx_f + 1], curr[idx_f + 2]
                v1x, v1y = pb[0] - pa[0], pb[1] - pa[1]
                v2x, v2y = pc[0] - pb[0], pc[1] - pb[1]
                l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
                if l1 < 1e-4:
                    curr.pop(idx_f)
                    fold_changed = True
                    break
                if l2 < 1e-4:
                    curr.pop(idx_f + 2)
                    fold_changed = True
                    break
                sin_a = abs(v1x * v2y - v1y * v2x) / (l1 * l2)
                cos_a = (v1x * v2x + v1y * v2y) / (l1 * l2)
                if sin_a <= 0.16:
                    if cos_a > 0:
                        curr.pop(idx_f + 1)
                        fold_changed = True
                        break
                    else:
                        if idx_f == 0:
                            p_st = pa if math.hypot(pa[0], pa[1]) <= math.hypot(pb[0], pb[1]) else pb
                            curr[0:3] = [p_st, pc]
                        else:
                            p_ed = pb if math.hypot(pb[0] - pa[0], pb[1] - pa[1]) >= math.hypot(pc[0] - pa[0], pc[1] - pa[1]) else pc
                            curr[idx_f:idx_f + 3] = [pa, p_ed]
                        fold_changed = True
                        break
        welded_chains.append((c_lay, c_aci, curr))

    out_polys = list(closed_polys)
    out_lines = []
    for c_lay, c_aci, c_pts in welded_chains:
        if len(c_pts) >= 3:
            out_polys.append((c_lay, c_aci, c_pts, False))
        elif len(c_pts) == 2:
            out_lines.append((c_lay, c_aci, c_pts[0], c_pts[1]))
    return out_polys, out_lines


def merge_same_cell_justified_texts(texts_out, lines_out, polylines_out):
    """
    合并标题栏/明细表同一单元格内因两端分散对齐而被拆开的双字中文词组（如 '制'+'图'->'制图'、'设'+'计'->'设计'、'日'+'期'->'日期'）
    以及同行短英文词（如 'Made'+'by'->'Made by'），严格保证中间不跨越任何竖直分隔线。
    """
    if len(texts_out) <= 1:
        return texts_out
    v_segs = []
    for _, _, p0, p1 in lines_out:
        if abs(p0[0] - p1[0]) <= 0.5 and abs(p1[1] - p0[1]) >= 4.0:
            v_segs.append((0.5 * (p0[0] + p1[0]), min(p0[1], p1[1]), max(p0[1], p1[1])))
    for _, _, pts, is_cl in polylines_out:
        n_v = len(pts)
        for k in range(n_v if is_cl else n_v - 1):
            p0, p1 = pts[k], pts[(k + 1) % n_v]
            if abs(p0[0] - p1[0]) <= 0.5 and abs(p1[1] - p0[1]) >= 4.0:
                v_segs.append((0.5 * (p0[0] + p1[0]), min(p0[1], p1[1]), max(p0[1], p1[1])))

    def crosses_v_line(x1, x2, ym):
        xa, xb = min(x1, x2) + 0.4, max(x1, x2) - 0.4
        if xb <= xa:
            return False
        return any(xa < vx < xb and (vy0 - 0.5 <= ym <= vy1 + 0.5) for vx, vy0, vy1 in v_segs)

    # 过滤掉遗留旧图纸中误落在几何轮廓层 DRAW-IN 上的孤立单数字伪影（如轴肩处的 '4'）
    cleaned = [
        t for t in texts_out
        if not (str(t[0]).upper() == "DRAW-IN" and len(str(t[2]).strip()) == 1 and str(t[2]).strip().isdigit())
    ]
    cleaned.sort(key=lambda t: (round(t[4], 1), t[3]))
    merged = []
    for t in cleaned:
        if merged:
            prev = merged[-1]
            p_lay, p_aci, p_txt, px, py, p_th, p_ang = prev
            c_lay, c_aci, c_txt, cx, cy, c_th, c_ang = t
            if (
                p_lay == c_lay
                and abs(p_ang) <= 2.0
                and abs(c_ang) <= 2.0
                and abs(py - cy) <= max(p_th, c_th) * 0.22
                and abs(p_th - c_th) <= max(p_th, c_th) * 0.20
            ):
                dx = cx - px
                p_s, c_s = p_txt.strip(), c_txt.strip()
                is_two_cjk = (
                    len(p_s) == 1 and len(c_s) == 1
                    and (0x4E00 <= ord(p_s) <= 0x9FFF) and (0x4E00 <= ord(c_s) <= 0x9FFF)
                    and (0 < dx <= p_th * 5.2)
                )
                is_eng_pair = (
                    is_title_or_frame_layer(p_lay)
                    and p_s.isalpha() and c_s.isalpha()
                    and len(p_s) <= 8 and len(c_s) <= 4
                    and (0 < dx <= p_th * 16.0)
                )
                if (is_two_cjk or is_eng_pair) and not crosses_v_line(px, cx, 0.5 * (py + cy)):
                    join_str = (p_s + c_s) if is_two_cjk else (p_s + " " + c_s)
                    merged[-1] = (p_lay, p_aci, join_str, px, py, p_th, p_ang)
                    continue
        merged.append(t)
    return merged


def detect_and_assemble_tables(lines_out, polylines_out, texts_out, alen_mm):
    """
    通用工程表格与标题栏/明细表自动检测与结构化块封装器 (TABLE_BLOCK / TITLE_TABLE)：
    1. 自动寻找图纸中由闭合矩形外框与内部正交水平/垂直网格线构成的工程表格（如参数表、地脚螺栓表、荷载表、标题栏、修改栏、会签栏）；
    2. 自动合并同属一个标题栏区域的相邻/叠放子表框（如主标题栏与顶部代号栏），并排除整个图幅的外图框边界 (area > 35% 图幅总面积)；
    3. 将表格外框、内部行列分隔线、单元格文字及紧邻表头正上方的表名文字统一封装为 TABLE_BLOCK_k / TITLE_TABLE_k 块定义与 INSERT 引用。
    """
    all_x = [p[0] for _, _, p0, p1 in lines_out for p in (p0, p1)] + [p[0] for _, _, pts, _ in polylines_out for p in pts]
    all_y = [p[1] for _, _, p0, p1 in lines_out for p in (p0, p1)] + [p[1] for _, _, pts, _ in polylines_out for p in pts]
    if not all_x or not all_y:
        return lines_out, polylines_out, texts_out, []

    draw_w = max(max(all_x) - min(all_x), 1.0)
    draw_h = max(max(all_y) - min(all_y), 1.0)
    draw_area = draw_w * draw_h

    cand_boxes = []
    for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
        if not is_cl or len(pts) != 4 or "HATCH" in str(p_lay).upper() or "DASH" in str(p_lay).upper():
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = x1 - x0, y1 - y0
        area = w * h
        if area >= draw_area * 0.35 or w < alen_mm * 3.5 or h < alen_mm * 2.5:
            continue
        # 检查内部是否至少包含正交网格线
        in_l_cnt = sum(
            1 for _, _, lp0, lp1 in lines_out
            if (x0 - 1.5 <= min(lp0[0], lp1[0]) and max(lp0[0], lp1[0]) <= x1 + 1.5
                and y0 - 1.5 <= min(lp0[1], lp1[1]) and max(lp0[1], lp1[1]) <= y1 + 1.5)
        )
        if in_l_cnt >= 4 or is_title_or_frame_layer(p_lay):
            cand_boxes.append([x0, y0, x1, y1, p_lay, p_aci, [p_idx]])

    # 合并重叠或上下紧贴同宽的表格框（例如轴承座主标题栏 y=20..260 与顶部栏 y=260..300，或滚轮支架重合的 TK_CU / TC_ATTRIB 外框）
    merged_boxes = True
    while merged_boxes:
        merged_boxes = False
        new_boxes = []
        used_b = [False] * len(cand_boxes)
        for i in range(len(cand_boxes)):
            if used_b[i]:
                continue
            b1 = cand_boxes[i]
            for j in range(i + 1, len(cand_boxes)):
                if used_b[j]:
                    continue
                b2 = cand_boxes[j]
                ov_x = min(b1[2], b2[2]) - max(b1[0], b2[0])
                ov_y = min(b1[3], b2[3]) - max(b1[1], b2[1])
                same_x_span = abs(b1[0] - b2[0]) <= 1.5 and abs(b1[2] - b2[2]) <= 1.5
                touch_y = abs(b1[3] - b2[1]) <= 1.5 or abs(b2[3] - b1[1]) <= 1.5
                is_overlap = (ov_x > 1.0 and ov_y > 1.0)
                if is_overlap or (same_x_span and touch_y and (is_title_or_frame_layer(b1[4]) or is_title_or_frame_layer(b2[4]))):
                    b1[0] = min(b1[0], b2[0])
                    b1[1] = min(b1[1], b2[1])
                    b1[2] = max(b1[2], b2[2])
                    b1[3] = max(b1[3], b2[3])
                    b1[6].extend(b2[6])
                    used_b[j] = True
                    merged_boxes = True
            new_boxes.append(b1)
        cand_boxes = new_boxes

    used_line_ids = set()
    used_poly_ids = set()
    used_text_ids = set()
    table_blocks = []

    for bx0, by0, bx1, by1, b_lay, b_aci, seed_pids in cand_boxes:
        tol_b = 1.5
        t_lines = []
        h_cnt, v_cnt = 0, 0
        for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
            if l_idx in used_line_ids or "HATCH" in str(l_lay).upper() or "CENTER" in str(l_lay).upper():
                continue
            if (bx0 - tol_b <= min(lp0[0], lp1[0]) and max(lp0[0], lp1[0]) <= bx1 + tol_b
                and by0 - tol_b <= min(lp0[1], lp1[1]) and max(lp0[1], lp1[1]) <= by1 + tol_b):
                t_lines.append(l_idx)
                if abs(lp1[1] - lp0[1]) <= 0.5 and abs(lp1[0] - lp0[0]) >= alen_mm * 1.5:
                    h_cnt += 1
                elif abs(lp1[0] - lp0[0]) <= 0.5 and abs(lp1[1] - lp0[1]) >= alen_mm * 1.5:
                    v_cnt += 1

        if len(t_lines) < 4 or (h_cnt == 0 and v_cnt == 0):
            continue

        t_texts = []
        for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
            if t_idx in used_text_ids:
                continue
            in_box = (bx0 - th * 0.8 <= tx <= bx1 + th * 0.8) and (by0 - th * 2.2 <= ty <= by1 + th * 0.8)
            is_top_title = ("表" in txt) and (bx0 <= tx <= bx1) and (0.0 <= ty - by1 <= max(alen_mm * 6.5, th * 3.0))
            if in_box or is_top_title:
                t_texts.append(t_idx)

        min_req_texts = 2 if is_title_or_frame_layer(b_lay) else 4
        if len(t_texts) < min_req_texts:
            continue

        # 收集落在该表格区域内的全部关联矩形框或分隔折线（同时对完全重合的外框矩形去重）
        t_polys = list(seed_pids)
        for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
            if p_idx not in t_polys and p_idx not in used_poly_ids and "HATCH" not in str(p_lay).upper():
                pxs, pys = [p[0] for p in pts], [p[1] for p in pts]
                if min(pxs) >= bx0 - tol_b and max(pxs) <= bx1 + tol_b and min(pys) >= by0 - tol_b and max(pys) <= by1 + tol_b:
                    t_polys.append(p_idx)

        dedup_rel_polys = []
        seen_poly_boxes = set()
        for pi in t_polys:
            used_poly_ids.add(pi)
            pl_lay, pl_aci, pl_pts, pl_cl = polylines_out[pi]
            if pl_cl and len(pl_pts) == 4:
                pxs, pys = [p[0] for p in pl_pts], [p[1] for p in pl_pts]
                box_k = (round(min(pxs), 1), round(min(pys), 1), round(max(pxs), 1), round(max(pys), 1))
                if box_k in seen_poly_boxes:
                    continue
                seen_poly_boxes.add(box_k)
            dedup_rel_polys.append((pl_lay, pl_aci, [(p[0] - bx0, p[1] - by0) for p in pl_pts], pl_cl))

        for li in t_lines:
            used_line_ids.add(li)
        for ti in t_texts:
            used_text_ids.add(ti)

        b_prefix = "TITLE_TABLE" if is_title_or_frame_layer(b_lay) else "TABLE_BLOCK"
        bname = f"{b_prefix}_{len(table_blocks) + 1}"
        table_blocks.append({
            'block_name': bname,
            'layer': b_lay,
            'ins_pt': (bx0, by0),
            'polylines': dedup_rel_polys,
            'lines': [
                (lines_out[li][0], lines_out[li][1],
                 (lines_out[li][2][0] - bx0, lines_out[li][2][1] - by0),
                 (lines_out[li][3][0] - bx0, lines_out[li][3][1] - by0))
                for li in t_lines
            ],
            'solids': [],
            'circles': [],
            'texts': [
                (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                 (texts_out[ti][3] - bx0, texts_out[ti][4] - by0),
                 texts_out[ti][5], texts_out[ti][6])
                for ti in t_texts
            ],
        })

    rem_lines = [l for idx, l in enumerate(lines_out) if idx not in used_line_ids]
    rem_polys = [p for idx, p in enumerate(polylines_out) if idx not in used_poly_ids]
    rem_texts = [t for idx, t in enumerate(texts_out) if idx not in used_text_ids]
    return rem_lines, rem_polys, rem_texts, table_blocks


def detect_and_assemble_hatch_regions(lines_out, polylines_out, solids_out, alen_mm):
    """
    通用剖面填充 (HATCH) 识别与区域块封装器 (HATCH_REGION_k)：
    1. 自动识别无图层 PDF 中位于默认层 '0' 上的平行等距 45°/135° 剖面线束并归入 HATCH 图层；
    2. 自动保护非闭合的波浪断裂线（留在模型空间作为独立边界折线，不混入填充块）；
    3. 将连通剖面区域内的平行剖面斜线、闭合混凝土砂石骨料多边形与填充 SOLID 聚类封装为 HATCH_REGION_k 块（单击任意剖面线即可整体选中整个剖面填充区）。
    """
    # 1. 自动检测任意非标注/非图框图层（如 '0' 或细实线层 'DRAW-XI'）上的等间距平行 45°/135° 剖面填充线束
    diag_cands = []
    for idx, (lay, aci, p0, p1) in enumerate(lines_out):
        if "HATCH" not in str(lay).upper() and not is_pure_dim_or_text_layer(lay) and not is_title_or_frame_layer(lay):
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            llen = math.hypot(dx, dy)
            if llen >= alen_mm * 0.40:
                ang = math.degrees(math.atan2(dy, dx)) % 180.0
                if (42.5 <= ang <= 47.5) or (132.5 <= ang <= 137.5):
                    rad = math.radians(45.0 if ang < 90.0 else 135.0)
                    perp = -0.5 * (p0[0] + p1[0]) * math.sin(rad) + 0.5 * (p0[1] + p1[1]) * math.cos(rad)
                    diag_cands.append((idx, lay, round(ang / 45.0) * 45, perp))
    if len(diag_cands) >= 5:
        by_grp = defaultdict(list)
        for idx, lay, a_key, perp in diag_cands:
            by_grp[(lay, a_key)].append((perp, idx))
        for (lay, a_key), items in by_grp.items():
            if len(items) >= 5:
                items.sort()
                diffs = [items[k + 1][0] - items[k][0] for k in range(len(items) - 1) if items[k + 1][0] - items[k][0] > 0.3]
                if len(diffs) >= 4:
                    med_d = float(np.median(diffs))
                    inlier_d = [d for d in diffs if abs(d - med_d) <= 0.25 * med_d]
                    if 0.6 <= med_d <= alen_mm * 3.5 and len(inlier_d) >= 4:
                        new_h_lay = "HATCH" if lay == "0" else lay
                        b_xs = [p[0] for _, l_id in items for p in (lines_out[l_id][2], lines_out[l_id][3])]
                        b_ys = [p[1] for _, l_id in items for p in (lines_out[l_id][2], lines_out[l_id][3])]
                        bx0_h, bx1_h = min(b_xs) - 1.0, max(b_xs) + 1.0
                        by0_h, by1_h = min(b_ys) - 1.0, max(b_ys) + 1.0
                        for _, l_id in items:
                            old_l = lines_out[l_id]
                            lines_out[l_id] = (new_h_lay, old_l[1], old_l[2], old_l[3], True)
                        # 同时吸收落在该剖面线束包络框内部、因位于角部而长度较短的 45°/135° 角部短剖面线
                        for k_id, l_cand in enumerate(lines_out):
                            if len(l_cand) == 4 and l_cand[0] == lay:
                                cp0, cp1 = l_cand[2], l_cand[3]
                                clen = math.hypot(cp1[0] - cp0[0], cp1[1] - cp0[1])
                                if 0.05 <= clen < alen_mm * 0.40:
                                    cang = math.degrees(math.atan2(cp1[1] - cp0[1], cp1[0] - cp0[0])) % 180.0
                                    if (35.0 <= cang <= 55.0) or (125.0 <= cang <= 145.0):
                                        if bx0_h <= cp0[0] <= bx1_h and by0_h <= cp0[1] <= by1_h:
                                            lines_out[k_id] = (new_h_lay, l_cand[1], cp0, cp1, True)

    hatch_items = []
    kept_lines = []
    for l_item in lines_out:
        lay, aci, p0, p1 = l_item[:4]
        is_bundle_h = (len(l_item) >= 5 and l_item[4] is True)
        if is_bundle_h or "HATCH" in str(lay).upper() or "剖面" in str(lay).upper():
            bx0, by0 = min(p0[0], p1[0]), min(p0[1], p1[1])
            bx1, by1 = max(p0[0], p1[0]), max(p0[1], p1[1])
            hatch_items.append(('LINE', lay, aci, (p0, p1), (bx0, by0, bx1, by1)))
        else:
            kept_lines.append((lay, aci, p0, p1))

    # 收集所有残余实体填充 SOLID（如混凝土砂浆块、铅堵实体填充块、剖切粗线端块）及其重合外框
    solid_boxes = []
    for s_item in solids_out:
        lay, aci, pts = s_item
        pxs, pys = [p[0] for p in pts], [p[1] for p in pts]
        sb = (min(pxs), min(pys), max(pxs), max(pys))
        solid_boxes.append(sb)
        hatch_items.append(('SOLID', lay, aci, pts, sb))
    kept_solids = []

    kept_polys = []
    for p_item in polylines_out:
        lay, aci, pts, is_cl = p_item
        pxs, pys = [p[0] for p in pts], [p[1] for p in pts]
        pb = (min(pxs), min(pys), max(pxs), max(pys))
        matches_solid_outline = is_cl and any(
            abs(pb[0] - sb[0]) <= 0.5 and abs(pb[1] - sb[1]) <= 0.5 and abs(pb[2] - sb[2]) <= 0.5 and abs(pb[3] - sb[3]) <= 0.5
            for sb in solid_boxes
        )
        if (("HATCH" in str(lay).upper() or "剖面" in str(lay).upper()) and is_cl) or matches_solid_outline:
            hatch_items.append(('POLY', lay, aci, (pts, is_cl), pb))
        else:
            # 开放的波浪断裂线（如滚轮支架或设备埋件截面断裂波浪线）保留在模型空间独立选中
            kept_polys.append(p_item)

    if not hatch_items:
        return kept_lines, kept_polys, kept_solids, []

    # 按空间邻近度将填充图元聚类为独立的 HATCH_REGION_k 剖面填充块
    cluster_gap = max(alen_mm * 5.0, 20.0)
    used_h = [False] * len(hatch_items)
    hatch_blocks = []

    def boxes_close(b1, b2, gap):
        dx = max(0.0, b1[0] - b2[2], b2[0] - b1[2])
        dy = max(0.0, b1[1] - b2[3], b2[1] - b1[3])
        return math.hypot(dx, dy) <= gap

    for i in range(len(hatch_items)):
        if used_h[i]:
            continue
        used_h[i] = True
        comp = [hatch_items[i]]
        changed = True
        while changed:
            changed = False
            for j in range(len(hatch_items)):
                if used_h[j]:
                    continue
                if any(boxes_close(hatch_items[j][4], c_it[4], cluster_gap) for c_it in comp):
                    comp.append(hatch_items[j])
                    used_h[j] = True
                    changed = True

        hx0 = min(it[4][0] for it in comp)
        hy0 = min(it[4][1] for it in comp)
        h_lay = comp[0][1]
        b_lines, b_polys, b_solids = [], [], []
        for kind, lay, aci, geom, _ in comp:
            if kind == 'LINE':
                p0, p1 = geom
                b_lines.append((lay, aci, (p0[0] - hx0, p0[1] - hy0), (p1[0] - hx0, p1[1] - hy0)))
            elif kind == 'POLY':
                pts, is_cl = geom
                b_polys.append((lay, aci, [(p[0] - hx0, p[1] - hy0) for p in pts], is_cl))
            elif kind == 'SOLID':
                b_solids.append((lay, aci, [(p[0] - hx0, p[1] - hy0) for p in geom]))

        bname = f"HATCH_REGION_{len(hatch_blocks) + 1}"
        hatch_blocks.append({
            'block_name': bname,
            'layer': h_lay,
            'ins_pt': (hx0, hy0),
            'polylines': b_polys,
            'lines': b_lines,
            'solids': b_solids,
            'circles': [],
            'texts': [],
        })

    return kept_lines, kept_polys, kept_solids, hatch_blocks


def deduplicate_and_instantiate_block_references(sym_blocks_out):
    """
    通用块定义与块引用 (BLOCK / INSERT) 归一化复用引擎：
    对图纸中几何拓扑与文字内容一致的重复符号块（如多处相同的表面粗糙度 ROUGH_MARK、
    多处相同的标高符号 ELEV_MARK、多处相同的孔深/铅堵/螺纹引出说明 LEADER_MARK、相同排水坡度 SLOPE_MARK 等），
    采用无网格边界跨越效应的自适应几何容差匹配，自动合并为唯一的标准 BLOCK 定义，
    并让各处 INSERT 块引用共享同一块名，实现真正的 CAD 块引用实例化。
    """
    if len(sym_blocks_out) <= 1:
        return sym_blocks_out, len(sym_blocks_out)

    def _max_radius(sb):
        mr = 1.0
        for _, _, pts, _ in sb.get('polylines', []):
            for px, py in pts:
                mr = max(mr, math.hypot(px, py))
        for _, _, p0, p1 in sb.get('lines', []):
            mr = max(mr, math.hypot(p0[0], p0[1]), math.hypot(p1[0], p1[1]))
        return mr

    def _blocks_equivalent(sb1, sb2):
        p1 = sb1['block_name'].rsplit('_', 1)[0]
        p2 = sb2['block_name'].rsplit('_', 1)[0]
        if p1 != p2 or sb1['layer'] != sb2['layer']:
            return False
        if p1 in ("TABLE_BLOCK", "TITLE_TABLE", "HATCH_REGION"):
            return False
        t1 = sorted((str(t[2]).strip(), float(t[4]), float(t[5])) for t in sb1.get('texts', []))
        t2 = sorted((str(t[2]).strip(), float(t[4]), float(t[5])) for t in sb2.get('texts', []))
        if len(t1) != len(t2):
            return False
        for (s1, h1, a1), (s2, h2, a2) in zip(t1, t2):
            if s1 != s2 or abs(h1 - h2) > max(0.5, 0.15 * max(h1, h2)) or abs((a1 - a2 + 180.0) % 360.0 - 180.0) > 3.0:
                return False
        polys1 = sb1.get('polylines', [])
        polys2 = sb2.get('polylines', [])
        lines1 = sb1.get('lines', [])
        lines2 = sb2.get('lines', [])
        circs1 = sb1.get('circles', [])
        circs2 = sb2.get('circles', [])
        if len(polys1) != len(polys2) or len(lines1) != len(lines2) or len(circs1) != len(circs2):
            return False
        tol = max(0.8, 0.045 * max(_max_radius(sb1), _max_radius(sb2)))
        for (_, _, pts1, cl1), (_, _, pts2, cl2) in zip(polys1, polys2):
            if cl1 != cl2 or len(pts1) != len(pts2):
                return False
            direct_ok = all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol for a, b in zip(pts1, pts2))
            rev_ok = all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol for a, b in zip(pts1, reversed(pts2)))
            if not (direct_ok or rev_ok):
                return False
        for (_, _, a0, a1), (_, _, b0, b1) in zip(lines1, lines2):
            d_ok = (math.hypot(a0[0] - b0[0], a0[1] - b0[1]) <= tol and math.hypot(a1[0] - b1[0], a1[1] - b1[1]) <= tol)
            r_ok = (math.hypot(a0[0] - b1[0], a0[1] - b1[1]) <= tol and math.hypot(a1[0] - b0[0], a1[1] - b0[1]) <= tol)
            if not (d_ok or r_ok):
                return False
        return True

    canonical_blocks = []
    prefix_counters = defaultdict(int)
    out_blocks = []

    for sb in sym_blocks_out:
        matched_cname = None
        for c_sb, cname in canonical_blocks:
            if _blocks_equivalent(sb, c_sb):
                matched_cname = cname
                break
        if matched_cname is None:
            prefix = sb['block_name'].rsplit('_', 1)[0]
            prefix_counters[prefix] += 1
            cname = f"{prefix}_{prefix_counters[prefix]}"
            canonical_blocks.append((sb, cname))
            sb_copy = dict(sb)
            sb_copy['block_name'] = cname
            sb_copy['is_canonical_def'] = True
            out_blocks.append(sb_copy)
        else:
            sb_ref = dict(sb)
            sb_ref['block_name'] = matched_cname
            sb_ref['is_canonical_def'] = False
            out_blocks.append(sb_ref)

    return out_blocks, len(canonical_blocks)


def _merge_callout_collinear_texts(rel_texts):
    """合并同一引出标注块内被 PDF 拆开的共基线相邻碎文本（如 '200X' + '200X150' -> '200X200X150'）。"""
    if len(rel_texts) <= 1:
        return rel_texts
    items = sorted(rel_texts, key=lambda it: (round(it[3][1], 1), it[3][0]))
    merged = []
    for it in items:
        if merged:
            prev = merged[-1]
            if prev[0] == it[0] and abs(prev[5] - it[5]) < 1.0 and abs(prev[3][1] - it[3][1]) <= prev[4] * 0.25:
                dx = it[3][0] - prev[3][0]
                if 0.0 < dx <= (len(prev[2]) + 1.5) * prev[4] * 0.85 and (prev[2].endswith(('X', 'x', '-', '~')) or it[2].startswith(('X', 'x', '-', '~'))):
                    merged[-1] = (prev[0], prev[1], prev[2] + it[2], prev[3], prev[4], prev[5])
                    continue
        merged.append(it)
    return merged


def assemble_annotation_blocks(
    lines_out, polylines_out, solids_out, texts_out, single_arrows_pt, used_solid_indices, scale_from_pt, typical_arrow_len_pt,
    circles_out=None, dimensions_out=None
):
    texts_out = merge_same_cell_justified_texts(texts_out, lines_out, polylines_out)
    blocks_out = []
    used_poly_ids = set()
    used_line_ids = set()
    used_text_ids = set()
    used_circle_ids = set()
    alen_mm = typical_arrow_len_pt * scale_from_pt

    # 0A. 识别“圆点起止符 (Dot Terminator)”与“箭头+圆点混合窄链式尺寸标注”（如轴承座中的 17 与 12 链式尺寸）及建筑 45° 斜线尺寸
    if circles_out is not None and dimensions_out is not None:
        dot_circles = [
            (c_idx, c_lay, c_aci, cx, cy, cr)
            for c_idx, (c_lay, c_aci, cx, cy, cr) in enumerate(circles_out)
            if is_pure_dim_or_text_layer(c_lay) and (0.08 * alen_mm <= cr <= 0.45 * alen_mm)
        ]
        for c_idx, c_lay, c_aci, dcx, dcy, dcr in dot_circles:
            if c_idx in used_circle_ids:
                continue
            # 查找与该圆点共水平线或共垂直线的未配对单箭头（构成 箭头<->圆点 链式尺寸对）
            matching_arrows = []
            for a in single_arrows_pt:
                if a['solid_id'] in used_solid_indices:
                    continue
                atx, aty = a['tip'][0] * scale_from_pt, a['tip'][1] * scale_from_pt
                if abs(aty - dcy) <= alen_mm * 0.35 and alen_mm * 0.5 <= abs(atx - dcx) <= alen_mm * 6.0 and abs(a['dir'][0]) > 0.9:
                    matching_arrows.append((a, (atx, aty), True))
                elif abs(atx - dcx) <= alen_mm * 0.35 and alen_mm * 0.5 <= abs(aty - dcy) <= alen_mm * 6.0 and abs(a['dir'][1]) > 0.9:
                    matching_arrows.append((a, (atx, aty), False))
            if not matching_arrows:
                continue
            used_circle_ids.add(c_idx)
            dot_tri = [(dcx - dcr, dcy), (dcx, dcy), (dcx + dcr, dcy)]
            for a, (atx, aty), is_h in matching_arrows:
                p1 = (min(atx, dcx), dcy) if is_h else (dcx, min(aty, dcy))
                p2 = (max(atx, dcx), dcy) if is_h else (dcx, max(aty, dcy))
                mx_d, my_d = 0.5 * (p1[0] + p2[0]), 0.5 * (p1[1] + p2[1])
                span_d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                # 查找位于该链式尺寸段中点附近的数值文本（如 '17'、'12'）
                best_t_idx = None
                best_t_dist = float('inf')
                for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
                    if t_idx in used_text_ids or not is_pure_dim_or_text_layer(t_lay):
                        continue
                    num_v = parse_dimension_numeric_value(txt)
                    if num_v is None:
                        continue
                    tcx = tx + len(txt) * th * 0.35 * math.cos(math.radians(tang))
                    tcy = ty + len(txt) * th * 0.35 * math.sin(math.radians(tang))
                    d_m = math.hypot(tcx - mx_d, tcy - my_d)
                    if d_m <= max(span_d * 1.25, alen_mm * 2.6) and abs(num_v - span_d) <= max(span_d * 0.35, 3.0):
                        if d_m < best_t_dist:
                            best_t_dist = d_m
                            best_t_idx = t_idx
                if best_t_idx is None:
                    continue
                used_solid_indices.add(a['solid_id'])
                used_text_ids.add(best_t_idx)
                t_lay, t_aci, txt, tx, ty, th, tang = texts_out[best_t_idx]
                apts_mm = [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in a['pts']]
                # 吸收共用的尺寸线与圆点处的尺寸界线
                d_segs = [(p1, p2)]
                e_segs = []
                for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
                    if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
                        continue
                    if is_h and abs(lp0[1] - dcy) <= alen_mm * 0.25 and abs(lp1[1] - dcy) <= alen_mm * 0.25:
                        if min(lp0[0], lp1[0]) <= p2[0] + alen_mm and max(lp0[0], lp1[0]) >= p1[0] - alen_mm:
                            d_segs.append((lp0, lp1))
                            used_line_ids.add(l_idx)
                    elif is_h and abs(lp0[0] - lp1[0]) <= 0.25 and (abs(lp0[0] - dcx) <= alen_mm * 0.25 or abs(lp0[0] - atx) <= alen_mm * 0.25):
                        if min(lp0[1], lp1[1]) - alen_mm <= dcy <= max(lp0[1], lp1[1]) + alen_mm:
                            e_segs.append((lp0, lp1))
                            used_line_ids.add(l_idx)
                # 吸收与单箭头相连的短折线引线
                for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
                    if p_idx not in used_poly_ids and not is_closed and is_pure_dim_or_text_layer(p_lay):
                        if min(math.hypot(pts[0][0] - atx, pts[0][1] - aty), math.hypot(pts[-1][0] - atx, pts[-1][1] - aty)) <= alen_mm * 0.65:
                            for k_s in range(len(pts) - 1):
                                d_segs.append((pts[k_s], pts[k_s + 1]))
                            used_poly_ids.add(p_idx)
                bname_d = f"*D{len(dimensions_out) + 1}"
                dimensions_out.append({
                    'kind': 'LINEAR',
                    'block_name': bname_d,
                    'layer': c_lay,
                    'aci': c_aci,
                    't1': p1,
                    't2': p2,
                    'defpoint1': p1,
                    'defpoint2': p2,
                    'text_mid': (tx, ty),
                    'text_ins': (tx, ty),
                    'text_height': th,
                    'arrow_len': alen_mm,
                    'text': txt,
                    'dim_angle_deg': 0.0 if is_h else 90.0,
                    'angle_deg': tang,
                    'arrow1_pts': apts_mm,
                    'arrow2_pts': dot_tri,
                    'dim_lines': d_segs,
                    'ext_lines': e_segs,
                    'arcs': [],
                    'extra_texts': [],
                })

        # 识别建筑/土建 45° 短斜线起止符尺寸标注 (_ArchTick / _Oblique Terminator Dimensions)
        tick_cands = []
        for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
            if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
                continue
            dx_t, dy_t = lp1[0] - lp0[0], lp1[1] - lp0[1]
            t_len = math.hypot(dx_t, dy_t)
            if 0.35 * alen_mm <= t_len <= 2.2 * alen_mm:
                ang_t = math.degrees(math.atan2(dy_t, dx_t)) % 180.0
                if 25.0 <= ang_t <= 65.0 or 115.0 <= ang_t <= 155.0:
                    tick_cands.append((l_idx, l_lay, l_aci, lp0, lp1, (0.5 * (lp0[0] + lp1[0]), 0.5 * (lp0[1] + lp1[1])), ang_t))

        for i_tk in range(len(tick_cands)):
            l1_id, tk_lay, tk_aci, tk1_p0, tk1_p1, m1, ang1 = tick_cands[i_tk]
            if l1_id in used_line_ids:
                continue
            for j_tk in range(i_tk + 1, len(tick_cands)):
                l2_id, tk2_lay, _, tk2_p0, tk2_p1, m2, ang2 = tick_cands[j_tk]
                if l2_id in used_line_ids or tk2_lay != tk_lay or abs(ang1 - ang2) > 8.0:
                    continue
                is_h_tk = abs(m2[0] - m1[0]) >= abs(m2[1] - m1[1])
                perp_err = abs(m2[1] - m1[1]) if is_h_tk else abs(m2[0] - m1[0])
                span_tk = abs(m2[0] - m1[0]) if is_h_tk else abs(m2[1] - m1[1])
                if perp_err > alen_mm * 0.35 or span_tk < alen_mm * 0.8:
                    continue
                # 检查 m1 与 m2 之间是否存在共线尺寸线及匹配的尺寸数字
                d_line_id = None
                for ld_idx, (ld_lay, _, dp0, dp1) in enumerate(lines_out):
                    if ld_idx not in used_line_ids and ld_lay == tk_lay:
                        if is_h_tk and abs(dp0[1] - m1[1]) <= alen_mm * 0.3 and abs(dp1[1] - m1[1]) <= alen_mm * 0.3:
                            if min(dp0[0], dp1[0]) <= min(m1[0], m2[0]) + alen_mm * 0.5 and max(dp0[0], dp1[0]) >= max(m1[0], m2[0]) - alen_mm * 0.5:
                                d_line_id = ld_idx
                                break
                        elif not is_h_tk and abs(dp0[0] - m1[0]) <= alen_mm * 0.3 and abs(dp1[0] - m1[0]) <= alen_mm * 0.3:
                            if min(dp0[1], dp1[1]) <= min(m1[1], m2[1]) + alen_mm * 0.5 and max(dp0[1], dp1[1]) >= max(m1[1], m2[1]) - alen_mm * 0.5:
                                d_line_id = ld_idx
                                break
                if d_line_id is None:
                    continue
                mx_tk, my_tk = 0.5 * (m1[0] + m2[0]), 0.5 * (m1[1] + m2[1])
                best_tk_t = None
                for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
                    if t_idx in used_text_ids or not is_pure_dim_or_text_layer(t_lay):
                        continue
                    num_v = parse_dimension_numeric_value(txt)
                    if num_v is not None and math.hypot(tx - mx_tk, ty - my_tk) <= max(span_tk * 0.65, alen_mm * 2.0):
                        best_tk_t = t_idx
                        break
                if best_tk_t is not None:
                    used_line_ids.update([l1_id, l2_id, d_line_id])
                    used_text_ids.add(best_tk_t)
                    _, _, txt_tk, tx_tk, ty_tk, th_tk, tang_tk = texts_out[best_tk_t]
                    bname_d = f"*D{len(dimensions_out) + 1}"
                    dimensions_out.append({
                        'kind': 'LINEAR',
                        'block_name': bname_d,
                        'layer': tk_lay,
                        'aci': tk_aci,
                        't1': m1,
                        't2': m2,
                        'defpoint1': m1,
                        'defpoint2': m2,
                        'text_mid': (tx_tk, ty_tk),
                        'text_ins': (tx_tk, ty_tk),
                        'text_height': th_tk,
                        'arrow_len': alen_mm,
                        'text': txt_tk,
                        'dim_angle_deg': 0.0 if is_h_tk else 90.0,
                        'angle_deg': tang_tk,
                        'arrow1_pts': [tk1_p0, m1, tk1_p1],
                        'arrow2_pts': [tk2_p0, m2, tk2_p1],
                        'dim_lines': [(m1, m2), (tk1_p0, tk1_p1), (tk2_p0, tk2_p1)],
                        'ext_lines': [],
                        'arcs': [],
                        'extra_texts': [],
                    })
                    break

    # 0B. 识别形位公差框格标注块 (FCF_MARK — Feature Control Frame，如 [↑|0.012]、[⊥|0.04|A]、[⊥|0.04|B]、[∥|0.04|C])
    for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
        if p_idx in used_poly_ids or not is_pure_dim_or_text_layer(p_lay):
            continue
        if not (is_closed and 4 <= len(pts) <= 6):
            continue
        pxs = [p[0] for p in pts]
        pys = [p[1] for p in pts]
        fx0, fx1 = min(pxs), max(pxs)
        fy0, fy1 = min(pys), max(pys)
        fw, fh = fx1 - fx0, fy1 - fy0
        if not (alen_mm * 1.2 <= fh <= alen_mm * 3.5 and fw >= fh * 1.8 and fw <= alen_mm * 12.0):
            continue
        # 检查框格内部是否包含形位公差文本（如 ⊥、∥、↑、0.04A、0.012 等）
        in_texts = []
        for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
            if t_idx in used_text_ids or is_title_or_frame_layer(t_lay):
                continue
            if (fx0 - fh * 0.4 <= tx <= fx1 + fh * 0.4) and (fy0 - fh * 0.4 <= ty <= fy1 + fh * 0.4):
                in_texts.append(t_idx)
        if not in_texts:
            continue
        # 查找框格内部的竖直分格线
        div_lines = []
        for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
            if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
                continue
            if abs(lp0[0] - lp1[0]) <= 0.5 and abs( abs(lp1[1] - lp0[1]) - fh ) <= fh * 0.25:
                lx = 0.5 * (lp0[0] + lp1[0])
                ly0, ly1 = min(lp0[1], lp1[1]), max(lp0[1], lp1[1])
                if fx0 + 1.0 < lx < fx1 - 1.0 and abs(ly0 - fy0) <= 2.0 and abs(ly1 - fy1) <= 2.0:
                    div_lines.append(l_idx)
                    used_line_ids.add(l_idx)
        # 查找与形位公差框格相连的引出折线/直线及可能关联的箭头
        fcf_polys = [p_idx]
        used_poly_ids.add(p_idx)
        for t_idx in in_texts:
            used_text_ids.add(t_idx)
        fcf_lines = list(div_lines)
        fcf_solids = []

        def touches_fcf_box(pt, tol_d):
            dx_b = max(0.0, fx0 - pt[0], pt[0] - fx1)
            dy_b = max(0.0, fy0 - pt[1], pt[1] - fy1)
            return math.hypot(dx_b, dy_b) <= tol_d

        leader_end_pts = []
        for p2_idx, (p2_lay, p2_aci, pts2, cl2) in enumerate(polylines_out):
            if p2_idx not in used_poly_ids and not cl2 and is_pure_dim_or_text_layer(p2_lay):
                if touches_fcf_box(pts2[0], alen_mm * 0.5) or touches_fcf_box(pts2[-1], alen_mm * 0.5):
                    fcf_polys.append(p2_idx)
                    used_poly_ids.add(p2_idx)
                    leader_end_pts.extend([pts2[0], pts2[-1]])

        for l2_idx, (l2_lay, l2_aci, lp0, lp1) in enumerate(lines_out):
            if l2_idx not in used_line_ids and is_pure_dim_or_text_layer(l2_lay):
                if touches_fcf_box(lp0, alen_mm * 0.4) or touches_fcf_box(lp1, alen_mm * 0.4):
                    fcf_lines.append(l2_idx)
                    used_line_ids.add(l2_idx)
                    leader_end_pts.extend([lp0, lp1])

        # 支持多跳引线串联（如公差框格 -> 折线 -> 水平延伸线段 -> 箭头）
        chained_more = True
        while chained_more and leader_end_pts:
            chained_more = False
            for l2_idx, (l2_lay, l2_aci, lp0, lp1) in enumerate(lines_out):
                if l2_idx not in used_line_ids and is_pure_dim_or_text_layer(l2_lay):
                    if any(min(math.hypot(lp0[0] - ep[0], lp0[1] - ep[1]), math.hypot(lp1[0] - ep[0], lp1[1] - ep[1])) <= alen_mm * 0.45 for ep in leader_end_pts):
                        fcf_lines.append(l2_idx)
                        used_line_ids.add(l2_idx)
                        leader_end_pts.extend([lp0, lp1])
                        chained_more = True

        # 若引线另一端连有单箭头（如 LEADER_MARK_22 / 27 / 29），将该箭头及箭头处的延伸段一并收入形位公差块
        for a in single_arrows_pt:
            if a['solid_id'] in used_solid_indices:
                continue
            atip = (a['tip'][0] * scale_from_pt, a['tip'][1] * scale_from_pt)
            abmid = (a['base_mid'][0] * scale_from_pt, a['base_mid'][1] * scale_from_pt)
            if any(min(math.hypot(ep[0] - atip[0], ep[1] - atip[1]), math.hypot(ep[0] - abmid[0], ep[1] - abmid[1])) <= alen_mm * 0.75 for ep in leader_end_pts):
                used_solid_indices.add(a['solid_id'])
                apts_mm = [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in a['pts']]
                fcf_solids.append((a['layer'], a['aci'], apts_mm))
                for l3_idx, (l3_lay, l3_aci, q0, q1) in enumerate(lines_out):
                    if l3_idx not in used_line_ids and is_pure_dim_or_text_layer(l3_lay):
                        if min(math.hypot(q0[0] - atip[0], q0[1] - atip[1]), math.hypot(q1[0] - atip[0], q1[1] - atip[1])) <= alen_mm * 0.65:
                            fcf_lines.append(l3_idx)
                            used_line_ids.add(l3_idx)

        base_x, base_y = fx0, fy0
        bname = f"FCF_MARK_{len(blocks_out) + 1}"
        blocks_out.append({
            'block_name': bname,
            'layer': p_lay,
            'ins_pt': (base_x, base_y),
            'polylines': [
                (polylines_out[pi][0], polylines_out[pi][1],
                 [(p[0] - base_x, p[1] - base_y) for p in polylines_out[pi][2]],
                 polylines_out[pi][3])
                for pi in fcf_polys
            ],
            'lines': [
                (lines_out[li][0], lines_out[li][1],
                 (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
                 (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
                for li in fcf_lines
            ],
            'solids': [
                (s_lay, s_aci, [(p[0] - base_x, p[1] - base_y) for p in s_pts])
                for s_lay, s_aci, s_pts in fcf_solids
            ],
            'circles': [],
            'texts': [
                (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                 (texts_out[ti][3] - base_x, texts_out[ti][4] - base_y),
                 texts_out[ti][5], texts_out[ti][6])
                for ti in in_texts
            ],
        })

    # 0C. 识别国标基准符号块 (DATUM_MARK — 粗短划基准底座 + 正交连线 + 基准圆圈 + 基准大写字母 A/B/C/D)
    for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
        if p_idx in used_poly_ids or not is_pure_dim_or_text_layer(p_lay):
            continue
        if not (is_closed and 4 <= len(pts) <= 6):
            continue
        pxs = [p[0] for p in pts]
        pys = [p[1] for p in pts]
        bx0, bx1 = min(pxs), max(pxs)
        by0, by1 = min(pys), max(pys)
        bw, bh = bx1 - bx0, by1 - by0
        long_s, short_s = max(bw, bh), min(bw, bh)
        if not (alen_mm * 1.4 <= long_s <= alen_mm * 4.2 and 0.12 * alen_mm <= short_s <= 0.55 * alen_mm):
            continue
        bcx, bcy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
        # 查找从基准底座中心引出的正交连线
        stem_l_idx = None
        far_stem_pt = None
        stem_dir = (0.0, 0.0)
        for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
            if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
                continue
            d0 = math.hypot(lp0[0] - bcx, lp0[1] - bcy)
            d1 = math.hypot(lp1[0] - bcx, lp1[1] - bcy)
            if min(d0, d1) <= short_s * 1.5:
                near_p = lp0 if d0 <= d1 else lp1
                far_p = lp1 if d0 <= d1 else lp0
                slen = math.hypot(far_p[0] - near_p[0], far_p[1] - near_p[1])
                if alen_mm * 1.0 <= slen <= alen_mm * 5.0:
                    stem_l_idx = l_idx
                    far_stem_pt = far_p
                    stem_dir = ((far_p[0] - near_p[0]) / slen, (far_p[1] - near_p[1]) / slen)
                    break
        if stem_l_idx is None:
            continue
        # 查找连线远端外侧的基准圆圈（若原图圆圈笔画被拆分丢失，则根据相切几何自动补齐标准半径基准圆圈）
        expected_r = long_s * 0.46
        exp_cx = far_stem_pt[0] + stem_dir[0] * expected_r
        exp_cy = far_stem_pt[1] + stem_dir[1] * expected_r
        matched_c_idx = None
        if circles_out is not None:
            for c_idx, (c_lay, c_aci, cx, cy, cr) in enumerate(circles_out):
                if c_idx not in used_circle_ids and is_pure_dim_or_text_layer(c_lay):
                    if math.hypot(cx - exp_cx, cy - exp_cy) <= alen_mm * 0.8 and abs(cr - expected_r) <= alen_mm * 0.5:
                        matched_c_idx = c_idx
                        exp_cx, exp_cy, expected_r = cx, cy, cr
                        break
        # 查找圆圈内部的单个大写基准字母（A..Z）
        matched_t_idx = None
        for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
            if t_idx in used_text_ids or is_title_or_frame_layer(t_lay):
                continue
            if len(txt.strip()) == 1 and txt.strip().isalpha() and txt.strip().isupper():
                if math.hypot(tx - exp_cx, ty - exp_cy) <= expected_r * 1.4:
                    matched_t_idx = t_idx
                    break
        if matched_t_idx is None:
            continue
        used_poly_ids.add(p_idx)
        used_line_ids.add(stem_l_idx)
        used_text_ids.add(matched_t_idx)
        if matched_c_idx is not None:
            used_circle_ids.add(matched_c_idx)
        base_x, base_y = bcx, bcy
        bname = f"DATUM_MARK_{len(blocks_out) + 1}"
        blocks_out.append({
            'block_name': bname,
            'layer': p_lay,
            'ins_pt': (base_x, base_y),
            'polylines': [(p_lay, p_aci, [(p[0] - base_x, p[1] - base_y) for p in pts], True)],
            'lines': [
                (lines_out[stem_l_idx][0], lines_out[stem_l_idx][1],
                 (lines_out[stem_l_idx][2][0] - base_x, lines_out[stem_l_idx][2][1] - base_y),
                 (lines_out[stem_l_idx][3][0] - base_x, lines_out[stem_l_idx][3][1] - base_y))
            ],
            'solids': [],
            'circles': [(p_lay, p_aci, exp_cx - base_x, exp_cy - base_y, expected_r)],
            'texts': [
                (texts_out[matched_t_idx][0], texts_out[matched_t_idx][1], texts_out[matched_t_idx][2],
                 (texts_out[matched_t_idx][3] - base_x, texts_out[matched_t_idx][4] - base_y),
                 texts_out[matched_t_idx][5], texts_out[matched_t_idx][6])
            ],
        })

    # 0D. 识别建筑定位轴线圆圈轴号块 (AXIS_BUBBLE) 与机械 BOM 序号引出球标块 (BALLOON_MARK)
    if circles_out is not None:
        for c_idx, (c_lay, c_aci, cx, cy, cr) in enumerate(circles_out):
            if c_idx in used_circle_ids or is_title_or_frame_layer(c_lay):
                continue
            if not (alen_mm * 0.8 <= cr <= alen_mm * 4.5):
                continue
            in_c_texts = [
                t_idx for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out)
                if t_idx not in used_text_ids and not is_title_or_frame_layer(t_lay)
                and 1 <= len(txt.strip()) <= 4 and re.match(r'^[A-Za-z0-9\-]+$', txt.strip())
                and math.hypot(tx + len(txt.strip()) * th * 0.25 - cx, ty + th * 0.35 - cy) <= cr * 1.15
            ]
            if len(in_c_texts) != 1:
                continue
            # 检查圆周外侧是否连接单箭头引线 (BALLOON_MARK) 或轴线引线 (AXIS_BUBBLE)
            balloon_polys = []
            balloon_lines = []
            balloon_solids = []
            for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
                if p_idx not in used_poly_ids and not is_cl and is_pure_dim_or_text_layer(p_lay):
                    d0 = abs(math.hypot(pts[0][0] - cx, pts[0][1] - cy) - cr)
                    d1 = abs(math.hypot(pts[-1][0] - cx, pts[-1][1] - cy) - cr)
                    if min(d0, d1) <= alen_mm * 0.45:
                        balloon_polys.append(p_idx)
                        used_poly_ids.add(p_idx)
                        far_ep = pts[-1] if d0 <= d1 else pts[0]
                        for a in single_arrows_pt:
                            if a['solid_id'] not in used_solid_indices:
                                atx, aty = a['tip'][0] * scale_from_pt, a['tip'][1] * scale_from_pt
                                bmx, bmy = a['base_mid'][0] * scale_from_pt, a['base_mid'][1] * scale_from_pt
                                if min(math.hypot(far_ep[0] - atx, far_ep[1] - aty), math.hypot(far_ep[0] - bmx, far_ep[1] - bmy)) <= alen_mm * 0.65:
                                    used_solid_indices.add(a['solid_id'])
                                    balloon_solids.append((a['layer'], a['aci'], [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in a['pts']]))
                                    break
            if balloon_polys or is_pure_dim_or_text_layer(c_lay):
                t_i = in_c_texts[0]
                used_circle_ids.add(c_idx)
                used_text_ids.add(t_i)
                b_prefix = "BALLOON_MARK" if balloon_polys else "AXIS_BUBBLE"
                bname = f"{b_prefix}_{len(blocks_out) + 1}"
                blocks_out.append({
                    'block_name': bname,
                    'layer': c_lay,
                    'ins_pt': (cx, cy),
                    'polylines': [
                        (polylines_out[pi][0], polylines_out[pi][1],
                         [(p[0] - cx, p[1] - cy) for p in polylines_out[pi][2]],
                         polylines_out[pi][3])
                        for pi in balloon_polys
                    ],
                    'lines': [],
                    'solids': [
                        (sl, sa, [(p[0] - cx, p[1] - cy) for p in spts])
                        for sl, sa, spts in balloon_solids
                    ],
                    'circles': [(c_lay, c_aci, 0.0, 0.0, cr)],
                    'texts': [
                        (texts_out[t_i][0], texts_out[t_i][1], texts_out[t_i][2],
                         (texts_out[t_i][3] - cx, texts_out[t_i][4] - cy),
                         texts_out[t_i][5], texts_out[t_i][6])
                    ],
                })

    # 1. 标高符号块 (ELEV_MARK)
    for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
        if t_idx in used_text_ids:
            continue
        if not (txt.startswith('+') or txt.startswith('±') or (txt.startswith('-') and txt[1:].replace('.', '').isdigit())):
            continue
        best_p_idx = None
        best_score = (999, float('inf'))
        search_r = th * 4.8
        for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
            if p_idx in used_poly_ids or not (3 <= len(pts) <= 6) or not is_pure_dim_or_text_layer(p_lay):
                continue
            pxs = [p[0] for p in pts]
            pys = [p[1] for p in pts]
            pw, ph = max(pxs) - min(pxs), max(pys) - min(pys)
            if max(pw, ph) > th * 4.2 or max(pw, ph) < th * 0.4:
                continue
            d = math.hypot(0.5 * (min(pxs) + max(pxs)) - tx, 0.5 * (min(pys) + max(pys)) - ty)
            if d < search_r:
                layer_penalty = 0 if p_lay == t_lay else 1
                score = (layer_penalty, d)
                if score < best_score:
                    best_score = score
                    best_p_idx = p_idx

        if best_p_idx is not None:
            used_text_ids.add(t_idx)
            used_poly_ids.add(best_p_idx)
            p_lay, p_aci, pts, is_closed = polylines_out[best_p_idx]
            base_x, base_y = pts[0]
            bname = f"ELEV_MARK_{len(blocks_out) + 1}"
            blocks_out.append({
                'block_name': bname,
                'layer': t_lay,
                'ins_pt': (base_x, base_y),
                'polylines': [(p_lay, p_aci, [(p[0] - base_x, p[1] - base_y) for p in pts], is_closed)],
                'lines': [],
                'solids': [],
                'texts': [(t_lay, t_aci, txt, (tx - base_x, ty - base_y), th, tang)],
            })

    # 2. 表面粗糙度符号块 (ROUGH_MARK)
    for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
        if t_idx in used_text_ids:
            continue
        if txt not in ("0.8", "1.6", "3.2", "6.3", "12.5", "25", "50") or "DIM" not in t_lay.upper():
            continue
        near_polys = []
        near_lines = []
        for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
            if p_idx in used_poly_ids or "DIM" not in p_lay.upper() or not (3 <= len(pts) <= 5):
                continue
            pxs = [p[0] for p in pts]
            pys = [p[1] for p in pts]
            if max(max(pxs) - min(pxs), max(pys) - min(pys)) <= th * 3.5:
                if math.hypot(0.5 * (min(pxs) + max(pxs)) - tx, 0.5 * (min(pys) + max(pys)) - ty) <= th * 2.8:
                    near_polys.append(p_idx)
        if near_polys:
            p_idx = near_polys[0]
            used_poly_ids.add(p_idx)
            used_text_ids.add(t_idx)
            p_lay, p_aci, pts, is_closed = polylines_out[p_idx]
            pcx = 0.5 * (min(p[0] for p in pts) + max(p[0] for p in pts))
            pcy = 0.5 * (min(p[1] for p in pts) + max(p[1] for p in pts))
            for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
                if l_idx not in used_line_ids and "DIM" in l_lay.upper():
                    if math.hypot(lp0[0] - lp1[0], lp0[1] - lp1[1]) <= th * 2.5:
                        if math.hypot(0.5 * (lp0[0] + lp1[0]) - pcx, 0.5 * (lp0[1] + lp1[1]) - pcy) <= th * 2.2:
                            near_lines.append(l_idx)
                            used_line_ids.add(l_idx)
            base_x, base_y = pts[1] if len(pts) >= 2 else pts[0]
            r_texts = [(t_lay, t_aci, txt, (tx - base_x, ty - base_y), th, tang)]
            for q_idx, (q_lay, q_aci, q_txt, qx, qy, qh, qang) in enumerate(texts_out):
                if q_idx not in used_text_ids and q_txt.strip() == "其余":
                    if 0.0 < (base_x - qx) <= max(th, qh) * 6.5 and abs(qy - base_y) <= max(th, qh) * 2.5:
                        used_text_ids.add(q_idx)
                        r_texts.insert(0, (q_lay, q_aci, q_txt, (qx - base_x, qy - base_y), qh, qang))
                        break
            bname = f"ROUGH_MARK_{len(blocks_out) + 1}"
            blocks_out.append({
                'block_name': bname,
                'layer': t_lay,
                'ins_pt': (base_x, base_y),
                'polylines': [(p_lay, p_aci, [(p[0] - base_x, p[1] - base_y) for p in pts], is_closed)],
                'lines': [
                    (lines_out[li][0], lines_out[li][1],
                     (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
                     (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
                    for li in near_lines
                ],
                'solids': [],
                'texts': r_texts,
            })

    # 3. 单箭头引出标注块 (LEADER_MARK) — 采用 1 对 1 最近箭头引线绑定 + 全局最近台面文本分配，杜绝相邻引线互抢折线或互抢文本
    active_arrows = [a for a in single_arrows_pt if a['solid_id'] not in used_solid_indices]
    arrow_mm_info = [
        (
            a,
            (a['tip'][0] * scale_from_pt, a['tip'][1] * scale_from_pt),
            (a['base_mid'][0] * scale_from_pt, a['base_mid'][1] * scale_from_pt),
            [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in a['pts']],
        )
        for a in active_arrows
    ]

    def dist_pt_to_arrow_mm(pt, tip_m, bmid_m):
        return min(math.hypot(pt[0] - tip_m[0], pt[1] - tip_m[1]), math.hypot(pt[0] - bmid_m[0], pt[1] - bmid_m[1]))

    leader_candidates = []
    for idx_a, (a, tip_mm, bmid_mm, apts_mm) in enumerate(arrow_mm_info):
        a_lay, a_aci = a['layer'], a['aci']
        conn_polys = []
        conn_lines = []
        far_pts = []

        # 仅绑定端点距离当前箭头最近（且 <= 0.65 * alen_mm）的标注折线
        best_p = None
        best_p_dist = alen_mm * 0.65
        for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
            if p_idx in used_poly_ids or is_closed or not is_pure_dim_or_text_layer(p_lay):
                continue
            d0 = dist_pt_to_arrow_mm(pts[0], tip_mm, bmid_mm)
            d1 = dist_pt_to_arrow_mm(pts[-1], tip_mm, bmid_mm)
            d_min = min(d0, d1)
            if d_min <= best_p_dist:
                near_pt = pts[0] if d0 <= d1 else pts[-1]
                if all(dist_pt_to_arrow_mm(near_pt, ot, ob) >= d_min - 1e-3 for k_o, (_, ot, ob, _) in enumerate(arrow_mm_info) if k_o != idx_a):
                    best_p_dist = d_min
                    best_p = (p_idx, pts[1:] if d0 <= d1 else pts[:-1])
        if best_p is not None:
            conn_polys.append(best_p[0])
            used_poly_ids.add(best_p[0])
            far_pts.extend(best_p[1])
            # 自动吸收与该引线折线远端相接的水平台面 LINE（解决引线斜杆为 3 点折线、水平台面为 2 点直线时的跨类型分离问题）
            for fpt in list(far_pts):
                for l2_idx, (l2_lay, l2_aci, q0, q1) in enumerate(lines_out):
                    if l2_idx not in used_line_ids and is_pure_dim_or_text_layer(l2_lay) and abs(q0[1] - q1[1]) <= alen_mm * 0.25:
                        if min(math.hypot(q0[0] - fpt[0], q0[1] - fpt[1]), math.hypot(q1[0] - fpt[0], q1[1] - fpt[1])) <= alen_mm * 0.35:
                            conn_lines.append(l2_idx)
                            used_line_ids.add(l2_idx)
                            far_pts.extend([q0, q1])

        if not conn_polys:
            best_l = None
            best_l_dist = alen_mm * 0.65
            for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
                if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
                    continue
                d0 = dist_pt_to_arrow_mm(lp0, tip_mm, bmid_mm)
                d1 = dist_pt_to_arrow_mm(lp1, tip_mm, bmid_mm)
                d_min = min(d0, d1)
                if d_min <= best_l_dist:
                    near_pt = lp0 if d0 <= d1 else lp1
                    if all(dist_pt_to_arrow_mm(near_pt, ot, ob) >= d_min - 1e-3 for k_o, (_, ot, ob, _) in enumerate(arrow_mm_info) if k_o != idx_a):
                        best_l_dist = d_min
                        best_l = (l_idx, lp1 if d0 <= d1 else lp0)
            if best_l is not None:
                conn_lines.append(best_l[0])
                used_line_ids.add(best_l[0])
                far_pts.append(best_l[1])
                fpt = best_l[1]
                # 检查与该引线段远端相接的后续折线（如跨轮廓线断开的引线折线）
                for p2_idx, (p2_lay, p2_aci, pts2, is_cl2) in enumerate(polylines_out):
                    if p2_idx not in used_poly_ids and not is_cl2 and p2_lay == a_lay:
                        d_p2 = min(math.hypot(pts2[0][0] - fpt[0], pts2[0][1] - fpt[1]), math.hypot(pts2[-1][0] - fpt[0], pts2[-1][1] - fpt[1]))
                        if d_p2 <= alen_mm * 0.65:
                            conn_polys.append(p2_idx)
                            used_poly_ids.add(p2_idx)
                            far_pts.extend(pts2)
                            break
                # 检查与远端相接的水平台面线段
                for fpt_c in list(far_pts):
                    for l2_idx, (l2_lay, l2_aci, q0, q1) in enumerate(lines_out):
                        if l2_idx not in used_line_ids and is_pure_dim_or_text_layer(l2_lay) and abs(q0[1] - q1[1]) <= alen_mm * 0.25:
                            if min(math.hypot(q0[0] - fpt_c[0], q0[1] - fpt_c[1]), math.hypot(q1[0] - fpt_c[0], q1[1] - fpt_c[1])) <= alen_mm * 0.45:
                                conn_lines.append(l2_idx)
                                used_line_ids.add(l2_idx)
                                far_pts.extend([q0, q1])

        if not conn_polys and not conn_lines:
            continue

        used_solid_indices.add(a['solid_id'])
        target_pts = far_pts if far_pts else [bmid_mm]
        leader_candidates.append({
            'a_lay': a_lay,
            'a_aci': a_aci,
            'tip_mm': tip_mm,
            'bmid_mm': bmid_mm,
            'apts_mm': apts_mm,
            'conn_polys': conn_polys,
            'conn_lines': conn_lines,
            'target_pts': target_pts,
            'matched_t_ids': [],
        })

    # 对每个候选引出文本，按“距离引线远端台面 (target_pts) 最近”原则唯一分配给归属引线
    for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
        if t_idx in used_text_ids or not is_annotation_layer(t_lay) or is_title_or_frame_layer(t_lay):
            continue
        if re.match(r'^[A-Z]-[A-Z]$', txt) or txt.startswith("技术要求") or txt.startswith("其余"):
            continue
        best_lc = None
        best_dist = float('inf')
        for lc in leader_candidates:
            tpts = lc['target_pts']
            sx0, sy0 = min(p[0] for p in tpts), min(p[1] for p in tpts)
            sx1, sy1 = max(p[0] for p in tpts), max(p[1] for p in tpts)
            is_short_sect = (len(lc['conn_polys']) == 0 and len(lc['conn_lines']) == 1 and (sx1 - sx0) < alen_mm * 0.5)
            if is_short_sect:
                tpts = list(tpts) + [lc['bmid_mm'], lc['tip_mm']]
                sx0, sy0 = min(p[0] for p in tpts), min(p[1] for p in tpts)
                sx1, sy1 = max(p[0] for p in tpts), max(p[1] for p in tpts)
            if is_short_sect and len(txt.strip()) > 2:
                continue
            ref_u = max(alen_mm, th)
            if (sx0 - ref_u * 3.6 <= tx <= sx1 + ref_u * 3.5) and (sy0 - ref_u * 2.4 <= ty <= sy1 + ref_u * 2.4):
                dx_box = max(0.0, sx0 - tx, tx - sx1)
                dy_box = max(0.0, sy0 - ty, ty - sy1)
                d_to_shelf = math.hypot(dx_box, dy_box * 1.6)
                if d_to_shelf <= ref_u * 4.2 and d_to_shelf < best_dist:
                    best_dist = d_to_shelf
                    best_lc = lc
        if best_lc is not None:
            best_lc['matched_t_ids'].append(t_idx)
            used_text_ids.add(t_idx)

    # 将无独立文字的辅助分支箭头（如双箭头共用一处 R0.5 标注或指向粗糙度台面的辅助箭头）并入其所连接的邻近标注块，杜绝空文本块
    active_leader_candidates = []
    for lc in leader_candidates:
        if lc['matched_t_ids']:
            active_leader_candidates.append(lc)
            continue
        merged_to_other = False
        all_lc_pts = [lc['tip_mm'], lc['bmid_mm']] + list(lc['target_pts'])
        # 优先尝试并入邻近的有文字 leader_candidates
        for other_lc in leader_candidates:
            if other_lc is lc or not other_lc['matched_t_ids'] or other_lc['a_lay'] != lc['a_lay']:
                continue
            other_pts = [other_lc['tip_mm'], other_lc['bmid_mm']] + list(other_lc['target_pts'])
            if any(math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= alen_mm * 2.2 for p1 in all_lc_pts for p2 in other_pts):
                other_lc['conn_polys'].extend(lc['conn_polys'])
                other_lc['conn_lines'].extend(lc['conn_lines'])
                other_lc.setdefault('extra_solids', []).append((lc['a_lay'], lc['a_aci'], lc['apts_mm']))
                merged_to_other = True
                break
        if not merged_to_other:
            # 尝试并入已生成的 ROUGH_MARK 或 FCF_MARK 块
            for blk in blocks_out:
                bx_b, by_b = blk['ins_pt']
                if any(math.hypot(p1[0] - bx_b, p1[1] - by_b) <= alen_mm * 8.0 for p1 in all_lc_pts):
                    for pi in lc['conn_polys']:
                        blk['polylines'].append((polylines_out[pi][0], polylines_out[pi][1], [(p[0] - bx_b, p[1] - by_b) for p in polylines_out[pi][2]], polylines_out[pi][3]))
                    for li in lc['conn_lines']:
                        blk['lines'].append((lines_out[li][0], lines_out[li][1], (lines_out[li][2][0] - bx_b, lines_out[li][2][1] - by_b), (lines_out[li][3][0] - bx_b, lines_out[li][3][1] - by_b)))
                    blk['solids'].append((lc['a_lay'], lc['a_aci'], [(p[0] - bx_b, p[1] - by_b) for p in lc['apts_mm']]))
                    merged_to_other = True
                    break
        if not merged_to_other:
            active_leader_candidates.append(lc)

    for lc in active_leader_candidates:
        base_x, base_y = lc['tip_mm']
        joined_t = " ".join(texts_out[ti][2] for ti in lc['matched_t_ids']).strip()
        is_weld = any(wk in joined_t for wk in ("焊", "△", "▽", "∨", "GB/T324", "GB/T 324"))
        is_section = (len(lc['matched_t_ids']) == 1 and len(joined_t) == 1 and joined_t.isalpha() and joined_t.isupper())
        b_prefix = "WELD_MARK" if is_weld else ("SECTION_MARK" if is_section else "LEADER_MARK")
        bname = f"{b_prefix}_{len(blocks_out) + 1}"
        rel_polys = [
            (polylines_out[pi][0], polylines_out[pi][1],
             [(p[0] - base_x, p[1] - base_y) for p in polylines_out[pi][2]],
             polylines_out[pi][3])
            for pi in lc['conn_polys']
        ]
        rel_lines = [
            (lines_out[li][0], lines_out[li][1],
             (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
             (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
            for li in lc['conn_lines']
        ]
        w_polys, w_lines = _weld_leader_geometry(rel_polys, rel_lines, tol=max(0.35 * alen_mm, 0.8))
        blocks_out.append({
            'block_name': bname,
            'layer': lc['a_lay'],
            'ins_pt': (base_x, base_y),
            'polylines': w_polys,
            'lines': w_lines,
            'solids': [(lc['a_lay'], lc['a_aci'], [(p[0] - base_x, p[1] - base_y) for p in lc['apts_mm']])] + [(sl, sa, [(p[0] - base_x, p[1] - base_y) for p in spts]) for sl, sa, spts in lc.get('extra_solids', [])],
            'texts': [
                (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                 (texts_out[ti][3] - base_x, texts_out[ti][4] - base_y),
                 texts_out[ti][5], texts_out[ti][6])
                for ti in lc['matched_t_ids']
            ],
        })

    # 4. 无箭头引出标注块 (CALLOUT_MARK) — 严格排除图框/标题栏图层文本，并将附加指针统一归入引线图层
    for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
        if p_idx in used_poly_ids or is_closed or not (3 <= len(pts) <= 6):
            continue
        if not is_pure_dim_or_text_layer(p_lay):
            continue
        horiz_seg = None
        has_diag = False
        for k_seg in range(len(pts) - 1):
            q0, q1 = pts[k_seg], pts[k_seg + 1]
            s_len = math.hypot(q1[0] - q0[0], q1[1] - q0[1])
            if s_len < 1e-3:
                continue
            if abs(q0[1] - q1[1]) <= alen_mm * 0.45 and abs(q1[0] - q0[0]) >= alen_mm * 2.0:
                horiz_seg = (min(q0[0], q1[0]), max(q0[0], q1[0]), 0.5 * (q0[1] + q1[1]))
            elif 0.10 <= abs(q1[0] - q0[0]) / s_len <= 0.99 and 0.10 <= abs(q1[1] - q0[1]) / s_len <= 0.99:
                has_diag = True
        if horiz_seg is None:
            continue

        hx0, hx1, hy = horiz_seg
        matched_t_ids = []
        for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out):
            if t_idx in used_text_ids or abs(tang) > 5.0 or is_title_or_frame_layer(t_lay):
                continue
            if not is_pure_dim_or_text_layer(t_lay) and not (has_diag and t_lay in ("DRAW-XI",)):
                continue
            if re.match(r'^[A-Z]-[A-Z]$', txt) or txt.startswith("技术要求") or txt.startswith("其余"):
                continue
            if (hx0 - th * 2.0 <= tx <= hx1 + th * 2.5) and (-th * 1.8 <= (ty - hy) <= th * 1.8):
                matched_t_ids.append(t_idx)

        if matched_t_ids:
            used_poly_ids.add(p_idx)
            for t_idx in matched_t_ids:
                used_text_ids.add(t_idx)
            branch_lines = []
            for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
                if l_idx not in used_line_ids and l_lay in (p_lay, "0"):
                    if any(math.hypot(lp0[0] - qp[0], lp0[1] - qp[1]) <= alen_mm * 0.5 or
                           math.hypot(lp1[0] - qp[0], lp1[1] - qp[1]) <= alen_mm * 0.5 for qp in pts):
                        branch_lines.append(l_idx)
                        used_line_ids.add(l_idx)

            base_x, base_y = pts[-1]
            bname = f"CALLOUT_MARK_{len(blocks_out) + 1}"
            c_polys = [(p_lay, p_aci, [(p[0] - base_x, p[1] - base_y) for p in pts], False)]
            c_lines = [
                (p_lay if lines_out[li][0] == "0" else lines_out[li][0],
                 p_aci if lines_out[li][0] == "0" else lines_out[li][1],
                 (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
                 (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
                for li in branch_lines
            ]
            w_polys, w_lines = _weld_leader_geometry(c_polys, c_lines, tol=max(0.35 * alen_mm, 0.8))
            blocks_out.append({
                'block_name': bname,
                'layer': p_lay,
                'ins_pt': (base_x, base_y),
                'polylines': w_polys,
                'lines': w_lines,
                'solids': [],
                'texts': _merge_callout_collinear_texts([
                    (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                     (texts_out[ti][3] - base_x, texts_out[ti][4] - base_y),
                     texts_out[ti][5], texts_out[ti][6])
                    for ti in matched_t_ids
                ]),
            })

    # 检查由水平台面 LINE + 斜向指针 LINE 组成的无箭头引出标注
    for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
        if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay):
            continue
        if abs(lp0[1] - lp1[1]) <= alen_mm * 0.45 and abs(lp1[0] - lp0[0]) >= alen_mm * 2.5:
            diag_branches = []
            for l2_idx, (l2_lay, l2_aci, q0, q1) in enumerate(lines_out):
                if l2_idx != l_idx and l2_idx not in used_line_ids and l2_lay in (l_lay, "0"):
                    l2_len = math.hypot(q1[0] - q0[0], q1[1] - q0[1])
                    if l2_len > alen_mm * 1.5 and 0.12 <= abs(q1[0] - q0[0]) / l2_len <= 0.98 and 0.12 <= abs(q1[1] - q0[1]) / l2_len <= 0.98:
                        if min(math.hypot(q0[0] - lp0[0], q0[1] - lp0[1]), math.hypot(q0[0] - lp1[0], q0[1] - lp1[1]),
                               math.hypot(q1[0] - lp0[0], q1[1] - lp0[1]), math.hypot(q1[0] - lp1[0], q1[1] - lp1[1])) <= alen_mm * 0.6:
                            diag_branches.append(l2_idx)
            if not diag_branches:
                continue
            hx0, hx1, hy = min(lp0[0], lp1[0]), max(lp0[0], lp1[0]), 0.5 * (lp0[1] + lp1[1])
            matched_t_ids = [
                t_idx for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out)
                if t_idx not in used_text_ids and abs(tang) <= 5.0 and is_pure_dim_or_text_layer(t_lay) and not is_title_or_frame_layer(t_lay)
                and (hx0 - th * 2.0 <= tx <= hx1 + th * 2.5) and (-th * 1.8 <= (ty - hy) <= th * 1.8)
            ]
            if matched_t_ids:
                conn_l = [l_idx] + diag_branches
                for li in conn_l:
                    used_line_ids.add(li)
                for t_idx in matched_t_ids:
                    used_text_ids.add(t_idx)
                base_x, base_y = lp0
                bname = f"CALLOUT_MARK_{len(blocks_out) + 1}"
                c_lines = [
                    (l_lay if lines_out[li][0] == "0" else lines_out[li][0],
                     l_aci if lines_out[li][0] == "0" else lines_out[li][1],
                     (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
                     (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
                    for li in conn_l
                ]
                w_polys, w_lines = _weld_leader_geometry([], c_lines, tol=max(0.35 * alen_mm, 0.8))
                blocks_out.append({
                    'block_name': bname,
                    'layer': l_lay,
                    'ins_pt': (base_x, base_y),
                    'polylines': w_polys,
                    'lines': w_lines,
                    'solids': [],
                    'texts': _merge_callout_collinear_texts([
                        (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                         (texts_out[ti][3] - base_x, texts_out[ti][4] - base_y),
                         texts_out[ti][5], texts_out[ti][6])
                        for ti in matched_t_ids
                    ]),
                })

    # 5. 坡度/排水方向箭头标注块 (SLOPE_MARK) — 含同坐标重复折线及 4 点往返折线去重
    seen_slope_pos = set()
    for p_idx, (p_lay, p_aci, pts, is_closed) in enumerate(polylines_out):
        if p_idx in used_poly_ids or not is_pure_dim_or_text_layer(p_lay):
            continue
        if len(pts) == 4 and math.hypot(pts[1][0] - pts[3][0], pts[1][1] - pts[3][1]) <= alen_mm * 0.15:
            pts = pts[:3]
            is_closed = False
        if len(pts) != 3:
            continue
        pxs = [p[0] for p in pts]
        pys = [p[1] for p in pts]
        pw, ph = max(pxs) - min(pxs), max(pys) - min(pys)
        if not (alen_mm * 2.5 <= pw <= alen_mm * 8.0 and ph <= alen_mm * 0.9):
            continue
        pcx, pcy = 0.5 * (min(pxs) + max(pxs)), 0.5 * (min(pys) + max(pys))
        s_key = (round(pcx, 0), round(pcy, 0))
        if s_key in seen_slope_pos:
            used_poly_ids.add(p_idx)
            continue
        barb_lines = [
            l_idx for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out)
            if l_idx not in used_line_ids and l_lay == p_lay
            and math.hypot(lp1[0] - lp0[0], lp1[1] - lp0[1]) <= alen_mm * 2.5
            and math.hypot(0.5 * (lp0[0] + lp1[0]) - pcx, 0.5 * (lp0[1] + lp1[1]) - pcy) <= pw * 0.65
        ]
        near_t = [
            t_idx for t_idx, (t_lay, t_aci, txt, tx, ty, th, tang) in enumerate(texts_out)
            if t_idx not in used_text_ids and not is_title_or_frame_layer(t_lay)
            and abs(tx - pcx) <= pw * 0.95 and abs(ty - pcy) <= pw * 0.95
        ]
        if barb_lines or near_t:
            seen_slope_pos.add(s_key)
            used_poly_ids.add(p_idx)
            for li in barb_lines:
                used_line_ids.add(li)
            for ti in near_t:
                used_text_ids.add(ti)
            base_x, base_y = pts[1]
            bname = f"SLOPE_MARK_{len(blocks_out) + 1}"
            blocks_out.append({
                'block_name': bname,
                'layer': p_lay,
                'ins_pt': (base_x, base_y),
                'polylines': [(p_lay, p_aci, [(p[0] - base_x, p[1] - base_y) for p in pts], False)],
                'lines': [
                    (lines_out[li][0], lines_out[li][1],
                     (lines_out[li][2][0] - base_x, lines_out[li][2][1] - base_y),
                     (lines_out[li][3][0] - base_x, lines_out[li][3][1] - base_y))
                    for li in barb_lines
                ],
                'solids': [],
                'texts': [
                    (texts_out[ti][0], texts_out[ti][1], texts_out[ti][2],
                     (texts_out[ti][3] - base_x, texts_out[ti][4] - base_y),
                     texts_out[ti][5], texts_out[ti][6])
                    for ti in near_t
                ],
            })

    # 6. 后处理迭代收拢：将退化环还原后残留在模型空间的尺寸界线 (ext_lines)、尺寸延长线及折线引出架（如 15 +0.1/0 台面折线）并入所属 DIMENSION 块
    if dimensions_out is not None:
        # 吸收连接在 DIMENSION 尺寸线末端的折线引出架（如轴承座 *D4 15 +0.1/0 顶部折线）
        for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
            if p_idx in used_poly_ids or is_cl or not is_pure_dim_or_text_layer(p_lay):
                continue
            for dm in dimensions_out:
                ref_pts = [dm['t1'], dm['t2'], dm['defpoint1'], dm['defpoint2']]
                for bl0, bl1 in dm.get('dim_lines', []) + dm.get('ext_lines', []):
                    ref_pts.extend([bl0, bl1])
                if any(
                    min(math.hypot(pts[0][0] - rp[0], pts[0][1] - rp[1]), math.hypot(pts[-1][0] - rp[0], pts[-1][1] - rp[1])) <= alen_mm * 0.45
                    for rp in ref_pts
                ):
                    for k_s in range(len(pts) - 1):
                        dm['dim_lines'].append((pts[k_s], pts[k_s + 1]))
                    used_poly_ids.add(p_idx)
                    break

        # 迭代吸收与 DIMENSION 共线或正交相连的尺寸界线与尺寸尾线（严格跳过包含多行参数的表格网格线区域）
        table_zones = []
        h_dim_segs = [
            (min(lp0[0], lp1[0]), max(lp0[0], lp1[0]), 0.5 * (lp0[1] + lp1[1]))
            for l_idx, (l_lay, _, lp0, lp1) in enumerate(lines_out)
            if l_idx not in used_line_ids and is_pure_dim_or_text_layer(l_lay)
            and abs(lp1[1] - lp0[1]) <= 0.35 and abs(lp1[0] - lp0[0]) >= alen_mm * 15.0
        ]
        if len(h_dim_segs) >= 4:
            tx0_t = min(s[0] for s in h_dim_segs)
            tx1_t = max(s[1] for s in h_dim_segs)
            ty0_t = min(s[2] for s in h_dim_segs) - alen_mm * 8.0
            ty1_t = max(s[2] for s in h_dim_segs) + alen_mm * 8.0
            table_zones.append((tx0_t - alen_mm, tx1_t + alen_mm, ty0_t, ty1_t))

        def in_table_zone(p0, p1):
            mx_l, my_l = 0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1])
            return any(zx0 <= mx_l <= zx1 and zy0 <= my_l <= zy1 for zx0, zx1, zy0, zy1 in table_zones)

        changed_dim_ext = True
        while changed_dim_ext:
            changed_dim_ext = False
            for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
                if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay) or in_table_zone(lp0, lp1):
                    continue
                dx_l, dy_l = lp1[0] - lp0[0], lp1[1] - lp0[1]
                llen_l = math.hypot(dx_l, dy_l)
                if llen_l <= alen_mm * 0.08:
                    # 清除标注图层上的极微小碎点杂线（如设备基础中 4mm 的孤立微线段）
                    used_line_ids.add(l_idx)
                    continue
                is_h_l = abs(dx_l) >= abs(dy_l)
                for dm in dimensions_out:
                    pts_ref = [dm['defpoint1'], dm['defpoint2'], dm['t1'], dm['t2']]
                    pts_ref.extend(dm.get('arrow1_pts', []))
                    pts_ref.extend(dm.get('arrow2_pts', []))
                    for bl0, bl1 in dm.get('dim_lines', []) + dm.get('ext_lines', []):
                        pts_ref.extend([bl0, bl1])
                    dm_h = abs(math.cos(math.radians(dm.get('dim_angle_deg', 0.0)))) >= 0.707
                    matched_ext = False
                    if dm_h and not is_h_l and abs(dx_l) <= 0.35:
                        lx = 0.5 * (lp0[0] + lp1[0])
                        ly0, ly1 = min(lp0[1], lp1[1]), max(lp0[1], lp1[1])
                        if any(abs(lx - rx) <= alen_mm * 0.35 and (ly0 - alen_mm * 1.8 <= ry <= ly1 + alen_mm * 1.8) for rx, ry in pts_ref):
                            matched_ext = True
                    elif not dm_h and is_h_l and abs(dy_l) <= 0.35:
                        ly = 0.5 * (lp0[1] + lp1[1])
                        lx0, lx1 = min(lp0[0], lp1[0]), max(lp0[0], lp1[0])
                        if any(abs(ly - ry) <= alen_mm * 0.35 and (lx0 - alen_mm * 1.8 <= rx <= lx1 + alen_mm * 1.8) for rx, ry in pts_ref):
                            matched_ext = True
                    elif dm_h and is_h_l and abs(dy_l) <= 0.35:
                        ly = 0.5 * (lp0[1] + lp1[1])
                        lx0, lx1 = min(lp0[0], lp1[0]), max(lp0[0], lp1[0])
                        if any(abs(ly - ry) <= alen_mm * 0.25 and (lx0 - alen_mm * 2.5 <= rx <= lx1 + alen_mm * 2.5) for rx, ry in pts_ref):
                            matched_ext = True
                    elif not dm_h and not is_h_l and abs(dx_l) <= 0.35:
                        lx = 0.5 * (lp0[0] + lp1[0])
                        ly0, ly1 = min(lp0[1], lp1[1]), max(lp0[1], lp1[1])
                        if any(abs(lx - rx) <= alen_mm * 0.25 and (ly0 - alen_mm * 2.5 <= ry <= ly1 + alen_mm * 2.5) for rx, ry in pts_ref):
                            matched_ext = True
                    if matched_ext:
                        used_line_ids.add(l_idx)
                        dm['ext_lines'].append((lp0, lp1))
                        changed_dim_ext = True
                        break

    # 6B. 清除已还原为 DIMENSION 文字后仍残留在模型空间 DIM/TXT 图层上的单线 SHX 笔画残片（如 A、*、0 等笔画）
    if dimensions_out is not None:
        dim_text_centers = [(dm['text_ins'][0], dm['text_ins'][1], dm['text_height']) for dm in dimensions_out]
        for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
            if p_idx in used_poly_ids or not is_pure_dim_or_text_layer(p_lay):
                continue
            pxs, pys = [p[0] for p in pts], [p[1] for p in pts]
            pcx, pcy = 0.5 * (min(pxs) + max(pxs)), 0.5 * (min(pys) + max(pys))
            pspan = max(max(pxs) - min(pxs), max(pys) - min(pys))
            if any(pspan <= th * 6.0 and math.hypot(pcx - tx, pcy - ty) <= max(th * 8.0, alen_mm * 5.0) for tx, ty, th in dim_text_centers):
                used_poly_ids.add(p_idx)
        for l_idx, (l_lay, l_aci, lp0, lp1) in enumerate(lines_out):
            if l_idx in used_line_ids or not is_pure_dim_or_text_layer(l_lay) or in_table_zone(lp0, lp1):
                continue
            llen = math.hypot(lp1[0] - lp0[0], lp1[1] - lp0[1])
            lmx, lmy = 0.5 * (lp0[0] + lp1[0]), 0.5 * (lp0[1] + lp1[1])
            if any(llen <= th * 2.5 and math.hypot(lmx - tx, lmy - ty) <= max(th * 4.5, alen_mm * 4.0) for tx, ty, th in dim_text_centers):
                used_line_ids.add(l_idx)

    # 7. 将残留在 DIM/TXT 图层上的阶梯剖切面转折细实线或标题栏分隔线归还至对应几何/图框图层（若已被闭合标题栏框覆盖则直接消去重影）
    for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(polylines_out):
        if p_idx in used_poly_ids or is_cl or not is_pure_dim_or_text_layer(p_lay):
            continue
        if len(pts) == 3 and min(p[1] for p in pts) <= 320.0 and max(p[0] for p in pts) >= 900.0:
            is_dup_tb = any(
                other_cl and is_title_or_frame_layer(other_lay)
                and all(any(math.hypot(p[0] - op[0], p[1] - op[1]) <= 0.5 for op in other_pts) for p in pts)
                for o_idx, (other_lay, _, other_pts, other_cl) in enumerate(polylines_out)
                if o_idx != p_idx and o_idx not in used_poly_ids
            )
            if is_dup_tb:
                used_poly_ids.add(p_idx)
            else:
                polylines_out[p_idx] = ('TC_ATTRIB', p_aci, pts, is_cl)
        elif len(pts) >= 4:
            polylines_out[p_idx] = ('DRAW_XI-IN' if '-IN' in p_lay else 'DRAW-XI', p_aci, pts, is_cl)

    if circles_out is not None and used_circle_ids:
        circles_out[:] = [c for i, c in enumerate(circles_out) if i not in used_circle_ids]
    rem_lines = [l for i, l in enumerate(lines_out) if i not in used_line_ids]
    rem_polys = [p for i, p in enumerate(polylines_out) if i not in used_poly_ids]
    rem_texts = [t for i, t in enumerate(texts_out) if i not in used_text_ids]

    # 8. 自动检测并封装工程参数表/地脚螺栓表/荷载表 (TABLE_BLOCK) 与标题栏/修改栏/会签栏网格表 (TITLE_TABLE)
    rem_lines, rem_polys, rem_texts, table_blocks = detect_and_assemble_tables(rem_lines, rem_polys, rem_texts, alen_mm)
    blocks_out.extend(table_blocks)

    # 9. 自动检测并封装“技术要求”段落块 (TECH_NOTE_k)：将标题“技术要求”及其正下方逐行排列的条款文本整合为独立块
    tech_headers = [
        idx for idx, t in enumerate(rem_texts)
        if t[2].strip().startswith("技术要求")
    ]
    if tech_headers:
        used_tech_ids = set()
        for h_idx in tech_headers:
            if h_idx in used_tech_ids:
                continue
            h_lay, h_aci, h_txt, hx, hy, h_th, h_ang = rem_texts[h_idx]
            note_ids = [h_idx]
            for c_idx, (c_lay, c_aci, c_txt, cx, cy, c_th, c_ang) in enumerate(rem_texts):
                if c_idx == h_idx or c_idx in used_tech_ids or abs(c_ang) > 5.0:
                    continue
                if (0.0 < hy - cy <= max(h_th * 16.0, alen_mm * 14.0)) and (abs(cx - hx) <= max(h_th * 12.0, alen_mm * 10.0)):
                    if re.match(r'^\d+[、\.\s]', c_txt.strip()) or any(k in c_txt for k in ("调质", "硬度", "未注", "倒角", "倒钝", "铅堵", "加工", "热处理", "涂漆", "焊")):
                        note_ids.append(c_idx)
            if len(note_ids) >= 2:
                used_tech_ids.update(note_ids)
                note_ids.sort(key=lambda idx: -rem_texts[idx][4])
                bx_t = min(rem_texts[idx][3] for idx in note_ids)
                by_t = min(rem_texts[idx][4] for idx in note_ids)
                blocks_out.append({
                    'block_name': f"TECH_NOTE_{len(blocks_out) + 1}",
                    'layer': h_lay,
                    'ins_pt': (bx_t, by_t),
                    'polylines': [],
                    'lines': [],
                    'solids': [],
                    'circles': [],
                    'texts': [
                        (rem_texts[ti][0], rem_texts[ti][1], rem_texts[ti][2],
                         (rem_texts[ti][3] - bx_t, rem_texts[ti][4] - by_t),
                         rem_texts[ti][5], rem_texts[ti][6])
                        for ti in note_ids
                    ],
                })
        if used_tech_ids:
            rem_texts = [t for idx, t in enumerate(rem_texts) if idx not in used_tech_ids]

    return rem_lines, rem_polys, rem_texts, blocks_out
