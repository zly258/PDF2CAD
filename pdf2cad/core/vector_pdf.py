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
"""矢量 PDF 解析与重绘主流程：内容流算子、Form XObject、虚线图层推断与多页平铺（参考脚本 §7）。"""
import math
import re

from pypdf import PdfReader

from .annotations import assemble_all_annotations
from .blocks import assemble_annotation_blocks, detect_and_assemble_hatch_regions, deduplicate_and_instantiate_block_references
from .contour import chain_annotation_polylines, reconstruct_dashed_and_center_entities
from .dxf_writer import write_standard_dxf
from .encoding import (
    apply_mat,
    is_title_or_frame_layer,
    mat_mul,
    rgb_to_aci,
    sanitize_layer_name,
)
from .geometry import cubic_bezier, fit_circle_or_arc, merge_split_arrow_subpaths, simplify_collinear_pts
from .raster import convert_pdf_page_via_raster_fallback
from .text_extract import extract_sorted_pdf_texts
from ..ocr.recognizer import UniversalTextRecognizer
from .config import EngineConfig
from ..version import __version__, __copyright__


def _extract_single_pdf_page_entities(pdf_path, reader, page_index: int, cfg: EngineConfig):
    page = reader.pages[page_index]
    rotate = int(page.get('/Rotate') or 0) % 360
    mediabox = [float(v) for v in page.mediabox]
    mb_w, mb_h = mediabox[2] - mediabox[0], mediabox[3] - mediabox[1]

    oc_map = {}
    res = page.get('/Resources', {})
    if hasattr(res, "get_object"):
        res = res.get_object()
    if '/Properties' in res:
        props = res['/Properties'].get_object()
        for k, v in props.items():
            obj = v.get_object()
            if '/Name' in obj:
                oc_map[k] = sanitize_layer_name(obj['/Name'])

    form_xobjects = {}
    if '/XObject' in res:
        try:
            xobjs = res['/XObject'].get_object()
            for xk, xv in xobjs.items():
                xobj = xv.get_object()
                if xobj.get('/Subtype') == '/Form':
                    fmat = tuple(float(v) for v in xobj.get('/Matrix', [1, 0, 0, 1, 0, 0]))
                    fdata = xobj.get_data().decode('latin1', errors='replace')
                    form_xobjects[xk] = (fmat, fdata)
        except Exception:
            pass

    def page_pt_to_upright(x_pt, y_pt):
        if rotate == 90:
            return (y_pt, mb_w - x_pt)
        if rotate == 180:
            return (mb_w - x_pt, mb_h - y_pt)
        if rotate == 270:
            return (mb_h - y_pt, x_pt)
        return (x_pt, y_pt)

    contents = page.get_contents()
    if contents is None:
        return None
    data = contents.get_data().decode('latin1', errors='replace')

    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack = []
    current_layer = "0"
    stroke_rgb = (1.0, 1.0, 1.0)
    fill_rgb = (1.0, 1.0, 1.0)
    dash_ltype = "CONTINUOUS"
    in_bt = False
    last_tf_size = 12.0
    last_tm_info = (0.0, 0.0, 0.0, 12.0)

    all_strokes_pt = []
    solids_pt = []
    bt_records = []
    escaped_slashes = []

    curr_subpath = []
    curr_has_bezier = False
    subpaths = []

    def transform_pt(xr, yr):
        xp, yp = apply_mat(xr, yr, ctm)
        return page_pt_to_upright(xp, yp)

    def effective_layer():
        if current_layer == "0" and dash_ltype in ("DASHED", "CENTER"):
            return dash_ltype
        return current_layer

    def normalize_pdf_stream(s_text):
        # 将同一行内连续排列的多个 PDF 算子拆分为独立行，兼容紧凑型 PDF 生成器
        s_norm = re.sub(
            r'(?<!\S)(m|l|re|c|v|y|h|S|s|f|F|f\*|B|B\*|b|b\*|n|q|Q|cm|BT|ET|Tm|RG|rg|Do)\s+(?=[-\d\[/qQBT])',
            r'\1\n',
            s_text
        )
        return s_norm.splitlines()

    def parse_stream_lines(stream_text):
        nonlocal ctm, current_layer, stroke_rgb, fill_rgb, dash_ltype, in_bt, last_tf_size, last_tm_info
        nonlocal curr_subpath, curr_has_bezier, subpaths

        for raw_line in normalize_pdf_stream(stream_text):
            line = raw_line.strip()
            if not line:
                continue

            op_token = line.split()[0] if line else ''
            if not in_bt and op_token in ('S', 's', 'f', 'F', 'f*', 'b', 'b*', 'B', 'B*'):
                if len(curr_subpath) >= 2:
                    subpaths.append((curr_subpath, op_token in ('s', 'b', 'b*', 'f', 'F', 'f*'), curr_has_bezier))
                curr_subpath = []
                curr_has_bezier = False

                aci = rgb_to_aci(stroke_rgb if op_token in ('S', 's') else fill_rgb)
                eff_lay = effective_layer()
                if op_token in ('f', 'F', 'f*', 'b', 'B', 'b*', 'B*'):
                    subpaths = merge_split_arrow_subpaths(subpaths)

                for sp_pts, is_closed, has_bez in subpaths:
                    if op_token in ('f', 'F', 'f*', 'b', 'b*', 'B', 'B*') and 3 <= len(sp_pts) <= 5:
                        u_pts = sp_pts[:-1] if (len(sp_pts) > 3 and math.hypot(sp_pts[0][0] - sp_pts[-1][0], sp_pts[0][1] - sp_pts[-1][1]) < 1e-4) else sp_pts
                        if 3 <= len(u_pts) <= 4:
                            solids_pt.append((eff_lay, aci, u_pts, len(all_strokes_pt)))
                            continue
                    all_strokes_pt.append({
                        'layer': eff_lay,
                        'aci': aci,
                        'pts': sp_pts,
                        'closed': is_closed,
                        'has_bezier': has_bez,
                    })
                subpaths = []
                m_oc = re.search(r'/OC\s+(/oc\d+)\s+BDC', line)
                if m_oc:
                    current_layer = oc_map.get(m_oc.group(1), "0")
                continue

            m_oc = re.search(r'/OC\s+(/oc\d+)\s+BDC', line)
            if m_oc:
                current_layer = oc_map.get(m_oc.group(1), "0")

            m_do = re.match(r'^(/[^\s]+)\s+Do$', line)
            if m_do and m_do.group(1) in form_xobjects:
                fmat, fdata = form_xobjects[m_do.group(1)]
                saved_state = (ctm, stroke_rgb, fill_rgb, dash_ltype)
                ctm = mat_mul(fmat, ctm)
                parse_stream_lines(fdata)
                ctm, stroke_rgb, fill_rgb, dash_ltype = saved_state
                continue

            m_dash = re.match(r'^\[([^\]]*)\]\s*[\d\.\-]+\s+d$', line)
            if m_dash:
                nums = [float(x) for x in m_dash.group(1).split() if re.match(r'^-?[\d\.]+$', x)]
                if not nums or sum(nums) <= 1e-3:
                    dash_ltype = "CONTINUOUS"
                elif len(nums) >= 4:
                    dash_ltype = "CENTER"
                else:
                    dash_ltype = "DASHED"
                continue

            m_tf = re.search(r'/F\d+\s+([\d\.]+)\s+Tf', line)
            if m_tf:
                last_tf_size = float(m_tf.group(1))

            m_tm = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+Tm$', line)
            if m_tm:
                ta, tb, tc, td, te, tf_val = map(float, m_tm.groups())
                ux, uy = transform_pt(te, tf_val)
                bt_records.append((ux, uy, effective_layer(), len(all_strokes_pt)))
                t_scale = math.hypot(ta, tb) * math.hypot(ctm[0], ctm[1])
                ang = math.degrees(math.atan2(tb, ta))
                if rotate == 270:
                    ang = (ang + 90.0) % 360.0
                if abs(ang) < 1.5 or abs(ang - 360.0) < 1.5:
                    ang = 0.0
                elif abs(ang - 90.0) < 1.5 or abs(ang - 270.0) < 1.5:
                    ang = 90.0
                last_tm_info = (ux, uy, ang, max(last_tf_size * t_scale, 4.0))
                continue

            if line == r'(\/) Tj':
                escaped_slashes.append(last_tm_info)
                continue

            if line == 'BT' or line.startswith('BT '):
                in_bt = True
                continue
            if line == 'ET' or line.startswith('ET '):
                in_bt = False
                continue
            if in_bt:
                continue

            if line == 'q' or line.startswith('q '):
                ctm_stack.append((ctm, stroke_rgb, fill_rgb, dash_ltype))
                continue
            if line == 'Q' or line.startswith('Q '):
                if ctm_stack:
                    ctm, stroke_rgb, fill_rgb, dash_ltype = ctm_stack.pop()
                continue

            m_cm = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+cm$', line)
            if m_cm:
                new_m = tuple(map(float, m_cm.groups()))
                ctm = mat_mul(new_m, ctm)
                continue

            m_rg = re.match(r'^([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+RG', line)
            if m_rg:
                stroke_rgb = tuple(map(float, m_rg.groups()))
                continue
            m_rg2 = re.match(r'^([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+rg', line)
            if m_rg2:
                fill_rgb = tuple(map(float, m_rg2.groups()))
                continue

            if 'W n' in line or 'W* n' in line or line == 'n':
                curr_subpath = []
                curr_has_bezier = False
                subpaths = []
                continue

            m_re = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+re$', line)
            if m_re:
                if len(curr_subpath) >= 2:
                    subpaths.append((curr_subpath, False, curr_has_bezier))
                    curr_subpath = []
                    curr_has_bezier = False
                rx, ry, rw, rh = map(float, m_re.groups())
                r_pts = [
                    transform_pt(rx, ry),
                    transform_pt(rx + rw, ry),
                    transform_pt(rx + rw, ry + rh),
                    transform_pt(rx, ry + rh),
                ]
                subpaths.append((r_pts, True, False))
                continue

            m_m = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+m$', line)
            if m_m:
                if len(curr_subpath) >= 2:
                    subpaths.append((curr_subpath, False, curr_has_bezier))
                curr_subpath = [transform_pt(float(m_m.group(1)), float(m_m.group(2)))]
                curr_has_bezier = False
                continue

            m_l = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+l(?:\s+(h))?$', line)
            if m_l:
                curr_subpath.append(transform_pt(float(m_l.group(1)), float(m_l.group(2))))
                if m_l.group(3) == 'h' and len(curr_subpath) >= 2:
                    subpaths.append((curr_subpath, True, curr_has_bezier))
                    curr_subpath = []
                    curr_has_bezier = False
                continue

            m_c = re.match(
                r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+c(?:\s+(S|s|f|F|b|B))?$',
                line
            )
            if m_c and curr_subpath:
                p0 = curr_subpath[-1]
                p1 = transform_pt(float(m_c.group(1)), float(m_c.group(2)))
                p2 = transform_pt(float(m_c.group(3)), float(m_c.group(4)))
                p3 = transform_pt(float(m_c.group(5)), float(m_c.group(6)))
                curr_subpath.extend(cubic_bezier(p0, p1, p2, p3, steps=12)[1:])
                curr_has_bezier = True
                if m_c.group(7):
                    op2 = m_c.group(7)
                    subpaths.append((curr_subpath, op2 in ('s', 'b', 'f', 'F'), curr_has_bezier))
                    curr_subpath = []
                    curr_has_bezier = False
                    aci = rgb_to_aci(stroke_rgb if op2 in ('S', 's') else fill_rgb)
                    eff_lay = effective_layer()
                    for sp_pts, is_closed, has_bez in subpaths:
                        all_strokes_pt.append({
                            'layer': eff_lay,
                            'aci': aci,
                            'pts': sp_pts,
                            'closed': is_closed,
                            'has_bezier': has_bez,
                        })
                    subpaths = []
                continue

            m_vy = re.match(r'^(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+(-?[\d\.]+)\s+([vy])$', line)
            if m_vy and curr_subpath:
                p0 = curr_subpath[-1]
                pa = transform_pt(float(m_vy.group(1)), float(m_vy.group(2)))
                pb = transform_pt(float(m_vy.group(3)), float(m_vy.group(4)))
                if m_vy.group(5) == 'v':
                    curr_subpath.extend(cubic_bezier(p0, p0, pa, pb, steps=12)[1:])
                else:
                    curr_subpath.extend(cubic_bezier(p0, pa, pb, pb, steps=12)[1:])
                curr_has_bezier = True
                continue

            if line == 'h':
                if len(curr_subpath) >= 2:
                    subpaths.append((curr_subpath, True, curr_has_bezier))
                    curr_subpath = []
                    curr_has_bezier = False
                continue

    parse_stream_lines(data)

    pdf_texts_pt = extract_sorted_pdf_texts(pdf_path, bt_records, escaped_slashes, all_strokes_pt, page_index=page_index)

    # 若当前页为纯扫描件（无矢量笔画且无内嵌文字），返回 None 由上层触发光栅回退
    if len(all_strokes_pt) < 5 and len(pdf_texts_pt) == 0:
        return None

    recognizer = UniversalTextRecognizer(cfg)

    (
        used_stroke_indices,
        used_solid_indices,
        used_pdf_text_indices,
        native_dims_pt,
        standalone_shx_texts,
        single_arrows_pt,
        typical_arrow_len_pt,
        auto_scale,
    ) = assemble_all_annotations(solids_pt, all_strokes_pt, pdf_texts_pt, recognizer)

    scale_from_pt = cfg.user_scale if cfg.user_scale is not None else auto_scale

    raw_lines_out, circles_out, arcs_out, polylines_out = [], [], [], []
    for s_idx, s_info in enumerate(all_strokes_pt):
        if s_idx in used_stroke_indices:
            continue
        layer = s_info['layer']
        aci = s_info['aci']
        sp_pts = [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in s_info['pts']]
        is_closed = s_info['closed']

        if s_info['has_bezier'] or len(sp_pts) >= 5:
            fit_res = fit_circle_or_arc(sp_pts, layer_name=layer, scale_Hint=scale_from_pt)
            if fit_res is not None:
                kind, cx, cy, r, a0, a1 = fit_res
                if kind == 'CIRCLE':
                    circles_out.append((layer, aci, cx, cy, r))
                else:
                    arcs_out.append((layer, aci, cx, cy, r, a0, a1))
                continue

        if not is_closed:
            sp_pts = simplify_collinear_pts(sp_pts, tol=0.015 * scale_from_pt)

        if len(sp_pts) == 2 and not is_closed:
            if math.hypot(sp_pts[0][0] - sp_pts[1][0], sp_pts[0][1] - sp_pts[1][1]) > 1e-4:
                raw_lines_out.append((layer, aci, sp_pts[0], sp_pts[1]))
        elif len(sp_pts) >= 2:
            polylines_out.append((layer, aci, sp_pts, is_closed))

    # 1) 先执行退化闭合共线环还原、中心线十字交点虚线圆孔重构与共线合并，使 DIM/TXT 层上的退化环先还原为 LINE
    raw_lines_out, circles_out, arcs_out, polylines_out = reconstruct_dashed_and_center_entities(
        raw_lines_out, circles_out, arcs_out, polylines_out, typical_arrow_len_pt * scale_from_pt
    )
    # 2) 再串联标注层的引线折线，避免将外形轮廓在线端交点处串联成畸形折线
    lines_out, merged_dim_polys = chain_annotation_polylines(raw_lines_out, tol=0.12 * scale_from_pt)
    polylines_out.extend(merged_dim_polys)

    dimensions_out = []
    for k, d in enumerate(native_dims_pt, start=1):
        sc = scale_from_pt
        tx0, ty0, tx1, ty1 = [v * sc for v in d['text_bbox']]
        if d['text_pos_direct'] is not None:
            t_ins = (d['text_pos_direct'][0] * sc, d['text_pos_direct'][1] * sc)
            h_mm = max(2.0 * sc, d['text_pos_direct'][2] * sc)
            t_mid = t_ins
        else:
            t_ins = (tx0, ty0) if d['is_horiz'] else (tx1, ty0)
            t_mid = (0.5 * (tx0 + tx1), 0.5 * (ty0 + ty1))
            h_mm = max(2.5 * sc, (ty1 - ty0) if d['is_horiz'] else (tx1 - tx0))

        extra_txts_mm = []
        for et in d.get('extra_texts', []):
            extra_txts_mm.append((
                et['text'],
                (et['x'] * sc, et['y'] * sc),
                max(1.5 * sc, et['font_h'] * 0.65 * sc),
                et['angle'],
            ))

        dimensions_out.append({
            'kind': d['kind'],
            'block_name': f"*D{k}",
            'layer': d['layer'],
            'aci': d['aci'],
            't1': (d['t1'][0] * sc, d['t1'][1] * sc),
            't2': (d['t2'][0] * sc, d['t2'][1] * sc),
            'defpoint1': (d['defpoint1'][0] * sc, d['defpoint1'][1] * sc),
            'defpoint2': (d['defpoint2'][0] * sc, d['defpoint2'][1] * sc),
            'text_mid': t_mid,
            'text_ins': t_ins,
            'text_height': h_mm,
            'arrow_len': d['arrow_len_pt'] * sc,
            'text': d['text'],
            'dim_angle_deg': d['dim_angle_deg'],
            'angle_deg': d['angle_deg'],
            'arrow1_pts': [(p[0] * sc, p[1] * sc) for p in d['arrow1_pts']],
            'arrow2_pts': [(p[0] * sc, p[1] * sc) for p in d['arrow2_pts']],
            'dim_lines': [((p0[0] * sc, p0[1] * sc), (p1[0] * sc, p1[1] * sc)) for p0, p1 in d['dim_lines']],
            'ext_lines': [((p0[0] * sc, p0[1] * sc), (p1[0] * sc, p1[1] * sc)) for p0, p1 in d['ext_lines']],
            'arcs': [(cx * sc, cy * sc, r * sc, a0, a1_ang) for cx, cy, r, a0, a1_ang in d.get('arcs', [])],
            'extra_texts': extra_txts_mm,
        })

    texts_out = list(standalone_shx_texts)
    seen_texts = set()
    for t_idx, pt_item in enumerate(pdf_texts_pt):
        if t_idx in used_pdf_text_indices:
            continue
        txt = pt_item['text']
        key = (txt, round(pt_item['x'], 1), round(pt_item['y'], 1))
        if key in seen_texts:
            continue
        seen_texts.add(key)
        x_mm = pt_item['x'] * scale_from_pt
        y_mm = pt_item['y'] * scale_from_pt
        # 标题栏/表格内嵌 TTF 字高按 0.62 校准为 CAD SHX 标准字高，避免溢出单元格
        h_factor = 0.62 if is_title_or_frame_layer(pt_item['layer']) else 0.70
        h_mm = pt_item['font_h'] * scale_from_pt * h_factor
        texts_out.append((pt_item['layer'], pt_item['aci'], txt, x_mm, y_mm, h_mm, pt_item['angle']))

    lines_out, polylines_out, texts_out, sym_blocks_out = assemble_annotation_blocks(
        lines_out, polylines_out, solids_pt, texts_out, single_arrows_pt, used_solid_indices, scale_from_pt, typical_arrow_len_pt,
        circles_out=circles_out, dimensions_out=dimensions_out
    )



    solids_out = [
        (layer, aci, [(p[0] * scale_from_pt, p[1] * scale_from_pt) for p in pts])
        for idx, (layer, aci, pts, _) in enumerate(solids_pt)
        if idx not in used_solid_indices
    ]

    lines_out, polylines_out, solids_out, hatch_blocks = detect_and_assemble_hatch_regions(
        lines_out, polylines_out, solids_out, typical_arrow_len_pt * scale_from_pt
    )
    sym_blocks_out.extend(hatch_blocks)
    sym_blocks_out, _ = deduplicate_and_instantiate_block_references(sym_blocks_out)

    return {
        "oc_layers": list(oc_map.values()),
        "scale_from_pt": scale_from_pt,
        "lines_out": lines_out,
        "circles_out": circles_out,
        "arcs_out": arcs_out,
        "polylines_out": polylines_out,
        "solids_out": solids_out,
        "texts_out": texts_out,
        "dimensions_out": dimensions_out,
        "sym_blocks_out": sym_blocks_out,
        "absorbed": len(used_stroke_indices) + len(used_solid_indices),
    }


def convert_vector_pdf_to_dxf(pdf_path, out_dxf_path, config: EngineConfig = None):
    """支持单页及多页 PDF 自动横向平铺转换（自动为跨页块名编号、自动回退扫描页）。"""
    cfg = config or EngineConfig()
    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)

    all_oc_layers = []
    lines_out, circles_out, arcs_out, polylines_out = [], [], [], []
    solids_out, texts_out, dimensions_out, sym_blocks_out = [], [], [], []
    total_absorbed = 0
    scale_from_pt = cfg.user_scale or 1.0
    offset_x_mm = 0.0

    for p_idx in range(num_pages):
        page_res = _extract_single_pdf_page_entities(pdf_path, reader, p_idx, cfg)
        if page_res is None:
            if num_pages == 1:
                return convert_pdf_page_via_raster_fallback(pdf_path, out_dxf_path, cfg, page_index=0)
            continue

        scale_from_pt = page_res["scale_from_pt"]
        all_oc_layers.extend(page_res["oc_layers"])
        total_absorbed += page_res["absorbed"]

        dx = offset_x_mm
        for lay, aci, p0, p1 in page_res["lines_out"]:
            lines_out.append((lay, aci, (p0[0] + dx, p0[1]), (p1[0] + dx, p1[1])))
        for lay, aci, cx, cy, r in page_res["circles_out"]:
            circles_out.append((lay, aci, cx + dx, cy, r))
        for lay, aci, cx, cy, r, a0, a1 in page_res["arcs_out"]:
            arcs_out.append((lay, aci, cx + dx, cy, r, a0, a1))
        for lay, aci, pts, is_cl in page_res["polylines_out"]:
            polylines_out.append((lay, aci, [(p[0] + dx, p[1]) for p in pts], is_cl))
        for lay, aci, pts in page_res["solids_out"]:
            solids_out.append((lay, aci, [(p[0] + dx, p[1]) for p in pts]))
        for lay, aci, txt, tx, ty, th, tang in page_res["texts_out"]:
            texts_out.append((lay, aci, txt, tx + dx, ty, th, tang))

        for d in page_res["dimensions_out"]:
            d_copy = dict(d)
            d_copy["block_name"] = f"*D{len(dimensions_out) + 1}"
            d_copy["t1"] = (d["t1"][0] + dx, d["t1"][1])
            d_copy["t2"] = (d["t2"][0] + dx, d["t2"][1])
            d_copy["defpoint1"] = (d["defpoint1"][0] + dx, d["defpoint1"][1])
            d_copy["defpoint2"] = (d["defpoint2"][0] + dx, d["defpoint2"][1])
            d_copy["text_mid"] = (d["text_mid"][0] + dx, d["text_mid"][1])
            d_copy["text_ins"] = (d["text_ins"][0] + dx, d["text_ins"][1])
            d_copy["arrow1_pts"] = [(p[0] + dx, p[1]) for p in d["arrow1_pts"]]
            d_copy["arrow2_pts"] = [(p[0] + dx, p[1]) for p in d["arrow2_pts"]]
            d_copy["dim_lines"] = [((p0[0] + dx, p0[1]), (p1[0] + dx, p1[1])) for p0, p1 in d["dim_lines"]]
            d_copy["ext_lines"] = [((p0[0] + dx, p0[1]), (p1[0] + dx, p1[1])) for p0, p1 in d["ext_lines"]]
            d_copy["arcs"] = [(acx + dx, acy, ar, aa0, aa1) for acx, acy, ar, aa0, aa1 in d.get("arcs", [])]
            d_copy["extra_texts"] = [(et_t, (et_p[0] + dx, et_p[1]), et_h, et_a) for et_t, et_p, et_h, et_a in d.get("extra_texts", [])]
            dimensions_out.append(d_copy)

        for sb in page_res["sym_blocks_out"]:
            sb_copy = dict(sb)
            sb_copy["ins_pt"] = (sb["ins_pt"][0] + dx, sb["ins_pt"][1])
            sym_blocks_out.append(sb_copy)

        page_xs = [p[0] for _, _, p0, p1 in lines_out for p in (p0, p1)] + [p[0] for _, _, pts, _ in polylines_out for p in pts]
        if page_xs:
            offset_x_mm = max(page_xs) + 150.0

    if not lines_out and not circles_out and not polylines_out and not texts_out:
        return convert_pdf_page_via_raster_fallback(pdf_path, out_dxf_path, cfg, page_index=0)

    all_layers = sorted(set(
        all_oc_layers
        + [l[0] for l in lines_out]
        + [c[0] for c in circles_out]
        + [a[0] for a in arcs_out]
        + [p[0] for p in polylines_out]
        + [t[0] for t in texts_out]
        + [d["layer"] for d in dimensions_out]
        + [b["layer"] for b in sym_blocks_out]
        + ["0"]
    ))
    sym_blocks_out, unique_blk_defs = deduplicate_and_instantiate_block_references(sym_blocks_out)
    write_standard_dxf(
        out_dxf_path, all_layers, lines_out, circles_out, arcs_out, polylines_out,
        solids_out, texts_out, dimensions_out, sym_blocks_out
    )

    leaders_cnt = sum(1 for sb in sym_blocks_out if sb["block_name"].startswith(("LEADER_MARK", "CALLOUT_MARK", "WELD_MARK")))
    tables_cnt = sum(1 for sb in sym_blocks_out if sb["block_name"].startswith(("TABLE_BLOCK", "TITLE_TABLE")))
    hatches_cnt = sum(1 for sb in sym_blocks_out if sb["block_name"].startswith("HATCH_REGION"))

    return {
        "version": __version__,
        "copyright": __copyright__,
        "mode": "vector_pdf",
        "pages_processed": num_pages,
        "ocr_mode": cfg.ocr_mode,
        "auto_scale_mm_per_pt": round(scale_from_pt, 4),
        "layers": all_layers,
        "native_dimensions_assembled": len(dimensions_out),
        "annotation_blocks_assembled": len(sym_blocks_out),
        "unique_block_definitions": unique_blk_defs,
        "block_insert_references": len(sym_blocks_out),
        "leaders_recognized": leaders_cnt,
        "tables_recognized": tables_cnt,
        "hatch_regions_recognized": hatches_cnt,
        "lines": len(lines_out),
        "circles": len(circles_out),
        "arcs": len(arcs_out),
        "polylines": len(polylines_out),
        "loose_solids_remaining": len(solids_out),
        "standalone_editable_texts": len(texts_out),
        "total_scattered_entities_absorbed": total_absorbed,
    }
