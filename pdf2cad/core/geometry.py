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
"""曲线采样、折线简化、高精度圆/圆弧/圆角拟合与中心线/虚线点云重构引擎（参考脚本 §2）。"""
import math

import numpy as np

from .encoding import is_pure_dim_or_text_layer


# ==============================================================================
# 2. 曲线采样、折线简化、高精度圆/圆弧/圆角拟合与中心线/虚线点云重构引擎
# ==============================================================================

def cubic_bezier(p0, p1, p2, p3, steps=12):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def is_degenerate_collinear_loop(pts, tol=1e-2):
    """检测因 PDF `m ... l h S` 闭合指令产生的零面积共线往返线段，若共线则返回其两端极值点 `(p_start, p_end)`。"""
    if len(pts) < 2:
        return None
    p_start, p_end = pts[0], pts[-1]
    max_d = -1.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
            if d > max_d:
                max_d = d
                p_start, p_end = pts[i], pts[j]
    if max_d < 1e-4:
        return None
    ux, uy = (p_end[0] - p_start[0]) / max_d, (p_end[1] - p_start[1]) / max_d
    if all(abs((p[0] - p_start[0]) * (-uy) + (p[1] - p_start[1]) * ux) <= tol for p in pts):
        return (p_start, p_end)
    return None


def simplify_collinear_pts(pts, tol=1e-2):
    """消去折线中的共线冗余中间顶点；若整条路径共线则直接还原为 2 点直线段。"""
    if len(pts) <= 2:
        return pts
    col_pair = is_degenerate_collinear_loop(pts, tol=tol)
    if col_pair is not None:
        return [col_pair[0], col_pair[1]]

    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-4:
            out.append(p)
    fold_tol = max(tol * 2.0, 0.05)
    while len(out) >= 3 and math.hypot(out[0][0] - out[2][0], out[0][1] - out[2][1]) <= fold_tol:
        out.pop(0)
    while len(out) >= 3 and math.hypot(out[-1][0] - out[-3][0], out[-1][1] - out[-3][1]) <= fold_tol:
        out.pop()
    if len(out) <= 2:
        return out
    res = [out[0]]
    for k in range(1, len(out) - 1):
        p0, p1, p2 = res[-1], out[k], out[k + 1]
        d02 = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
        if d02 > 1e-4:
            perp = abs((p1[0] - p0[0]) * (-(p2[1] - p0[1]) / d02) + (p1[1] - p0[1]) * ((p2[0] - p0[0]) / d02))
            dot = (p1[0] - p0[0]) * (p2[0] - p1[0]) + (p1[1] - p0[1]) * (p2[1] - p1[1])
            if perp <= tol and dot >= -1e-4:
                continue
        res.append(p1)
    res.append(out[-1])
    return res


def fit_quarter_fillet_arc(pts, max_radius=3.5):
    """
    针对机械零件 90° 倒圆角/退刀槽小圆弧（如 R0.5、R2.5，因 PDF 坐标整数量化而仅有 5~12 个阶梯点）：
    直接根据首尾正交切点解析重构精确的 90° 原生 ARC。
    """
    if not (5 <= len(pts) <= 12):
        return None
    p0, p1 = pts[0], pts[-1]
    dx = abs(p1[0] - p0[0])
    dy = abs(p1[1] - p0[1])
    r = 0.5 * (dx + dy)
    if r < 0.15 or r > max_radius:
        return None
    if abs(dx - dy) > 0.18 * r:
        return None
    x_min, x_max = min(p0[0], p1[0]), max(p0[0], p1[0])
    y_min, y_max = min(p0[1], p1[1]), max(p0[1], p1[1])
    if any(p[0] < x_min - 0.05 * r or p[0] > x_max + 0.05 * r or p[1] < y_min - 0.05 * r or p[1] > y_max + 0.05 * r for p in pts):
        return None

    cands = [(p0[0], p1[1]), (p1[0], p0[1])]
    best_c = None
    best_err = float('inf')
    for cx, cy in cands:
        dists = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
        max_dev = max(abs(d - r) for d in dists)
        mean_d = sum(dists) / len(dists)
        if abs(mean_d - r) <= 0.18 * r and max_dev <= max(0.28 * r, 0.12):
            if max_dev < best_err:
                best_err = max_dev
                best_c = (cx, cy)

    if best_c is None:
        return None
    cx, cy = best_c
    ang0 = math.degrees(math.atan2(p0[1] - cy, p0[0] - cx)) % 360.0
    ang1 = math.degrees(math.atan2(p1[1] - cy, p1[0] - cx)) % 360.0
    if (ang1 - ang0) % 360.0 <= 180.0:
        return ('ARC', cx, cy, r, ang0, ang1)
    return ('ARC', cx, cy, r, ang1, ang0)


def fit_circle_or_arc(pts, rel_tol=0.022, layer_name="", scale_Hint=1.0, is_closed_hint=False):
    """
    代数最小二乘圆/圆弧拟合 (含曲率单调性检验与波浪断裂线防误判)：
    - 对闭合圆环（含大比例尺下的小直径锚栓圆孔）放宽整数量化绝对容差以恢复原生 CIRCLE；
    - 对非闭合圆弧严格检验径向残差与弦转角单调性，禁止将 HATCH 层的波浪断裂线误拟合为圆弧。
    """
    lu = str(layer_name).upper()
    if "HATCH" in lu or "剖面" in lu:
        return None
    if len(pts) < 5:
        return None
    arr = np.array(pts, dtype=float)
    x, y = arr[:, 0], arr[:, 1]
    w_box, h_box = float(np.ptp(x)), float(np.ptp(y))
    span = max(w_box, h_box)
    if span < 1e-4:
        return None

    end_gap = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
    is_closed_loop = bool(is_closed_hint) or (end_gap < max(0.15 * span, 1e-2))

    mx, my = np.mean(x), np.mean(y)
    u, v = x - mx, y - my
    A = np.column_stack([u, v, np.ones_like(u)])
    b = -(u**2 + v**2)
    try:
        sol, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    except Exception:
        return None
    D, E, F = sol
    uc, vc = -D / 2.0, -E / 2.0
    r_sq = uc**2 + vc**2 - F
    if r_sq <= 1e-6:
        return None
    r = math.sqrt(r_sq)
    if r > span * 30.0 or r < 1e-3:
        return None
    cx, cy = uc + mx, vc + my
    dists = np.hypot(x - cx, y - cy)
    max_rad_err = float(np.max(np.abs(dists - r)))

    min_closed_pts = 8 if (is_pure_dim_or_text_layer(layer_name) or r <= 2.5 * scale_Hint) else 12
    if is_closed_loop and len(pts) < min_closed_pts:
        return None
    if is_closed_loop and len(pts) >= min_closed_pts and 0.82 <= (w_box / max(h_box, 1e-4)) <= 1.22:
        # 闭合正多边形圆：允许 PDF 整数/一位小数量化误差 (含 1:100 图纸中的小锚栓圆孔)
        allowed_err = max(rel_tol * r, 0.16 * r if r <= 2.2 * scale_Hint else (0.115 * r if r < 25.0 * scale_Hint else 0.035 * r))
    else:
        allowed_err = rel_tol * r

    if max_rad_err > allowed_err:
        if not is_closed_loop:
            q_arc = fit_quarter_fillet_arc(pts, max_radius=4.5 * max(scale_Hint, 1.0))
            if q_arc is not None:
                return q_arc
            # 针对小跨度浅圆弧/相贯线圆弧（5..20 点，绝对径向残差 <= 0.15 * scale_Hint）放宽拟合
            if 5 <= len(pts) <= 20 and span <= 14.0 * max(scale_Hint, 1.0) and max_rad_err <= 0.16 * max(scale_Hint, 1.0):
                pass
            else:
                return None
        else:
            return None

    if len(pts) >= 6:
        diffs = np.diff(arr, axis=0)
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        valid_segs = seg_lens > 1e-4
        if np.sum(valid_segs) < 4:
            return None
        if np.max(seg_lens) > r * 1.25:
            return None

    angles = np.degrees(np.arctan2(y - cy, x - cx)) % 360.0
    if is_closed_loop and np.ptp(angles) > 235.0:
        return ('CIRCLE', cx, cy, r, 0.0, 360.0)

    # 非闭合圆弧：检查极角推进是否单调（防止波浪断裂线/相贯线被误拟合为圆弧）
    unwrapped = np.unwrap(np.arctan2(y - cy, x - cx))
    d_ang = np.diff(unwrapped)
    active_d = d_ang[np.abs(d_ang) > 1e-3]
    if len(active_d) >= 3:
        pos_ratio = float(np.sum(active_d > 0)) / len(active_d)
        if 0.12 < pos_ratio < 0.88:
            return None
    total_sweep_deg = abs(math.degrees(float(unwrapped[-1] - unwrapped[0])))
    if total_sweep_deg < (6.0 if 5 <= len(pts) <= 15 else 12.0) or total_sweep_deg > 350.0:
        return None

    ang0 = math.degrees(math.atan2(pts[0][1] - cy, pts[0][0] - cx)) % 360.0
    ang1 = math.degrees(math.atan2(pts[-1][1] - cy, pts[-1][0] - cx)) % 360.0
    mid = pts[len(pts) // 2]
    angm = math.degrees(math.atan2(mid[1] - cy, mid[0] - cx)) % 360.0

    def ccw_dist(a_start, a_end):
        return (a_end - a_start) % 360.0

    if ccw_dist(ang0, angm) < ccw_dist(ang0, ang1):
        return ('ARC', cx, cy, r, ang0, ang1)
    return ('ARC', cx, cy, r, ang1, ang0)


def merge_split_arrow_subpaths(subpaths):
    """合并被 CAD 驱动拆成左右两个直角三角形子路径的实心箭头。"""
    out = []
    i = 0
    while i < len(subpaths):
        if i + 1 < len(subpaths):
            pts1, c1, b1 = subpaths[i]
            pts2, c2, b2 = subpaths[i + 1]
            u1 = []
            for p in pts1:
                if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-3 for q in u1):
                    u1.append(p)
            u2 = []
            for p in pts2:
                if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-3 for q in u2):
                    u2.append(p)
            if len(u1) == 3 and len(u2) == 3:
                shared = [p for p in u1 if any(math.hypot(p[0] - q[0], p[1] - q[1]) <= 1e-2 for q in u2)]
                only1 = [p for p in u1 if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-2 for q in u2)]
                only2 = [p for p in u2 if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-2 for q in u1)]
                if len(shared) == 2 and len(only1) == 1 and len(only2) == 1:
                    mid_o = (0.5 * (only1[0][0] + only2[0][0]), 0.5 * (only1[0][1] + only2[0][1]))
                    d0 = math.hypot(shared[0][0] - mid_o[0], shared[0][1] - mid_o[1])
                    d1 = math.hypot(shared[1][0] - mid_o[0], shared[1][1] - mid_o[1])
                    tip = shared[1] if d0 < d1 else shared[0]
                    out.append(([only1[0], tip, only2[0]], True, False))
                    i += 2
                    continue
        out.append(subpaths[i])
        i += 1
    return out
