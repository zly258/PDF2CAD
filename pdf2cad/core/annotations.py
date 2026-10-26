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
"""全类型 CAD 标注组装器：线性/对齐/直径标注、角度标注与独立 SHX 文本簇（参考脚本 §5）。"""
import math
import re

import numpy as np

from .encoding import is_pure_dim_or_text_layer, is_annotation_layer, parse_dimension_numeric_value
from .geometry import (
    fit_circle_or_arc,
    is_degenerate_collinear_loop,
    simplify_collinear_pts,
)


# ==============================================================================
# 5. 全类型 CAD 标注（线性/对齐/直径标注、角度标注、独立 SHX 文本）组装器
# ==============================================================================

def is_stroke_arrow_outline(s_pts, arrow):
    if len(s_pts) > 6:
        return False
    tip = arrow['tip']
    ux, uy = arrow['dir']
    nx, ny = -uy, ux
    alen = arrow['length']
    for p in s_pts:
        dx, dy = p[0] - tip[0], p[1] - tip[1]
        proj = -(dx * ux + dy * uy)
        perp = abs(dx * nx + dy * ny)
        if not (-0.25 * alen <= proj <= 1.25 * alen and perp <= 0.65 * alen):
            return False
    return True


def assemble_all_annotations(solids_pt, all_strokes_pt, pdf_texts_pt, recognizer):
    arrows = []
    for idx, (layer, aci, pts, stream_pos) in enumerate(solids_pt):
        unique_pts = []
        for p in pts:
            if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-4 for q in unique_pts):
                unique_pts.append(p)
        if len(unique_pts) != 3:
            continue
        dists = [
            math.hypot(unique_pts[1][0] - unique_pts[2][0], unique_pts[1][1] - unique_pts[2][1]),
            math.hypot(unique_pts[0][0] - unique_pts[2][0], unique_pts[0][1] - unique_pts[2][1]),
            math.hypot(unique_pts[0][0] - unique_pts[1][0], unique_pts[0][1] - unique_pts[1][1]),
        ]
        tip_idx = int(np.argmin(dists))
        base_len = dists[tip_idx]
        side_len = 0.5 * (dists[(tip_idx + 1) % 3] + dists[(tip_idx + 2) % 3])
        if side_len < base_len * 1.3:
            continue
        tip = unique_pts[tip_idx]
        b1, b2 = unique_pts[(tip_idx + 1) % 3], unique_pts[(tip_idx + 2) % 3]
        base_mid = (0.5 * (b1[0] + b2[0]), 0.5 * (b1[1] + b2[1]))
        vx, vy = tip[0] - base_mid[0], tip[1] - base_mid[1]
        vlen = math.hypot(vx, vy)
        if vlen < 1e-4:
            continue
        ux, uy = vx / vlen, vy / vlen
        if abs(ux) < 0.05:
            ux, uy = 0.0, (1.0 if uy > 0 else -1.0)
        elif abs(uy) < 0.05:
            ux, uy = (1.0 if ux > 0 else -1.0), 0.0
        arrows.append({
            'solid_id': idx,
            'stream_pos': stream_pos,
            'layer': layer,
            'aci': aci,
            'tip': tip,
            'base_mid': base_mid,
            'pts': unique_pts,
            'dir': (ux, uy),
            'length': vlen,
        })

    used_stroke_indices = set()
    used_solid_indices = set()
    used_pdf_text_indices = set()

    for a in arrows:
        s0 = max(0, a['stream_pos'] - 4)
        s1 = min(len(all_strokes_pt), a['stream_pos'] + 7)
        for k in range(s0, s1):
            if all_strokes_pt[k]['layer'] == a['layer'] and is_stroke_arrow_outline(all_strokes_pt[k]['pts'], a):
                used_stroke_indices.add(k)

    def dist_to_arrow(pt, a):
        return min(
            math.hypot(pt[0] - a['tip'][0], pt[1] - a['tip'][1]),
            math.hypot(pt[0] - a['base_mid'][0], pt[1] - a['base_mid'][1]),
        )

    def find_connecting_arc(a1, a2):
        if abs(a1['length'] - a2['length']) > 0.25 * a1['length']:
            return None
        s0 = max(0, min(a1['stream_pos'], a2['stream_pos']) - 8)
        s1 = min(len(all_strokes_pt), max(a1['stream_pos'], a2['stream_pos']) + 8)
        alen = 0.5 * (a1['length'] + a2['length'])
        for k in range(s0, s1):
            if k in used_stroke_indices:
                continue
            st = all_strokes_pt[k]
            if len(st['pts']) >= 5 and st['layer'] == a1['layer']:
                res = fit_circle_or_arc(st['pts'], layer_name=st['layer'])
                if res and res[0] == 'ARC':
                    p0, p1 = st['pts'][0], st['pts'][-1]
                    if (dist_to_arrow(p0, a1) <= alen * 1.25 and dist_to_arrow(p1, a2) <= alen * 1.25) or \
                       (dist_to_arrow(p1, a1) <= alen * 1.25 and dist_to_arrow(p0, a2) <= alen * 1.25):
                        return k, res
        return None

    dim_pairs = []
    angular_pairs = []
    single_arrows = []
    i = 0
    while i < len(arrows):
        if i + 1 < len(arrows) and abs(arrows[i + 1]['stream_pos'] - arrows[i]['stream_pos']) <= 6 and arrows[i]['layer'] == arrows[i + 1]['layer']:
            a1, a2 = arrows[i], arrows[i + 1]
            dot = a1['dir'][0] * a2['dir'][0] + a1['dir'][1] * a2['dir'][1]
            dx, dy = a2['tip'][0] - a1['tip'][0], a2['tip'][1] - a1['tip'][1]
            dist = math.hypot(dx, dy)
            perp = abs(dx * a1['dir'][1] - dy * a1['dir'][0])
            if dot <= -0.92 and dist > 1e-3 and perp <= a1['length'] * 0.65 and abs(a1['length'] - a2['length']) <= 0.25 * a1['length']:
                dim_pairs.append((a1, a2))
                i += 2
                continue
            arc_match = find_connecting_arc(a1, a2)
            if arc_match is not None:
                angular_pairs.append((a1, a2, arc_match))
                i += 2
                continue
        single_arrows.append(arrows[i])
        i += 1

    # 全天候兼容非实心箭头：自动从标注层短折线中识别双线开口 V 形箭头或空心闭合三角形箭头（无论图纸中是否同时存在实心箭头）
    for s_idx, s_info in enumerate(all_strokes_pt):
        if s_idx in used_stroke_indices or not is_pure_dim_or_text_layer(s_info['layer']):
            continue
        pts_v = s_info['pts']
        if len(pts_v) == 4 and s_info['closed'] and math.hypot(pts_v[0][0] - pts_v[-1][0], pts_v[0][1] - pts_v[-1][1]) < 1e-3:
            pts_v = pts_v[:-1]
        if len(pts_v) == 3:
            p0, tip, p2 = pts_v
            d1 = math.hypot(p0[0] - tip[0], p0[1] - tip[1])
            d2 = math.hypot(p2[0] - tip[0], p2[1] - tip[1])
            base_d = math.hypot(p0[0] - p2[0], p0[1] - p2[1])
            if 1.8 <= d1 <= 22.0 and abs(d1 - d2) <= 0.22 * max(d1, d2) and 0.22 * d1 <= base_d <= 0.72 * d1:
                bmid = (0.5 * (p0[0] + p2[0]), 0.5 * (p0[1] + p2[1]))
                vx, vy = tip[0] - bmid[0], tip[1] - bmid[1]
                vlen = math.hypot(vx, vy)
                if vlen > 1e-3 and not any(math.hypot(tip[0] - a['tip'][0], tip[1] - a['tip'][1]) <= vlen * 0.8 for a in arrows):
                    ux, uy = vx / vlen, vy / vlen
                    arrows.append({
                        'solid_id': -1 - s_idx,
                        'stream_pos': s_idx,
                        'layer': s_info['layer'],
                        'aci': s_info['aci'],
                        'tip': tip,
                        'base_mid': bmid,
                        'pts': [p0, tip, p2],
                        'dir': (ux, uy),
                        'length': vlen,
                    })
                    used_stroke_indices.add(s_idx)
    if False:
        for s_idx, s_info in enumerate(all_strokes_pt):
            if s_info['closed'] or len(s_info['pts']) != 3:
                continue
            p0, tip, p2 = s_info['pts']
            d1 = math.hypot(p0[0] - tip[0], p0[1] - tip[1])
            d2 = math.hypot(p2[0] - tip[0], p2[1] - tip[1])
            base_d = math.hypot(p0[0] - p2[0], p0[1] - p2[1])
            if 1.5 <= d1 <= 25.0 and abs(d1 - d2) <= 0.25 * max(d1, d2) and 0.25 * d1 <= base_d <= 0.85 * d1:
                bmid = (0.5 * (p0[0] + p2[0]), 0.5 * (p0[1] + p2[1]))
                vx, vy = tip[0] - bmid[0], tip[1] - bmid[1]
                vlen = math.hypot(vx, vy)
                if vlen > 1e-3:
                    ux, uy = vx / vlen, vy / vlen
                    arrows.append({
                        'solid_id': -1 - s_idx,
                        'stream_pos': s_idx,
                        'layer': s_info['layer'],
                        'aci': s_info['aci'],
                        'tip': tip,
                        'base_mid': bmid,
                        'pts': [p0, tip, p2],
                        'dir': (ux, uy),
                        'length': vlen,
                    })

    arrow_lengths = [a['length'] for a in arrows]
    typical_arrow_len = float(np.median(arrow_lengths)) if arrow_lengths else 8.0
    max_char_size = typical_arrow_len * 4.5

    short_strokes = []
    two_pt_lines = []
    long_segments = []

    for s_idx, s_info in enumerate(all_strokes_pt):
        if s_info['has_bezier']:
            continue
        pts = s_info['pts']
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        box_size = max(w, h)
        if not s_info['closed']:
            if len(pts) == 2:
                two_pt_lines.append((s_idx, pts[0], pts[1], box_size, s_info))
            elif 3 <= len(pts) <= 6 and box_size > typical_arrow_len * 0.8:
                simp = simplify_collinear_pts(pts, tol=1e-2)
                if len(simp) == 2:
                    two_pt_lines.append((s_idx, simp[0], simp[1], box_size, s_info))
        elif 3 <= len(pts) <= 6 and box_size > typical_arrow_len * 0.35:
            col_pair = is_degenerate_collinear_loop(pts, tol=max(0.025 * typical_arrow_len, 0.04))
            if col_pair is not None:
                two_pt_lines.append((s_idx, col_pair[0], col_pair[1], box_size, s_info))
        if 0.12 * typical_arrow_len <= box_size <= max_char_size:
            if len(pts) == 2 and box_size > typical_arrow_len * 1.4:
                long_segments.append((s_idx, s_info))
            else:
                short_strokes.append((s_idx, min(xs), min(ys), max(xs), max(ys), s_info))
        elif box_size > max_char_size:
            long_segments.append((s_idx, s_info))

    def stream_dist_to_range(s_idx, s_start, s_end):
        if s_idx < s_start:
            return s_start - s_idx
        if s_idx > s_end:
            return s_idx - s_end
        return 0

    def is_spatially_near_pair(pt_xy, pair_tuple, margin_pt):
        pa1, pa2 = pair_tuple
        pmx = 0.5 * (pa1['tip'][0] + pa2['tip'][0])
        pmy = 0.5 * (pa1['tip'][1] + pa2['tip'][1])
        p_span = math.hypot(pa2['tip'][0] - pa1['tip'][0], pa2['tip'][1] - pa1['tip'][1])
        return math.hypot(pt_xy[0] - pmx, pt_xy[1] - pmy) <= 0.65 * p_span + margin_pt

    assembled_dims_pt = []
    scale_ratios = []

    # A. 组装所有 2-Arrow 线性/对齐/直径尺寸标注
    for p_idx, (a1_orig, a2_orig) in enumerate(dim_pairs):
        stream_start = min(a1_orig['stream_pos'], a2_orig['stream_pos'])
        stream_end = max(a1_orig['stream_pos'], a2_orig['stream_pos'])
        prev_s_start = min(dim_pairs[p_idx - 1][0]['stream_pos'], dim_pairs[p_idx - 1][1]['stream_pos']) if p_idx > 0 else -9999
        prev_s_end = max(dim_pairs[p_idx - 1][0]['stream_pos'], dim_pairs[p_idx - 1][1]['stream_pos']) if p_idx > 0 else -9999
        next_s_start = min(dim_pairs[p_idx + 1][0]['stream_pos'], dim_pairs[p_idx + 1][1]['stream_pos']) if p_idx + 1 < len(dim_pairs) else 999999
        next_s_end = max(dim_pairs[p_idx + 1][0]['stream_pos'], dim_pairs[p_idx + 1][1]['stream_pos']) if p_idx + 1 < len(dim_pairs) else 999999

        a1, a2 = a1_orig, a2_orig
        t1, t2 = a1['tip'], a2['tip']
        if (abs(t2[0] - t1[0]) >= abs(t2[1] - t1[1]) and t1[0] > t2[0]) or \
           (abs(t2[0] - t1[0]) < abs(t2[1] - t1[1]) and t1[1] > t2[1]):
            a1, a2 = a2, a1
            t1, t2 = a1['tip'], a2['tip']

        dist_pt = math.hypot(t2[0] - t1[0], t2[1] - t1[1])
        mx, my = 0.5 * (t1[0] + t2[0]), 0.5 * (t1[1] + t2[1])
        dx, dy = t2[0] - t1[0], t2[1] - t1[1]
        is_horiz = abs(dx) >= abs(dy)
        dim_angle = math.degrees(math.atan2(dy, dx)) % 180.0
        if abs(dim_angle) < 1.5 or abs(dim_angle - 180.0) < 1.5:
            dim_angle = 0.0
        elif abs(dim_angle - 90.0) < 1.5:
            dim_angle = 90.0
        text_angle = 0.0 if is_horiz else 90.0
        ux, uy = dx / dist_pt, dy / dist_pt
        nx, ny = -uy, ux
        alen = 0.5 * (a1['length'] + a2['length'])

        dim_line_segs = []
        ext1_candidates = []
        ext2_candidates = []

        for l_idx, p0, p1, l_len, l_info in two_pt_lines:
            if l_idx in used_stroke_indices or l_len < 1e-3 or l_info['layer'] != a1['layer']:
                continue
            d_curr = stream_dist_to_range(l_idx, stream_start, stream_end)
            if d_curr > 10:
                continue
            l_mid = (0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]))
            d_prev = (
                stream_dist_to_range(l_idx, prev_s_start, prev_s_end)
                if (p_idx > 0 and dim_pairs[p_idx - 1][0]['layer'] == a1['layer']
                    and is_spatially_near_pair(l_mid, dim_pairs[p_idx - 1], alen * 8.0))
                else 999999
            )
            d_next = (
                stream_dist_to_range(l_idx, next_s_start, next_s_end)
                if (p_idx + 1 < len(dim_pairs) and dim_pairs[p_idx + 1][0]['layer'] == a1['layer']
                    and is_spatially_near_pair(l_mid, dim_pairs[p_idx + 1], alen * 8.0))
                else 999999
            )
            if d_curr > d_prev or d_curr >= d_next:
                continue

            vx, vy = (p1[0] - p0[0]) / l_len, (p1[1] - p0[1]) / l_len
            dot_u = abs(vx * ux + vy * uy)

            if dot_u > 0.99:
                perp_dist = abs((p0[0] - t1[0]) * nx + (p0[1] - t1[1]) * ny)
                if perp_dist <= alen * 0.35:
                    proj0 = (p0[0] - t1[0]) * ux + (p0[1] - t1[1]) * uy
                    proj1 = (p1[0] - t1[0]) * ux + (p1[1] - t1[1]) * uy
                    pmin, pmax = min(proj0, proj1), max(proj0, proj1)
                    if pmin >= -alen * 4.5 and pmax <= dist_pt + alen * 4.5:
                        dim_line_segs.append((l_idx, p0, p1))
            elif dot_u < 0.1:
                u_pos = 0.5 * ((p0[0] - t1[0]) * ux + (p0[1] - t1[1]) * uy + (p1[0] - t1[0]) * ux + (p1[1] - t1[1]) * uy)
                n0 = (p0[0] - t1[0]) * nx + (p0[1] - t1[1]) * ny
                n1 = (p1[0] - t1[0]) * nx + (p1[1] - t1[1]) * ny
                nmin, nmax = min(n0, n1), max(n0, n1)
                if nmin - alen * 0.6 <= 0.0 <= nmax + alen * 0.6:
                    if abs(u_pos) <= alen * 0.45:
                        ext1_candidates.append((l_idx, p0, p1, d_curr, abs(u_pos)))
                    elif abs(u_pos - dist_pt) <= alen * 0.45:
                        ext2_candidates.append((l_idx, p0, p1, d_curr, abs(u_pos - dist_pt)))

        ext_segs = []
        defpoint1, defpoint2 = t1, t2
        if ext1_candidates:
            ext1_candidates.sort(key=lambda x: (x[3], x[4]))
            for cand in ext1_candidates:
                ext_segs.append((cand[0], cand[1], cand[2]))
            best_e1 = ext1_candidates[0]
            d_p0 = math.hypot(best_e1[1][0] - t1[0], best_e1[1][1] - t1[1])
            d_p1 = math.hypot(best_e1[2][0] - t1[0], best_e1[2][1] - t1[1])
            defpoint1 = best_e1[1] if d_p0 >= d_p1 else best_e1[2]

        if ext2_candidates:
            ext2_candidates.sort(key=lambda x: (x[3], x[4]))
            for cand in ext2_candidates:
                ext_segs.append((cand[0], cand[1], cand[2]))
            best_e2 = ext2_candidates[0]
            d_p0 = math.hypot(best_e2[1][0] - t2[0], best_e2[1][1] - t2[1])
            d_p1 = math.hypot(best_e2[2][0] - t2[0], best_e2[2][1] - t2[1])
            defpoint2 = best_e2[1] if d_p0 >= d_p1 else best_e2[2]

        extra_shelf_pts = []
        for s_idx in range(max(0, stream_start - 5), min(len(all_strokes_pt), stream_end + 6)):
            if s_idx in used_stroke_indices:
                continue
            st = all_strokes_pt[s_idx]
            if st['layer'] == a1['layer'] and 3 <= len(st['pts']) <= 4:
                pts = st['pts']
                if dist_to_arrow(pts[0], a1) <= alen * 0.5 or dist_to_arrow(pts[0], a2) <= alen * 0.5 or \
                   dist_to_arrow(pts[-1], a1) <= alen * 0.5 or dist_to_arrow(pts[-1], a2) <= alen * 0.5:
                    for k_seg in range(len(pts) - 1):
                        dim_line_segs.append((s_idx, pts[k_seg], pts[k_seg + 1]))
                    extra_shelf_pts.extend(pts)

        for l_idx, _, _ in dim_line_segs:
            used_stroke_indices.add(l_idx)
        for l_idx, _, _ in ext_segs:
            used_stroke_indices.add(l_idx)

        matched_pdf_texts = []
        for t_idx, pt_item in enumerate(pdf_texts_pt):
            if t_idx in used_pdf_text_indices:
                continue
            if pt_item['layer'] != a1['layer'] and not ("DIM" in pt_item['layer'] and "DIM" in a1['layer']):
                continue
            t_spos = pt_item['stream_pos']
            d_curr = stream_dist_to_range(t_spos, stream_start, stream_end)
            if d_curr <= 6:
                tcx, tcy = pt_item['cx'], pt_item['cy']
                d_prev = (
                    stream_dist_to_range(t_spos, prev_s_start, prev_s_end)
                    if (p_idx > 0 and is_spatially_near_pair((tcx, tcy), dim_pairs[p_idx - 1], alen * 6.0))
                    else 999999
                )
                d_next = (
                    stream_dist_to_range(t_spos, next_s_start, next_s_end)
                    if (p_idx + 1 < len(dim_pairs) and is_spatially_near_pair((tcx, tcy), dim_pairs[p_idx + 1], alen * 6.0))
                    else 999999
                )
                if d_curr <= d_prev and d_curr < d_next:
                    along = abs((tcx - mx) * ux + (tcy - my) * uy)
                    perp = abs((tcx - mx) * nx + (tcy - my) * ny)
                    near_extra = any(math.hypot(tcx - ep[0], tcy - ep[1]) <= alen * 6.0 for ep in extra_shelf_pts)
                    angle_ok = abs(pt_item['angle'] - text_angle) <= 15.0 or near_extra or dist_pt <= alen * 3.5
                    if angle_ok and ((along <= 0.75 * dist_pt + alen * 6.0 and perp <= alen * 2.8) or near_extra):
                        matched_pdf_texts.append((t_idx, pt_item))

        txt = ""
        text_bbox = (mx - alen, my + 0.2 * alen, mx + alen, my + 1.2 * alen)
        extra_block_texts = []

        if matched_pdf_texts:
            # 优先选取角度与尺寸线一致且距离尺寸线中点 (mx, my) 最近的文字作为主尺寸文本，仅将同向的上下偏差公差（如 +0.1 / 0 / -0.2）吸纳为附加公差文本，严禁吞噬邻近引线或粗糙度文本
            def dim_text_priority(item):
                _, pt_it = item
                ang_diff = 0 if abs(pt_it['angle'] - text_angle) <= 12.0 else 1
                is_tol_only = 1 if (pt_it['text'].startswith(('+', '-')) or pt_it['text'] == '0') else 0
                not_num_dim = 0 if parse_dimension_numeric_value(pt_it['text']) is not None else 1
                dist_m = math.hypot(pt_it['cx'] - mx, pt_it['cy'] - my)
                return (ang_diff, is_tol_only, not_num_dim, dist_m)

            matched_pdf_texts.sort(key=dim_text_priority)
            main_idx, main_t = matched_pdf_texts[0]
            used_pdf_text_indices.add(main_idx)
            txt = main_t['text']
            text_angle = main_t['angle']
            tx0 = min(main_t['x'], main_t['end_x'])
            ty0 = min(main_t['y'], main_t['end_y'])
            tx1 = max(main_t['x'], main_t['end_x']) + (main_t['font_h'] if abs(text_angle - 90.0) < 10 else 0.0)
            ty1 = max(main_t['y'], main_t['end_y']) + (main_t['font_h'] if abs(text_angle) < 10 else 0.0)
            text_bbox = (tx0, ty0, tx1, ty1)
            for sub_idx, sub_t in matched_pdf_texts[1:]:
                stxt = sub_t['text'].strip()
                if abs(sub_t['angle'] - main_t['angle']) <= 10.0 and sub_t['font_h'] <= main_t['font_h'] * 0.90 and (
                    stxt in ('0', '+0', '-0') or re.match(r'^[+\-]\d+(?:\.\d+)?$', stxt)
                ) and math.hypot(sub_t['cx'] - main_t['cx'], sub_t['cy'] - main_t['cy']) <= main_t['font_h'] * 2.5:
                    used_pdf_text_indices.add(sub_idx)
                    extra_block_texts.append(sub_t)
            for l_idx, p0, p1, l_len, l_info in two_pt_lines:
                if l_idx not in used_stroke_indices and l_info['layer'] == a1['layer']:
                    if stream_dist_to_range(l_idx, stream_start, stream_end) <= 6:
                        if math.hypot(0.5 * (p0[0] + p1[0]) - main_t['cx'], 0.5 * (p0[1] + p1[1]) - main_t['cy']) <= alen * 4.0:
                            dim_line_segs.append((l_idx, p0, p1))
                            used_stroke_indices.add(l_idx)
        else:
            local_multi_pt_strokes = []
            local_two_pt_strokes = []
            for s_idx, sx0, sy0, sx1, sy1, s_info in short_strokes:
                if s_idx in used_stroke_indices or s_info['layer'] != a1['layer']:
                    continue
                d_curr = stream_dist_to_range(s_idx, stream_start, stream_end)
                if d_curr > 14:
                    continue
                scx, scy = 0.5 * (sx0 + sx1), 0.5 * (sy0 + sy1)
                along = abs((scx - mx) * ux + (scy - my) * uy)
                perp = abs((scx - mx) * nx + (scy - my) * ny)
                if along <= 0.75 * dist_pt + alen * 6.0 and perp <= alen * 5.0:
                    if len(s_info['pts']) >= 3:
                        d_prev = (
                            stream_dist_to_range(s_idx, prev_s_start, prev_s_end)
                            if (p_idx > 0 and dim_pairs[p_idx - 1][0]['layer'] == a1['layer']
                                and is_spatially_near_pair((scx, scy), dim_pairs[p_idx - 1], alen * 6.0))
                            else 999999
                        )
                        d_next = (
                            stream_dist_to_range(s_idx, next_s_start, next_s_end)
                            if (p_idx + 1 < len(dim_pairs) and dim_pairs[p_idx + 1][0]['layer'] == a1['layer']
                                and is_spatially_near_pair((scx, scy), dim_pairs[p_idx + 1], alen * 6.0))
                            else 999999
                        )
                        if d_curr <= d_prev and d_curr < d_next:
                            local_multi_pt_strokes.append((s_idx, sx0, sy0, sx1, sy1, s_info))
                    else:
                        local_two_pt_strokes.append((s_idx, sx0, sy0, sx1, sy1, s_info))

            cluster = []
            if local_multi_pt_strokes:
                seed = local_multi_pt_strokes[0]
                cluster = [seed]
                for item in local_multi_pt_strokes[1:]:
                    base_diff = abs(item[2] - seed[2]) if is_horiz else abs(item[1] - seed[1])
                    gap = max(0.0, max(item[1], min(c[1] for c in cluster)) - min(item[3], max(c[3] for c in cluster))) if is_horiz else \
                          max(0.0, max(item[2], min(c[2] for c in cluster)) - min(item[4], max(c[4] for c in cluster)))
                    if base_diff <= alen * 0.55 and gap <= alen * 1.6:
                        cluster.append(item)

                c_x0, c_y0 = min(c[1] for c in cluster), min(c[2] for c in cluster)
                c_x1, c_y1 = max(c[3] for c in cluster), max(c[4] for c in cluster)
                c_h = (c_y1 - c_y0) if is_horiz else (c_x1 - c_x0)
                for item in local_two_pt_strokes:
                    iw, ih = item[3] - item[1], item[4] - item[2]
                    if max(iw, ih) <= max(c_h * 1.65, alen * 1.5):
                        if is_horiz and abs(0.5 * (item[2] + item[4]) - 0.5 * (c_y0 + c_y1)) <= c_h * 0.6 and \
                           (c_x0 - c_h * 0.8 <= 0.5 * (item[1] + item[3]) <= c_x1 + c_h * 1.65):
                            cluster.append(item)
                        elif not is_horiz and abs(0.5 * (item[1] + item[3]) - 0.5 * (c_x0 + c_x1)) <= c_h * 0.6 and \
                             (c_y0 - c_h * 0.8 <= 0.5 * (item[2] + item[4]) <= c_y1 + c_h * 1.65):
                            cluster.append(item)

            if cluster:
                for c in cluster:
                    used_stroke_indices.add(c[0])
                text_bbox = (
                    min(c[1] for c in cluster),
                    min(c[2] for c in cluster),
                    max(c[3] for c in cluster),
                    max(c[4] for c in cluster),
                )
                strokes_pt = [c[5]['pts'] for c in cluster]
                txt = recognizer.recognize_cluster(strokes_pt, angle_deg=text_angle)

        used_solid_indices.add(a1['solid_id'])
        used_solid_indices.add(a2['solid_id'])

        num_val = parse_dimension_numeric_value(txt)
        if num_val is not None and dist_pt > 1e-2:
            scale_ratios.append(num_val / dist_pt)

        assembled_dims_pt.append({
            'kind': 'LINEAR',
            'layer': a1['layer'],
            'aci': a1['aci'],
            't1': t1,
            't2': t2,
            'defpoint1': defpoint1,
            'defpoint2': defpoint2,
            'arrow1_pts': a1['pts'],
            'arrow2_pts': a2['pts'],
            'dim_lines': [(p0, p1) for _, p0, p1 in dim_line_segs] or [(t1, t2)],
            'ext_lines': [(p0, p1) for _, p0, p1 in ext_segs],
            'arcs': [],
            'text': txt,
            'text_bbox': text_bbox,
            'text_pos_direct': (main_t['x'], main_t['y'], main_t['font_h'] * 0.65) if matched_pdf_texts else None,
            'extra_texts': extra_block_texts,
            'is_horiz': is_horiz,
            'dim_angle_deg': dim_angle,
            'angle_deg': text_angle,
            'dist_pt': dist_pt,
            'arrow_len_pt': alen,
        })

    # B. 组装所有 2-Arrow 角度尺寸标注
    for a1, a2, (arc_s_idx, arc_fit) in angular_pairs:
        used_solid_indices.add(a1['solid_id'])
        used_solid_indices.add(a2['solid_id'])
        used_stroke_indices.add(arc_s_idx)
        _, cx, cy, r, ang0, ang1 = arc_fit
        s_start = min(a1['stream_pos'], a2['stream_pos'])
        s_end = max(a1['stream_pos'], a2['stream_pos'])
        alen = 0.5 * (a1['length'] + a2['length'])

        rad_ext_lines = []
        for l_idx, p0, p1, l_len, l_info in two_pt_lines:
            if l_idx in used_stroke_indices or l_info['layer'] != a1['layer']:
                continue
            if max(0, s_start - 8) <= l_idx <= s_end + 8:
                if l_len > 1e-3:
                    vx, vy = (p1[0] - p0[0]) / l_len, (p1[1] - p0[1]) / l_len
                    perp_c = abs((cx - p0[0]) * (-vy) + (cy - p0[1]) * vx)
                    if perp_c <= alen * 0.6 and (dist_to_arrow(p0, a1) <= alen * 3.0 or dist_to_arrow(p1, a1) <= alen * 3.0 or
                                                 dist_to_arrow(p0, a2) <= alen * 3.0 or dist_to_arrow(p1, a2) <= alen * 3.0):
                        rad_ext_lines.append((p0, p1))
                        used_stroke_indices.add(l_idx)

        ang_txt = ""
        ang_pos = None
        ang_angle = 0.0
        mx, my = 0.5 * (a1['tip'][0] + a2['tip'][0]), 0.5 * (a1['tip'][1] + a2['tip'][1])
        for t_idx, pt_item in enumerate(pdf_texts_pt):
            if t_idx in used_pdf_text_indices:
                continue
            if stream_dist_to_range(pt_item['stream_pos'], s_start, s_end) <= 6:
                if math.hypot(pt_item['cx'] - mx, pt_item['cy'] - my) <= r * 1.5 + alen * 4.0:
                    used_pdf_text_indices.add(t_idx)
                    ang_txt = pt_item['text']
                    ang_pos = (pt_item['x'], pt_item['y'], pt_item['font_h'] * 0.65)
                    ang_angle = pt_item['angle']
                    break

        assembled_dims_pt.append({
            'kind': 'ANGULAR',
            'layer': a1['layer'],
            'aci': a1['aci'],
            't1': a1['tip'],
            't2': a2['tip'],
            'defpoint1': a1['tip'],
            'defpoint2': a2['tip'],
            'arrow1_pts': a1['pts'],
            'arrow2_pts': a2['pts'],
            'dim_lines': [],
            'ext_lines': rad_ext_lines,
            'arcs': [(cx, cy, r, ang0, ang1)],
            'text': ang_txt,
            'text_bbox': (mx - alen, my - alen, mx + alen, my + alen),
            'text_pos_direct': ang_pos,
            'extra_texts': [],
            'is_horiz': True,
            'dim_angle_deg': 0.0,
            'angle_deg': ang_angle,
            'dist_pt': r,
            'arrow_len_pt': alen,
        })

    auto_scale = float(np.median(scale_ratios)) if len(scale_ratios) >= 3 else (25.4 / 72.0)

    native_dimensions = []
    for d in assembled_dims_pt:
        if d['kind'] == 'LINEAR' and d['text_pos_direct'] is None:
            txt = d['text']
            dist_mm = d['dist_pt'] * auto_scale
            if txt and txt.isdigit() and len(scale_ratios) >= 3:
                val = int(txt)
                if abs(val - dist_mm) > max(8.0, 0.03 * dist_mm):
                    alt = txt.replace('6', '9') if val < dist_mm else txt.replace('9', '6')
                    if alt.isdigit() and abs(int(alt) - dist_mm) <= max(8.0, 0.03 * dist_mm):
                        txt = alt
                    else:
                        txt = str(int(round(dist_mm / 5.0) * 5)) if dist_mm >= 100 else str(int(round(dist_mm)))
            elif not txt and len(scale_ratios) >= 3:
                txt = str(int(round(dist_mm / 5.0) * 5)) if dist_mm >= 100 else str(int(round(dist_mm)))
            d['text'] = txt
        native_dimensions.append(d)

    # C. 识别独立 SHX 矢量文本簇（严格过滤图形轮廓层 DRAW-IN / HATCH-IN，防止将机械倒角或剖面线误判为文字）
    horiz_shelves = []
    for s_idx, seg in long_segments:
        pts = seg['pts']
        for k_seg in range(len(pts) - 1):
            p1, p2 = pts[k_seg], pts[k_seg + 1]
            if abs(p1[1] - p2[1]) < 2.0 and abs(p2[0] - p1[0]) > typical_arrow_len * 2.2:
                horiz_shelves.append((s_idx, min(p1[0], p2[0]), max(p1[0], p2[0]), 0.5 * (p1[1] + p2[1])))

    rem_strokes = [
        item for item in short_strokes
        if item[0] not in used_stroke_indices
        and is_annotation_layer(item[5]['layer'])
    ]
    line_clusters = [[it[1], it[2], it[3], it[4], [it]] for it in rem_strokes]
    merged = True
    while merged:
        merged = False
        new_clusters = []
        u_flags = [False] * len(line_clusters)
        for i in range(len(line_clusters)):
            if u_flags[i]:
                continue
            c1 = line_clusters[i]
            for j in range(i + 1, len(line_clusters)):
                if u_flags[j]:
                    continue
                c2 = line_clusters[j]
                if c1[4][0][5]['layer'] != c2[4][0][5]['layer']:
                    continue
                dx_gap = max(0.0, max(c1[0], c2[0]) - min(c1[2], c2[2]))
                dy_gap = max(0.0, max(c1[1], c2[1]) - min(c1[3], c2[3]))
                if dx_gap < typical_arrow_len * 1.5 and dy_gap < typical_arrow_len * 0.55:
                    c1[0] = min(c1[0], c2[0])
                    c1[1] = min(c1[1], c2[1])
                    c1[2] = max(c1[2], c2[2])
                    c1[3] = max(c1[3], c2[3])
                    c1[4].extend(c2[4])
                    u_flags[j] = True
                    merged = True
            new_clusters.append(c1)
        line_clusters = new_clusters

    standalone_shx_texts = []
    for cx0, cy0, cx1, cy1, items in line_clusters:
        if len(items) < 4:
            continue
        multi_vert_cnt = sum(1 for it in items if len(it[5]['pts']) >= 3)
        if multi_vert_cnt < 3:
            continue
        cw, ch = cx1 - cx0, cy1 - cy0
        near_shelf = any(
            (sx0 - typical_arrow_len <= cx0 and cx1 <= sx1 + typical_arrow_len * 3.0 and -typical_arrow_len * 0.5 <= (cy0 - sy) <= typical_arrow_len * 1.8)
            for _, sx0, sx1, sy in horiz_shelves
        )
        strokes_pt = [it[5]['pts'] for it in sorted(items, key=lambda x: x[1])]
        is_vert = ch > cw * 1.8
        ang = 90.0 if is_vert else 0.0
        _, rot_s = recognizer.render_strokes_to_pil(strokes_pt, angle_deg=ang)
        topo_str, unk_cnt, char_boxes = recognizer.segment_and_decode_upright_strokes(rot_s, allow_cjk_fallback=True)

        if (unk_cnt == 0 and len(topo_str) >= 3) or near_shelf:
            full_txt = recognizer.recognize_cluster(strokes_pt, angle_deg=ang)
            if not full_txt and unk_cnt == 0:
                full_txt = topo_str
            if full_txt:
                for it in items:
                    used_stroke_indices.add(it[0])
                ins_x = (cx1 if is_vert else cx0) * auto_scale
                ins_y = cy0 * auto_scale
                h_mm = (cw if is_vert else ch) * auto_scale * (0.72 if not is_vert and len(char_boxes) >= 4 else 1.0)
                standalone_shx_texts.append((items[0][5]['layer'], items[0][5]['aci'], full_txt, ins_x, ins_y, h_mm, ang))

    return used_stroke_indices, used_solid_indices, used_pdf_text_indices, native_dimensions, standalone_shx_texts, single_arrows, typical_arrow_len, auto_scale
