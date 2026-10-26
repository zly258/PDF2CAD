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
"""外形轮廓优化器：退化环还原、虚线/中心线点云重构、共线合并与共圆拟合（参考脚本 §6 前半，`reconstruct_dashed_and_center_entities` 结束于 2809 行）。"""
import math
from collections import defaultdict

import numpy as np

from .encoding import is_pure_dim_or_text_layer
from .geometry import (
    fit_circle_or_arc,
    fit_quarter_fillet_arc,
    is_degenerate_collinear_loop,
    simplify_collinear_pts,
)


def merge_collinear_lines(lines_list, angle_tol_sin=0.012, perp_tol=0.08, gap_tol=0.15):
    """
    将同一图层上共线（方向一致、法向偏差 <= perp_tol）且端点相接或重叠（gap <= gap_tol）的 LINE 线段
    无损合并为单条完整 LINE，绝不在 T 字交点或直角转折处串联成畸形折线。
    """
    by_group = defaultdict(list)
    for layer, aci, p1, p2 in lines_list:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 1e-4:
            continue
        ang = math.atan2(dy, dx) % math.pi
        if ang > math.pi * 0.995:
            ang = 0.0
        by_group[(layer, aci)].append((ang, p1, p2))

    out_lines = []
    for (layer, aci), items in by_group.items():
        used = [False] * len(items)
        for i in range(len(items)):
            if used[i]:
                continue
            ang_i, p1_i, p2_i = items[i]
            used[i] = True
            ux, uy = math.cos(ang_i), math.sin(ang_i)
            nx, ny = -uy, ux

            group_pts = [p1_i, p2_i]
            base_n = 0.5 * ((p1_i[0] * nx + p1_i[1] * ny) + (p2_i[0] * nx + p2_i[1] * ny))

            changed = True
            while changed:
                changed = False
                u_vals = [p[0] * ux + p[1] * uy for p in group_pts]
                u_min, u_max = min(u_vals), max(u_vals)
                for j in range(len(items)):
                    if used[j]:
                        continue
                    ang_j, q1, q2 = items[j]
                    if abs(math.sin(ang_i - ang_j)) > angle_tol_sin:
                        continue
                    n_q1 = q1[0] * nx + q1[1] * ny
                    n_q2 = q2[0] * nx + q2[1] * ny
                    if abs(n_q1 - base_n) > perp_tol or abs(n_q2 - base_n) > perp_tol:
                        continue
                    uq1 = q1[0] * ux + q1[1] * uy
                    uq2 = q2[0] * ux + q2[1] * uy
                    q_min, q_max = min(uq1, uq2), max(uq1, uq2)
                    if (u_min - gap_tol <= q_max) and (q_min <= u_max + gap_tol):
                        group_pts.extend([q1, q2])
                        used[j] = True
                        changed = True

            u_proj = [(p[0] * ux + p[1] * uy, p) for p in group_pts]
            u_proj.sort(key=lambda x: x[0])
            out_lines.append((layer, aci, u_proj[0][1], u_proj[-1][1]))
    return out_lines



def regularize_orthogonal_lines(lines_list, max_dev_mm=0.035, max_slope=0.002):
    """
    通用正交微倾规整器：对因 PDF 坐标浮点截断或 1pt 整数量化产生的微倾水平线/垂直线
    自动对齐为严格 0° / 90° 正交线段，同时滤除零长度退化碎线。
    """
    out = []
    for lay, aci, p1, p2 in lines_list:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 1e-3:
            continue
        eff_dev = 0.28 if length >= 45.0 else max_dev_mm
        eff_slope = 0.0048 if length >= 45.0 else max_slope
        if 0.0 < abs(dy) <= eff_dev and abs(dy) / length <= eff_slope:
            ym = round(0.5 * (p1[1] + p2[1]), 4)
            p1, p2 = (p1[0], ym), (p2[0], ym)
        elif 0.0 < abs(dx) <= eff_dev and abs(dx) / length <= eff_slope:
            xm = round(0.5 * (p1[0] + p2[0]), 4)
            p1, p2 = (xm, p1[1]), (xm, p2[1])
        out.append((lay, aci, p1, p2))
    return out


def chain_annotation_polylines(lines_list, tol=0.05):
    """仅对标注图层（DIM / DIM-IN / 螺栓_载荷）上的引线折线段进行端点连接以还原引线。"""
    by_group = defaultdict(list)
    out_lines = []
    for layer, aci, p1, p2 in lines_list:
        if is_pure_dim_or_text_layer(layer):
            by_group[(layer, aci)].append([p1, p2])
        else:
            out_lines.append((layer, aci, p1, p2))

    out_polys = []
    for (layer, aci), segs in by_group.items():
        used = [False] * len(segs)
        for i in range(len(segs)):
            if used[i]:
                continue
            chain = list(segs[i])
            used[i] = True
            changed = True
            while changed:
                changed = False
                for j in range(len(segs)):
                    if used[j]:
                        continue
                    q0, q1 = segs[j]
                    if math.hypot(chain[-1][0] - q0[0], chain[-1][1] - q0[1]) < tol:
                        chain.append(q1)
                        used[j] = True
                        changed = True
                    elif math.hypot(chain[-1][0] - q1[0], chain[-1][1] - q1[1]) < tol:
                        chain.append(q0)
                        used[j] = True
                        changed = True
                    elif math.hypot(chain[0][0] - q1[0], chain[0][1] - q1[1]) < tol:
                        chain.insert(0, q0)
                        used[j] = True
                        changed = True
                    elif math.hypot(chain[0][0] - q0[0], chain[0][1] - q0[1]) < tol:
                        chain.insert(0, q1)
                        used[j] = True
                        changed = True
            chain = simplify_collinear_pts(chain, tol=tol * 0.5)
            if len(chain) == 2:
                out_lines.append((layer, aci, chain[0], chain[1]))
            elif len(chain) > 2:
                is_closed = math.hypot(chain[0][0] - chain[-1][0], chain[0][1] - chain[-1][1]) < tol
                if is_closed:
                    chain = chain[:-1]
                out_polys.append((layer, aci, chain, is_closed))
    return out_lines, out_polys


def sample_arc_points(cx, cy, r, a0_deg, a1_deg, n_samples=5):
    """在圆弧 `(cx, cy, r, a0_deg, a1_deg)` 上逆时针均匀采样 `n_samples` 个点，用于多段虚线圆弧点云联合拟合。"""
    sweep = (a1_deg - a0_deg) % 360.0
    if sweep < 1e-3:
        sweep = 360.0
    pts = []
    for k in range(n_samples):
        ang = math.radians(a0_deg + sweep * (k / max(n_samples - 1, 1)))
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts



def decompose_compound_polyline(pts, is_closed, layer_name="", scale_hint=1.0):
    """
    通用复合折线（直线段 + 圆弧/倒圆角/腰形孔/圆角矩形）分段解析器：
    当一条折线同时包含长直线段与离散圆弧段（导致整体拟合圆/圆弧失败）时，
    按边长与转角连续性将其切分为直线子段与弯曲子段，若弯曲子段可拟合成原生 ARC，
    则无损拆解为原生 LINE 列表 + 原生 ARC 列表；否则保持原折线不变。
    """
    lu = str(layer_name).upper()
    if "HATCH" in lu or "剖面" in lu or len(pts) < 7:
        return None
    ring = list(pts) + ([pts[0]] if is_closed and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-3 else [])
    n_seg = len(ring) - 1
    if n_seg < 6:
        return None

    seg_lens = [math.hypot(ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1]) for i in range(n_seg)]
    short_segs = [s for s in seg_lens if s > 1e-4]
    if not short_segs:
        return None
    med_len = float(np.median(short_segs))
    long_thresh = max(med_len * 3.0, 2.5 * max(scale_hint, 1.0))

    is_long = [s >= long_thresh for s in seg_lens]
    if not (any(is_long) and sum(1 for x in is_long if not x) >= 4):
        return None

    # 若为闭合折线且起点落在短边段内部，旋转起点至第一条长直线段起点
    if is_closed and not is_long[0]:
        first_long = next((idx for idx, flag in enumerate(is_long) if flag), None)
        if first_long is not None:
            ring = ring[first_long:-1] + ring[:first_long] + [ring[first_long]]
            seg_lens = [math.hypot(ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1]) for i in range(len(ring) - 1)]
            is_long = [s >= long_thresh for s in seg_lens]

    out_lines = []
    out_arcs = []
    i = 0
    while i < len(seg_lens):
        if is_long[i]:
            out_lines.append((ring[i], ring[i + 1]))
            i += 1
        else:
            j = i
            while j < len(seg_lens) and not is_long[j]:
                j += 1
            sub_pts = ring[i : j + 1]
            if len(sub_pts) >= 5:
                arc_fit = fit_circle_or_arc(sub_pts, rel_tol=0.035, layer_name=layer_name, scale_Hint=scale_hint)
                if arc_fit is not None and arc_fit[0] == 'ARC':
                    out_arcs.append(arc_fit[1:])
                else:
                    return None
            else:
                return None
            i = j

    if out_lines and out_arcs:
        return out_lines, out_arcs
    return None


def stitch_open_contour_polylines(polylines_list, tol=0.06):
    """
    通用开放曲线折线缝合器：将同一图层上端点相接（距离 <= tol）的分段开放折线（如上下两半相贯线、分段样条曲线）
    自动缝合为单条连续 POLYLINE；若首尾闭合则自动设置 is_closed=True。
    """
    by_group = defaultdict(list)
    closed_out = []
    for lay, aci, pts, is_cl in polylines_list:
        if is_cl or len(pts) < 2:
            closed_out.append((lay, aci, pts, is_cl))
        else:
            by_group[(lay, aci)].append(list(pts))

    stitched_out = list(closed_out)
    for (lay, aci), chains in by_group.items():
        used = [False] * len(chains)
        for i in range(len(chains)):
            if used[i]:
                continue
            curr = chains[i]
            used[i] = True
            changed = True
            while changed:
                changed = False
                for j in range(len(chains)):
                    if used[j]:
                        continue
                    cand = chains[j]
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
            is_cl = len(curr) >= 4 and math.hypot(curr[0][0] - curr[-1][0], curr[0][1] - curr[-1][1]) <= tol
            if is_cl:
                curr = curr[:-1]
                stitched_out.append((lay, aci, curr, True))
            else:
                # 检查开放折线首部或尾部是否包含首尾闭合的子环（如倒角矩形外框与相邻槽口共用顶点被串联为 1 条开放折线）
                split_done = False
                if len(curr) >= 6:
                    for k_sub in range(3, len(curr) - 1):
                        if math.hypot(curr[0][0] - curr[k_sub][0], curr[0][1] - curr[k_sub][1]) <= tol:
                            stitched_out.append((lay, aci, curr[:k_sub], True))
                            rem_tail = curr[k_sub:]
                            if len(rem_tail) >= 2:
                                is_rem_cl = len(rem_tail) >= 4 and math.hypot(rem_tail[0][0] - rem_tail[-1][0], rem_tail[0][1] - rem_tail[-1][1]) <= tol
                                stitched_out.append((lay, aci, rem_tail[:-1] if is_rem_cl else rem_tail, is_rem_cl))
                            split_done = True
                            break
                    if not split_done:
                        for k_sub in range(1, len(curr) - 3):
                            if math.hypot(curr[-1][0] - curr[k_sub][0], curr[-1][1] - curr[k_sub][1]) <= tol:
                                stitched_out.append((lay, aci, curr[k_sub:-1], True))
                                rem_head = curr[:k_sub + 1]
                                if len(rem_head) >= 2:
                                    stitched_out.append((lay, aci, rem_head, False))
                                split_done = True
                                break
                if not split_done:
                    stitched_out.append((lay, aci, curr, False))
    return stitched_out


def deduplicate_and_merge_circles_arcs(circles_list, arcs_list, pos_tol=0.25, r_tol=0.22):
    """
    通用圆与圆弧去重及共圆弧区间合并算法：
    1. 消除同图层、同圆心、同半径的叠印重复 CIRCLE；
    2. 消除已被同图层同圆心同半径 CIRCLE 覆盖的冗余 ARC；
    3. 将同图层、同圆心、同半径的多段相邻或重叠 ARC（如两半圆或分段螺纹弧）合并为单条连续 ARC，
       若合并后总角度跨度 >= 345° 则自动升级为原生 CIRCLE。
    """
    unique_circles = []
    for lay, aci, cx, cy, r in circles_list:
        if not any(
            lay == olay and math.hypot(cx - ocx, cy - ocy) <= pos_tol and abs(r - orad) <= max(r_tol, 0.02 * r)
            for olay, _, ocx, ocy, orad in unique_circles
        ):
            unique_circles.append((lay, aci, cx, cy, r))

    # 过滤掉已被同图层 CIRCLE 完全覆盖的冗余 ARC，并对剩余 ARC 按 (layer, cx, cy, r) 聚类合并角度区间
    arc_groups = []
    for lay, aci, cx, cy, r, a0, a1 in arcs_list:
        lu_a = str(lay).upper()
        is_cd_a = ("DASH" in lu_a) or ("CENTER" in lu_a) or ("HIDE" in lu_a) or ("虚线" in lu_a) or ("中心" in lu_a)
        p_tol_a = max(pos_tol * 2.2, 0.55) if is_cd_a else pos_tol
        if any(
            lay == clay and math.hypot(cx - ccx, cy - ccy) <= p_tol_a and abs(r - crad) <= (max(r_tol * 1.8, 0.45, 0.12 * crad) if is_cd_a else max(r_tol, 0.025 * r))
            for clay, _, ccx, ccy, crad in unique_circles
        ):
            continue
        matched_g = None
        for g in arc_groups:
            if g['lay'] == lay and math.hypot(cx - g['cx'], cy - g['cy']) <= pos_tol and abs(r - g['r']) <= max(r_tol, 0.025 * r):
                matched_g = g
                break
        if matched_g is None:
            arc_groups.append({'lay': lay, 'aci': aci, 'cx': cx, 'cy': cy, 'r': r, 'intervals': [(a0 % 360.0, a1 % 360.0)]})
        else:
            matched_g['intervals'].append((a0 % 360.0, a1 % 360.0))

    merged_arcs = []
    for g in arc_groups:
        lay, aci, cx, cy, r = g['lay'], g['aci'], g['cx'], g['cy'], g['r']
        ivs = g['intervals']
        if len(ivs) == 1:
            a0, a1 = ivs[0]
            if (a1 - a0) % 360.0 >= 348.0:
                unique_circles.append((lay, aci, cx, cy, r))
            else:
                merged_arcs.append((lay, aci, cx, cy, r, a0, a1))
            continue

        # 使用 0.5° 角度栅格合并同圆上的多段圆弧区间（支持跨 0°/360° 边界）
        n_bins = 720
        covered = np.zeros(n_bins, dtype=bool)
        for a0, a1 in ivs:
            sweep = (a1 - a0) % 360.0
            if sweep < 0.5:
                continue
            steps = max(2, int(math.ceil(sweep * 2.0)))
            for s_i in range(steps + 1):
                ang = (a0 + sweep * (s_i / steps)) % 360.0
                covered[int(round(ang * 2.0)) % n_bins] = True

        # 桥接 <= 12° (24 bins) 的微小断口（如螺纹圆弧或 PDF 分段圆弧接缝）
        for k_b in range(n_bins):
            if covered[k_b]:
                for gap in range(1, 25):
                    if covered[(k_b + gap) % n_bins]:
                        for fill_i in range(1, gap):
                            covered[(k_b + fill_i) % n_bins] = True
                        break

        total_deg = float(np.sum(covered)) * 0.5
        if total_deg >= 345.0:
            unique_circles.append((lay, aci, cx, cy, r))
        else:
            # 寻找最长连续未覆盖缺口作为起点，提取连续覆盖弧段
            not_cov = ~covered
            runs = []
            in_run = False
            start_b = 0
            # Find a gap to start scanning
            start_scan = int(np.argmin(covered))
            for offset in range(n_bins):
                idx_b = (start_scan + offset) % n_bins
                if covered[idx_b] and not in_run:
                    in_run = True
                    start_b = idx_b
                elif not covered[idx_b] and in_run:
                    in_run = False
                    runs.append((start_b * 0.5, idx_b * 0.5))
            if in_run:
                runs.append((start_b * 0.5, ((start_scan + n_bins) % n_bins) * 0.5))
            for ra0, ra1 in runs:
                if (ra1 - ra0) % 360.0 >= 2.0:
                    merged_arcs.append((lay, aci, cx, cy, r, ra0 % 360.0, ra1 % 360.0))

    return unique_circles, merged_arcs


def reconstruct_dashed_and_center_entities(lines_out, circles_out, arcs_out, polylines_out, alen_mm):
    """
    针对 CENTER / DASHED 图层（以及退化闭合折线）被 PDF 导出打散的碎线段、碎点与虚线圆弧进行智能原生重构：
    1. 将所有图层上因 PDF `m ... l h S` 产生的零面积共线闭合折线还原为单条原生 LINE；
    2. 清除 CENTER / DASHED 图层上跨度极小（< 0.65 * alen_mm）的闭合点划菱形点垃圾；
    3. 将 DASHED / CENTER 图层上的短弧形折线（5..20 点）与离散圆弧按点云联合最小二乘拟合为完整 CIRCLE（解决短圆弧单独拟合圆心/半径漂移问题）；
    4. 将 CENTER / DASHED 图层上共线的断续短线段跨间隙合并为单条连续的原生 LINE。
    """
    clean_polys = []
    candidate_arcs = list(arcs_out)
    raw_lines = []
    hatch_short_chains = []
    for l_item in lines_out:
        l_lay, l_aci, lp0, lp1 = l_item
        if "HATCH" in str(l_lay).upper():
            dx_h, dy_h = lp1[0] - lp0[0], lp1[1] - lp0[1]
            llen_h = math.hypot(dx_h, dy_h)
            ang_h = math.degrees(math.atan2(dy_h, dx_h)) % 180.0
            is_diag_45 = (35.0 <= ang_h <= 55.0) or (125.0 <= ang_h <= 145.0)
            if llen_h <= max(alen_mm * 1.35, 4.8) and (llen_h <= max(alen_mm * 0.75, 2.6) or not is_diag_45):
                hatch_short_chains.append((l_lay, l_aci, [lp0, lp1], False))
                continue
        raw_lines.append(l_item)

    if hatch_short_chains:
        stitched_h = stitch_open_contour_polylines(hatch_short_chains, tol=max(0.015 * alen_mm, 0.08))
        for h_lay, h_aci, h_pts, h_cl in stitched_h:
            if not h_cl and len(h_pts) == 2:
                raw_lines.append((h_lay, h_aci, h_pts[0], h_pts[1]))
            else:
                polylines_out.append((h_lay, h_aci, h_pts, h_cl))

    polylines_out = stitch_open_contour_polylines(polylines_out, tol=max(0.01 * alen_mm, 0.06))

    for layer, aci, pts, is_closed in polylines_out:
        if not is_closed and len(pts) >= 3:
            if len(pts) <= 6:
                pts = simplify_collinear_pts(pts, tol=max(0.015 * alen_mm, 0.04))
            else:
                pts = simplify_collinear_pts(pts, tol=1e-2)
        lu = str(layer).upper()
        is_cd = ("CENTER" in lu) or ("DASH" in lu) or ("HIDE" in lu) or ("中心" in lu) or ("虚线" in lu)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys))

        # 1. 任何图层上的退化零面积共线折线（含 closed=True）直接还原为单条 LINE
        col_pair = is_degenerate_collinear_loop(pts, tol=max(0.025 * alen_mm, 0.04))
        if col_pair is not None:
            raw_lines.append((layer, aci, col_pair[0], col_pair[1]))
            continue

        # 2. 非 HATCH 图层上的闭合正多边形圆（如锚栓小圆孔）或浅圆弧尝试还原为 CIRCLE / ARC，或拆解直线+圆弧复合折线
        if "HATCH" not in lu and len(pts) >= 5 and (not is_cd or is_closed or span >= alen_mm * 0.85):
            fit_c = fit_circle_or_arc(
                pts, rel_tol=0.06 if is_closed else 0.036, layer_name=layer,
                scale_Hint=max(alen_mm / 3.0, 1.0), is_closed_hint=is_closed
            )
            if fit_c is not None:
                if fit_c[0] == 'CIRCLE':
                    circles_out.append((layer, aci, fit_c[1], fit_c[2], fit_c[3]))
                    continue
                elif not is_closed and fit_c[0] == 'ARC':
                    candidate_arcs.append((layer, aci, fit_c[1], fit_c[2], fit_c[3], fit_c[4], fit_c[5]))
                    continue
            decomp = decompose_compound_polyline(pts, is_closed, layer_name=layer, scale_hint=max(alen_mm / 3.0, 1.0))
            if decomp is not None:
                d_lines, d_arcs = decomp
                for lp0, lp1 in d_lines:
                    raw_lines.append((layer, aci, lp0, lp1))
                for cx, cy, r, a0, a1 in d_arcs:
                    candidate_arcs.append((layer, aci, cx, cy, r, a0, a1))
                continue

        if is_cd:
            # 3. 过滤极小点划点垃圾（如设备埋件中 0.16mm 的 9 顶点闭合菱形点）
            if is_closed and span <= alen_mm * 0.65:
                continue
            # 3B. 对虚线层上因单个虚线缺口未闭合的投影椭圆环（>=16 点且首尾距离 <= 0.55 * alen_mm）自动闭合
            if not is_closed and len(pts) >= 16 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= alen_mm * 0.55:
                is_closed = True
            # 4. 尝试将虚线圆周上的弧形短折线（5..22 点且跨度足够）或虚线 90° 小倒圆角拟合成圆弧段
            if not is_closed and 5 <= len(pts) <= 22 and span >= alen_mm * 0.85:
                fit_res = fit_circle_or_arc(pts, rel_tol=0.045, layer_name=layer)
                if fit_res is None and 5 <= len(pts) <= 12 and "DASH" in lu:
                    fit_res = fit_quarter_fillet_arc(pts, max_radius=max(alen_mm * 1.5, 4.0))
                if fit_res is not None:
                    kind, cx, cy, r, a0, a1 = fit_res
                    if kind == 'CIRCLE':
                        circles_out.append((layer, aci, cx, cy, r))
                    else:
                        candidate_arcs.append((layer, aci, cx, cy, r, a0, a1))
                    continue
            # 5. 将 CENTER / DASHED 上的共线短折线还原为 LINE 段参与中心线/虚线合并
            simp = simplify_collinear_pts(pts, tol=0.03 * alen_mm)
            if len(simp) == 2 and not is_closed:
                raw_lines.append((layer, aci, simp[0], simp[1]))
                continue
            if not is_closed and len(simp) <= 5:
                for k in range(len(simp) - 1):
                    raw_lines.append((layer, aci, simp[k], simp[k + 1]))
                continue

        if not is_closed and len(pts) >= 4 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-2:
            is_closed = True
            pts = pts[:-1]
        if is_closed and len(pts) >= 3:
            dedup_pts = [pts[0]]
            for p in pts[1:]:
                if math.hypot(p[0] - dedup_pts[-1][0], p[1] - dedup_pts[-1][1]) > 1e-3:
                    dedup_pts.append(p)
            if len(dedup_pts) > 2 and math.hypot(dedup_pts[0][0] - dedup_pts[-1][0], dedup_pts[0][1] - dedup_pts[-1][1]) <= 1e-3:
                dedup_pts.pop()
            pts = dedup_pts
        if len(pts) >= 2:
            clean_polys.append((layer, aci, pts, is_closed))

    # 合并同心同半径（或点云共圆）的 DASHED / CENTER 圆弧段为完整 CIRCLE
    final_arcs = []
    cd_arcs = []
    for item in candidate_arcs:
        lay = str(item[0]).upper()
        if "DASH" in lay or "CENTER" in lay or "HIDE" in lay or "中心" in lay or "虚线" in lay:
            cd_arcs.append(item)
        else:
            final_arcs.append(item)

    def fit_pts_lsq_circle(pts_list):
        arr = np.array(pts_list, dtype=float)
        mx, my = np.mean(arr[:, 0]), np.mean(arr[:, 1])
        u, v = arr[:, 0] - mx, arr[:, 1] - my
        A = np.column_stack([u, v, np.ones_like(u)])
        b = -(u**2 + v**2)
        try:
            sol, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
            uc, vc = -sol[0] / 2.0, -sol[1] / 2.0
            r_sq = uc**2 + vc**2 - sol[2]
            if r_sq <= 1e-3:
                return None
            fit_r = math.sqrt(r_sq)
            fit_cx, fit_cy = uc + mx, vc + my
            err = float(np.max(np.abs(np.hypot(arr[:, 0] - fit_cx, arr[:, 1] - fit_cy) - fit_r)))
            return fit_cx, fit_cy, fit_r, err
        except Exception:
            return None

    arc_samples = [sample_arc_points(a[2], a[3], a[4], a[5], a[6], 5) for a in cd_arcs]
    used_arc = [False] * len(cd_arcs)
    for i in range(len(cd_arcs)):
        if used_arc[i]:
            continue
        lay_i, aci_i, cx_i, cy_i, r_i, a0_i, a1_i = cd_arcs[i]
        merged_circle = None
        for j in range(i + 1, len(cd_arcs)):
            if used_arc[j] or cd_arcs[j][0] != lay_i:
                continue
            r_j = cd_arcs[j][4]
            if abs(r_i - r_j) > 0.42 * max(r_i, r_j):
                continue
            res_ij = fit_pts_lsq_circle(arc_samples[i] + arc_samples[j])
            if res_ij is None:
                continue
            fcx, fcy, fr, ferr = res_ij
            if ferr > max(0.03 * fr, 0.25) or abs(fr - 0.5 * (r_i + r_j)) > 0.35 * fr:
                continue
            grp = [i, j]
            for k in range(len(cd_arcs)):
                if k not in grp and not used_arc[k] and cd_arcs[k][0] == lay_i:
                    dists_k = [math.hypot(px - fcx, py - fcy) for px, py in arc_samples[k]]
                    if max(abs(d - fr) for d in dists_k) <= max(0.035 * fr, 0.35):
                        grp.append(k)
            all_pts = [pt for g in grp for pt in arc_samples[g]]
            res_all = fit_pts_lsq_circle(all_pts)
            if res_all is not None:
                fcx, fcy, fr, ferr = res_all
                if ferr <= max(0.035 * fr, 0.35):
                    arr_all = np.array(all_pts, dtype=float)
                    angs = np.sort(np.degrees(np.arctan2(arr_all[:, 1] - fcy, arr_all[:, 0] - fcx)) % 360.0)
                    max_gap = float(np.max(np.diff(np.append(angs, angs[0] + 360.0))))
                    if max_gap <= 225.0:
                        merged_circle = (grp, (lay_i, aci_i, fcx, fcy, fr))
                        break
        if merged_circle is not None:
            grp, c_item = merged_circle
            for g in grp:
                used_arc[g] = True
            circles_out.append(c_item)
        else:
            used_arc[i] = True
            sweep_i = (a1_i - a0_i) % 360.0
            if "DASH" in lay_i.upper() and sweep_i >= 250.0:
                circles_out.append((lay_i, aci_i, cx_i, cy_i, r_i))
            else:
                final_arcs.append(cd_arcs[i])

    # 对 CENTER / DASHED 图层的共线断续线段按虚线间隙桥接合并，其他图层按严格无缝共线合并
    cd_lines = []
    solid_lines = []
    for item in raw_lines:
        lu = str(item[0]).upper()
        if "CENTER" in lu or "DASH" in lu or "HIDE" in lu or "中心" in lu or "虚线" in lu:
            cd_lines.append(item)
        else:
            solid_lines.append(item)

    # 针对被虚拟打印驱动打散为数百段微步进线段 (len < 1.5mm) 的斜向中心线与中心圆钩（如地脚螺栓弯钩中心线），
    # 先对长线段共线合并，再对残留微线段点云执行通用 SVD 主直线提取与最小二乘圆弧重构
    cd_perp_tol = 0.28 if alen_mm <= 20.0 else max(0.08 * alen_mm, 0.28)
    long_cd = [it for it in cd_lines if math.hypot(it[3][0] - it[2][0], it[3][1] - it[2][1]) >= 1.5]
    micro_cd = [it for it in cd_lines if math.hypot(it[3][0] - it[2][0], it[3][1] - it[2][1]) < 1.5]
    if len(micro_cd) >= 40:
        merged_long_cd = merge_collinear_lines(long_cd, angle_tol_sin=0.022, perp_tol=cd_perp_tol, gap_tol=alen_mm * 3.8)
        # 过滤掉已落在 merged_long_cd 上的微点
        rem_micro = []
        for m_lay, m_aci, mp0, mp1 in micro_cd:
            mmx, mmy = 0.5 * (mp0[0] + mp1[0]), 0.5 * (mp0[1] + mp1[1])
            on_long = False
            for l_lay, _, lp0, lp1 in merged_long_cd:
                if l_lay != m_lay:
                    continue
                ldx, ldy = lp1[0] - lp0[0], lp1[1] - lp0[1]
                llen = math.hypot(ldx, ldy)
                if llen > 1e-3:
                    perp_m = abs((mmx - lp0[0]) * (-ldy / llen) + (mmy - lp0[1]) * (ldx / llen))
                    proj_m = (mmx - lp0[0]) * (ldx / llen) + (mmy - lp0[1]) * (ldy / llen)
                    if perp_m <= 0.25 and -1.5 <= proj_m <= llen + 1.5:
                        on_long = True
                        break
            if not on_long:
                rem_micro.append((m_lay, m_aci, mp0, mp1))
        if len(rem_micro) >= 25:
            m_lay0, m_aci0 = rem_micro[0][0], rem_micro[0][1]
            mids_arr = np.array([(0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1])) for _, _, p0, p1 in rem_micro])
            used_m = np.zeros(len(rem_micro), dtype=bool)
            for _ in range(6):
                avail = np.where(~used_m)[0]
                if len(avail) < 25:
                    break
                best_inl = []
                pts_av = mids_arr[avail]
                step_s = max(1, len(avail) // 40)
                for ii in range(0, len(avail), step_s):
                    for jj in range(ii + 1, len(avail), step_s):
                        dx_m = pts_av[jj, 0] - pts_av[ii, 0]
                        dy_m = pts_av[jj, 1] - pts_av[ii, 1]
                        d_m = math.hypot(dx_m, dy_m)
                        if d_m < alen_mm * 3.0:
                            continue
                        nx_m, ny_m = -dy_m / d_m, dx_m / d_m
                        perp_v = np.abs((pts_av[:, 0] - pts_av[ii, 0]) * nx_m + (pts_av[:, 1] - pts_av[ii, 1]) * ny_m)
                        inl = avail[perp_v <= 0.18]
                        if len(inl) > len(best_inl):
                            best_inl = inl
                if len(best_inl) >= 25:
                    p_inl = mids_arr[best_inl]
                    mean_p = np.mean(p_inl, axis=0)
                    _, _, vt = np.linalg.svd(p_inl - mean_p)
                    ux_m, uy_m = vt[0]
                    projs = (p_inl[:, 0] - mean_p[0]) * ux_m + (p_inl[:, 1] - mean_p[1]) * uy_m
                    s_projs = np.sort(projs)
                    if float(np.max(np.diff(s_projs))) <= alen_mm * 1.5:
                        used_m[best_inl] = True
                        ps = (float(mean_p[0] + s_projs[0] * ux_m), float(mean_p[1] + s_projs[0] * uy_m))
                        pe = (float(mean_p[0] + s_projs[-1] * ux_m), float(mean_p[1] + s_projs[-1] * uy_m))
                        merged_long_cd.append((m_lay0, m_aci0, ps, pe))
                    else:
                        break
                else:
                    break
            rem_arc_i = np.where(~used_m)[0]
            if len(rem_arc_i) >= 15:
                arc_pts_m = [pt for idx_m in rem_arc_i for pt in (rem_micro[idx_m][2], rem_micro[idx_m][3])]
                res_m_arc = fit_pts_lsq_circle(arc_pts_m)
                if res_m_arc is not None:
                    mcx, mcy, mr, merr = res_m_arc
                    if merr <= max(0.035 * mr, 0.25):
                        arr_ma = np.array(arc_pts_m, dtype=float)
                        unw = np.unwrap(np.arctan2(arr_ma[:, 1] - mcy, arr_ma[:, 0] - mcx))
                        a_min_d = math.degrees(float(np.min(unw))) % 360.0
                        a_max_d = math.degrees(float(np.max(unw))) % 360.0
                        # 移除同一圆弧区域内已被完整拟合取代的碎片子弧
                        final_arcs = [
                            fa for fa in final_arcs
                            if not (fa[0] == m_lay0 and math.hypot(fa[2] - mcx, fa[3] - mcy) <= mr * 1.2)
                        ]
                        final_arcs.append((m_lay0, m_aci0, mcx, mcy, mr, a_min_d, a_max_d))
                        used_m[rem_arc_i] = True
            for idx_m in np.where(~used_m)[0]:
                merged_long_cd.append(rem_micro[idx_m])
        merged_cd_lines = merged_long_cd
    else:
        merged_cd_lines = merge_collinear_lines(
            cd_lines, angle_tol_sin=0.022, perp_tol=cd_perp_tol, gap_tol=alen_mm * 3.8
        )
    merged_solid_lines = merge_collinear_lines(
        solid_lines, angle_tol_sin=0.010, perp_tol=max(0.02 * alen_mm, 0.05), gap_tol=max(0.06 * alen_mm, 0.1)
    )

    # 利用正交中心线 (CENTER) 十字交点精确引导小直径虚线圆孔（如 M5/M8 螺纹孔或沉孔）与弦线段拟合成整圆 CIRCLE
    h_clines, v_clines = [], []
    for lay, _, p0, p1 in merged_cd_lines:
        if "CENTER" in str(lay).upper() or "中心" in str(lay).upper():
            if abs(p1[1] - p0[1]) < 0.25 and abs(p1[0] - p0[0]) > 2.0:
                h_clines.append((min(p0[0], p1[0]), max(p0[0], p1[0]), 0.5 * (p0[1] + p1[1])))
            elif abs(p1[0] - p0[0]) < 0.25 and abs(p1[1] - p0[1]) > 2.0:
                v_clines.append((0.5 * (p0[0] + p1[0]), min(p0[1], p1[1]), max(p0[1], p1[1])))
    crosshairs = [
        (vx, hy)
        for hx0, hx1, hy in h_clines
        for vx, vy0, vy1 in v_clines
        if hx0 - 2.0 <= vx <= hx1 + 2.0 and vy0 - 2.0 <= hy <= vy1 + 2.0
    ]

    if crosshairs and final_arcs:
        absorbed_cd_line_ids = set()
        kept_final_arcs = []
        for arc_item in final_arcs:
            lay, aci, cx, cy, r, a0, a1 = arc_item
            if "DASH" not in str(lay).upper() and "虚线" not in str(lay).upper():
                kept_final_arcs.append(arc_item)
                continue
            pts_a = sample_arc_points(cx, cy, r, a0, a1, 5)
            matched_crosshair_circle = None
            for chx, chy in crosshairs:
                ds = [math.hypot(px - chx, py - chy) for px, py in pts_a]
                mr = sum(ds) / len(ds)
                if mr <= max(alen_mm * 3.8, 15.0) and max(abs(d - mr) for d in ds) <= max(0.045 * mr, 0.35):
                    m_lids = [
                        l_id for l_id, (l_lay, _, lp0, lp1) in enumerate(merged_cd_lines)
                        if l_id not in absorbed_cd_line_ids and l_lay == lay
                        and math.hypot(lp1[0] - lp0[0], lp1[1] - lp0[1]) <= mr * 1.65
                        and abs(math.hypot(lp0[0] - chx, lp0[1] - chy) - mr) <= max(0.06 * mr, 0.45)
                        and abs(math.hypot(lp1[0] - chx, lp1[1] - chy) - mr) <= max(0.06 * mr, 0.45)
                    ]
                    if len(m_lids) >= 2:
                        matched_crosshair_circle = (chx, chy, mr, m_lids)
                        break
            if matched_crosshair_circle is not None:
                chx, chy, mr, m_lids = matched_crosshair_circle
                for l_id in m_lids:
                    absorbed_cd_line_ids.add(l_id)
                circles_out.append((lay, aci, chx, chy, mr))
            else:
                kept_final_arcs.append(arc_item)
        final_arcs = kept_final_arcs
        merged_cd_lines = [l for idx, l in enumerate(merged_cd_lines) if idx not in absorbed_cd_line_ids]

    # 识别并重构围绕大圆周分布的同心分度圆/螺栓孔中心圆（将离散切向 CENTER 短线段、点划短点与微弧合并为完整原生 CIRCLE）
    large_centers = []
    for _, _, cx, cy, r in circles_out:
        if r >= alen_mm * 2.0 and all(math.hypot(cx - ocx, cy - ocy) > 1.0 for ocx, ocy in large_centers):
            large_centers.append((cx, cy))
    if large_centers and merged_cd_lines:
        bolt_line_ids = set()
        bolt_arc_ids = set()
        for cx, cy in large_centers:
            cand_l = []
            for l_id, (l_lay, l_aci, lp0, lp1) in enumerate(merged_cd_lines):
                if l_id in bolt_line_ids or ('CENTER' not in str(l_lay).upper() and '中心' not in str(l_lay).upper()):
                    continue
                dx_b, dy_b = lp1[0] - lp0[0], lp1[1] - lp0[1]
                llen_b = math.hypot(dx_b, dy_b)
                if llen_b > max(alen_mm * 2.2, 25.0):
                    continue
                r0 = math.hypot(lp0[0] - cx, lp0[1] - cy)
                r1 = math.hypot(lp1[0] - cx, lp1[1] - cy)
                rm = math.hypot(0.5 * (lp0[0] + lp1[0]) - cx, 0.5 * (lp0[1] + lp1[1]) - cy)
                if abs(r0 - r1) <= max(0.04 * alen_mm, 0.45) and rm >= alen_mm * 2.5:
                    rx, ry = (0.5 * (lp0[0] + lp1[0]) - cx) / rm, (0.5 * (lp0[1] + lp1[1]) - cy) / rm
                    dot_r = abs((dx_b * rx + dy_b * ry) / max(llen_b, 1e-4))
                    if llen_b <= max(0.15 * alen_mm, 1.5) or dot_r <= 0.15:
                        cand_l.append((l_id, 0.5 * (r0 + r1), lp0, lp1, l_lay, l_aci))
            if len(cand_l) >= 12:
                med_r = float(np.median([it[1] for it in cand_l]))
                inliers = [it for it in cand_l if abs(it[1] - med_r) <= max(0.1 * alen_mm, 1.2)]
                if len(inliers) >= 12:
                    angs = [
                        math.degrees(math.atan2(0.5 * (it[2][1] + it[3][1]) - cy, 0.5 * (it[2][0] + it[3][0]) - cx)) % 360.0
                        for it in inliers
                    ]
                    angs.sort()
                    max_gap = max(angs[k + 1] - angs[k] for k in range(len(angs) - 1)) if len(angs) > 1 else 360.0
                    max_gap = max(max_gap, (angs[0] + 360.0) - angs[-1])
                    if max_gap <= 135.0:
                        for it in inliers:
                            bolt_line_ids.add(it[0])
                        for a_id, (a_lay, _, acx, acy, ar, _, _) in enumerate(final_arcs):
                            if 'CENTER' in str(a_lay).upper() and math.hypot(acx - cx, acy - cy) + abs(ar - med_r) <= max(alen_mm * 2.5, 30.0):
                                bolt_arc_ids.add(a_id)
                        circles_out.append((inliers[0][4], inliers[0][5], cx, cy, med_r))
        if bolt_line_ids:
            merged_cd_lines = [l for idx, l in enumerate(merged_cd_lines) if idx not in bolt_line_ids]
        if bolt_arc_ids:
            final_arcs = [a for idx, a in enumerate(final_arcs) if idx not in bolt_arc_ids]

    # 利用正交中心线 (CENTER) 十字交点直接聚类纯短弦线段构成的虚线小圆孔（即使无预存圆弧段，如 M5 螺纹盲孔双层虚线圆）
    if crosshairs and merged_cd_lines:
        chord_absorbed_ids = set()
        for chx, chy in crosshairs:
            cands_ch = []
            for l_id, (l_lay, l_aci, lp0, lp1) in enumerate(merged_cd_lines):
                if l_id in chord_absorbed_ids:
                    continue
                lu_c = str(l_lay).upper()
                if "DASH" not in lu_c and "HIDE" not in lu_c and "虚线" not in lu_c:
                    continue
                llen_c = math.hypot(lp1[0] - lp0[0], lp1[1] - lp0[1])
                if not (0.20 <= llen_c <= max(alen_mm * 0.65, 5.0)):
                    continue
                r0 = math.hypot(lp0[0] - chx, lp0[1] - chy)
                r1 = math.hypot(lp1[0] - chx, lp1[1] - chy)
                rm = 0.5 * (r0 + r1)
                if 0.8 <= rm <= max(alen_mm * 3.8, 15.0) and abs(r0 - r1) <= max(0.06 * rm, 0.25) and llen_c <= rm * 1.45:
                    ang_c = math.degrees(math.atan2(0.5 * (lp0[1] + lp1[1]) - chy, 0.5 * (lp0[0] + lp1[0]) - chx)) % 360.0
                    cands_ch.append((l_id, rm, l_lay, l_aci, ang_c))
            if len(cands_ch) >= 4:
                cands_ch.sort(key=lambda x: x[1])
                clusters_r = []
                for item_c in cands_ch:
                    if not clusters_r or abs(item_c[1] - float(np.median([x[1] for x in clusters_r[-1]]))) > 0.28:
                        clusters_r.append([item_c])
                    else:
                        clusters_r[-1].append(item_c)
                for cl_r in clusters_r:
                    if len(cl_r) >= 4:
                        angs_cl = sorted(x[4] for x in cl_r)
                        max_gap_cl = max(
                            max(angs_cl[k + 1] - angs_cl[k] for k in range(len(angs_cl) - 1)),
                            (angs_cl[0] + 360.0) - angs_cl[-1],
                        )
                        if max_gap_cl <= 240.0:
                            mr_cl = float(np.median([x[1] for x in cl_r]))
                            circles_out.append((cl_r[0][2], cl_r[0][3], chx, chy, mr_cl))
                            for x in cl_r:
                                chord_absorbed_ids.add(x[0])
        if chord_absorbed_ids:
            merged_cd_lines = [l for idx, l in enumerate(merged_cd_lines) if idx not in chord_absorbed_ids]

    # 若开放折线的首尾恰好被同图层的一条独立 LINE 闭合（如内图框 TK_CU 的 3 边折线 + 1 条底边直线），自动缝合为闭合 POLYLINE
    used_solid_line_for_poly = set()
    for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(clean_polys):
        if is_cl or len(pts) < 3:
            continue
        p0, p1 = pts[0], pts[-1]
        close_tol = max(0.02 * alen_mm, 0.25)
        for l_idx, (l_lay, _, lp0, lp1) in enumerate(merged_solid_lines):
            if l_idx in used_solid_line_for_poly or l_lay != p_lay:
                continue
            d_a = math.hypot(p0[0] - lp0[0], p0[1] - lp0[1]) + math.hypot(p1[0] - lp1[0], p1[1] - lp1[1])
            d_b = math.hypot(p0[0] - lp1[0], p0[1] - lp1[1]) + math.hypot(p1[0] - lp0[0], p1[1] - lp0[1])
            if min(d_a, d_b) <= close_tol:
                used_solid_line_for_poly.add(l_idx)
                clean_polys[p_idx] = (p_lay, p_aci, pts, True)
                break
    if used_solid_line_for_poly:
        merged_solid_lines = [l for idx, l in enumerate(merged_solid_lines) if idx not in used_solid_line_for_poly]

    # 通用共线共享边界闭合算法：
    # 1. 对 HATCH 图层上的极小 3 点砂砾碎折线自动闭合为微三角形；
    # 2. 对几何/图框层上的开放多边形（如 4 点 U 形槽、倒角法兰、六角螺母头、子环拆分后的外腔室），若其首尾连线 100% 被图纸已有共线边界覆盖，则自动闭合为完整闭合轮廓；
    # 3. 对正交 3 点 L 形折线（如矩形图框/零件外框的其中两边），若其对应矩形的另外两边 100% 被已有共线边界覆盖，则自动补全第 4 角点并闭合为完整矩形 POLYLINE，同时吸收同图层被完全覆盖的冗余单边 LINE。
    all_cov_segs = []
    for l_idx, (l_lay, _, lp0, lp1) in enumerate(merged_solid_lines):
        if "HATCH" not in str(l_lay).upper():
            all_cov_segs.append((lp0, lp1, -1, l_idx, l_lay))
    for p_idx, (p_lay, _, pts, is_cl) in enumerate(clean_polys):
        if "HATCH" not in str(p_lay).upper():
            n_v = len(pts)
            for k_v in range(n_v if is_cl else n_v - 1):
                all_cov_segs.append((pts[k_v], pts[(k_v + 1) % n_v], p_idx, -1, p_lay))

    def check_edge_covered(q0, q1, exclude_p_idx, cov_tol):
        seg_len = math.hypot(q1[0] - q0[0], q1[1] - q0[1])
        if seg_len < 0.25:
            return False, []
        ux, uy = (q1[0] - q0[0]) / seg_len, (q1[1] - q0[1]) / seg_len
        intervals = []
        sub_line_ids = []
        for s0, s1, sp_idx, sl_idx, s_lay in all_cov_segs:
            if sp_idx == exclude_p_idx:
                continue
            slen = math.hypot(s1[0] - s0[0], s1[1] - s0[1])
            if slen < 1e-3:
                continue
            cross = abs((s1[0] - s0[0]) * uy - (s1[1] - s0[1]) * ux) / slen
            if cross > 0.015:
                continue
            perp0 = abs((s0[0] - q0[0]) * (-uy) + (s0[1] - q0[1]) * ux)
            perp1 = abs((s1[0] - q0[0]) * (-uy) + (s1[1] - q0[1]) * ux)
            if max(perp0, perp1) > cov_tol:
                continue
            t0 = (s0[0] - q0[0]) * ux + (s0[1] - q0[1]) * uy
            t1 = (s1[0] - q0[0]) * ux + (s1[1] - q0[1]) * uy
            ta, tb = max(0.0, min(t0, t1)), min(seg_len, max(t0, t1))
            if tb - ta > 1e-2:
                intervals.append((ta, tb))
                if sl_idx >= 0 and min(t0, t1) >= -cov_tol and max(t0, t1) <= seg_len + cov_tol:
                    sub_line_ids.append((sl_idx, s_lay))
        if not intervals:
            return False, []
        intervals.sort()
        merged_iv = [list(intervals[0])]
        for ta, tb in intervals[1:]:
            if ta <= merged_iv[-1][1] + cov_tol * 1.5:
                merged_iv[-1][1] = max(merged_iv[-1][1], tb)
            else:
                merged_iv.append([ta, tb])
        cov_sum = sum(b - a for a, b in merged_iv)
        return (cov_sum >= seg_len * 0.96), sub_line_ids

    cov_tol_mm = max(0.025 * alen_mm, 0.25)
    absorbed_cov_line_ids = set()
    for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(clean_polys):
        if is_cl:
            continue
        lu_p = str(p_lay).upper()
        if "HATCH" in lu_p:
            if len(pts) == 3:
                pxs, pys = [p[0] for p in pts], [p[1] for p in pts]
                if max(max(pxs) - min(pxs), max(pys) - min(pys)) <= max(0.45 * alen_mm, 1.8):
                    clean_polys[p_idx] = (p_lay, p_aci, pts, True)
            continue
        if is_pure_dim_or_text_layer(p_lay) or "DASH" in lu_p or "CENTER" in lu_p:
            continue
        if 4 <= len(pts) <= 12:
            ok_c, sub_l = check_edge_covered(pts[-1], pts[0], p_idx, cov_tol_mm)
            if ok_c:
                clean_polys[p_idx] = (p_lay, p_aci, pts, True)
                for sl_id, sl_lay in sub_l:
                    if sl_lay == p_lay:
                        absorbed_cov_line_ids.add(sl_id)
        elif len(pts) == 3:
            p0, p1, p2 = pts
            v1x, v1y = p0[0] - p1[0], p0[1] - p1[1]
            v2x, v2y = p2[0] - p1[0], p2[1] - p1[1]
            l1_v, l2_v = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
            if l1_v > 0.5 and l2_v > 0.5 and abs(v1x * v2x + v1y * v2y) / (l1_v * l2_v) <= 0.02:
                p3 = (p0[0] + p2[0] - p1[0], p0[1] + p2[1] - p1[1])
                ok1, sub1 = check_edge_covered(p2, p3, p_idx, cov_tol_mm)
                ok2, sub2 = check_edge_covered(p3, p0, p_idx, cov_tol_mm)
                if ok1 and ok2:
                    clean_polys[p_idx] = (p_lay, p_aci, [p0, p1, p2, p3], True)
                    for sl_id, sl_lay in sub1 + sub2:
                        if sl_lay == p_lay:
                            absorbed_cov_line_ids.add(sl_id)
            else:
                ok_c, sub_l = check_edge_covered(pts[-1], pts[0], p_idx, cov_tol_mm)
                if ok_c:
                    clean_polys[p_idx] = (p_lay, p_aci, pts, True)
                    for sl_id, sl_lay in sub_l:
                        if sl_lay == p_lay:
                            absorbed_cov_line_ids.add(sl_id)
    if absorbed_cov_line_ids:
        merged_solid_lines = [l for idx, l in enumerate(merged_solid_lines) if idx not in absorbed_cov_line_ids]

    # 过滤掉所有边均已被闭合多边形 100% 覆盖的冗余开放短折线（如标题栏局部重影折线）
    closed_cov_segs = []
    for p_idx, (p_lay, _, pts, is_cl) in enumerate(clean_polys):
        if is_cl and "HATCH" not in str(p_lay).upper():
            n_v = len(pts)
            for k_v in range(n_v):
                closed_cov_segs.append((pts[k_v], pts[(k_v + 1) % n_v], p_idx, -1, p_lay))
    if closed_cov_segs:
        saved_all_cov = all_cov_segs
        all_cov_segs = closed_cov_segs
        dedup_clean_polys = []
        for p_idx, (p_lay, p_aci, pts, is_cl) in enumerate(clean_polys):
            if not is_cl and 2 <= len(pts) <= 5 and "HATCH" not in str(p_lay).upper() and "DASH" not in str(p_lay).upper():
                if all(check_edge_covered(pts[k_e], pts[k_e + 1], p_idx, cov_tol_mm)[0] for k_e in range(len(pts) - 1)):
                    continue
            dedup_clean_polys.append((p_lay, p_aci, pts, is_cl))
        clean_polys = dedup_clean_polys
        all_cov_segs = saved_all_cov

    circles_out, final_arcs = deduplicate_and_merge_circles_arcs(
        circles_out, final_arcs, pos_tol=max(0.03 * alen_mm, 0.25), r_tol=max(0.025 * alen_mm, 0.22)
    )

    # 过滤掉已拟合成整圆 CIRCLE 或圆弧 ARC 后仍残留在同图层上的冗余短弦 LINE（如滚轮支架 R33.41 虚线圆上的 27 条残留斜弦与设备埋件中心圆弧上的残留短弦）
    if (circles_out or final_arcs) and merged_cd_lines:
        filtered_cd_lines = []
        for l_lay, l_aci, lp0, lp1 in merged_cd_lines:
            llen_q = math.hypot(lp1[0] - lp0[0], lp1[1] - lp0[1])
            lmid_q = (0.5 * (lp0[0] + lp1[0]), 0.5 * (lp0[1] + lp1[1]))
            on_curve = False
            for c_lay, _, cx, cy, cr in circles_out:
                if c_lay == l_lay and llen_q <= cr * 0.95:
                    tol_c = max(0.045 * cr, 0.42)
                    if (
                        abs(math.hypot(lp0[0] - cx, lp0[1] - cy) - cr) <= tol_c
                        and abs(math.hypot(lp1[0] - cx, lp1[1] - cy) - cr) <= tol_c
                        and abs(math.hypot(lmid_q[0] - cx, lmid_q[1] - cy) - cr) <= tol_c
                    ):
                        on_curve = True
                        break
            if not on_curve:
                for a_lay, _, cx, cy, ar, a0, a1 in final_arcs:
                    if a_lay == l_lay and llen_q <= ar * 0.95:
                        tol_a = max(0.045 * ar, 0.42)
                        if (
                            abs(math.hypot(lp0[0] - cx, lp0[1] - cy) - ar) <= tol_a
                            and abs(math.hypot(lp1[0] - cx, lp1[1] - cy) - ar) <= tol_a
                            and abs(math.hypot(lmid_q[0] - cx, lmid_q[1] - cy) - ar) <= tol_a
                        ):
                            ang_m = math.degrees(math.atan2(lmid_q[1] - cy, lmid_q[0] - cx)) % 360.0
                            sweep_a = (a1 - a0) % 360.0
                            rel_a = (ang_m - a0) % 360.0
                            if rel_a <= sweep_a + 12.0 or rel_a >= 360.0 - 12.0:
                                on_curve = True
                                break
            if not on_curve:
                filtered_cd_lines.append((l_lay, l_aci, lp0, lp1))
        merged_cd_lines = filtered_cd_lines

    return regularize_orthogonal_lines(merged_solid_lines + merged_cd_lines), circles_out, final_arcs, clean_polys
