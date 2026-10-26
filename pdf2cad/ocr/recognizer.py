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
"""极简三选一 OCR 识别器：RapidOCR / 百度 PaddleOCR / 第三方 LLM，含 SHX 字形几何拓扑解析（参考脚本 §3）。"""
import base64
import io
import json
import math
import urllib.request

import cv2
import numpy as np
from PIL import Image

from ..core.config import EngineConfig

HAS_PADDLE = True


# ==============================================================================
# 3. 极简三选一 OCR 识别器（RapidOCR / 百度 PaddleOCR 2.x&3.x / 第三方 LLM）
# ==============================================================================

class UniversalTextRecognizer:
    """支持 RapidOCR、百度 PaddleOCR (2.x/3.x) + 几何拓扑引擎，或接入第三方视觉大模型 LLM API。"""

    _shared_rapid_ocr = None
    _rapid_init_attempted = False
    _shared_paddle_ocr = None
    _paddle_init_attempted = False

    def __init__(self, config: EngineConfig = None):
        self.cfg = config or EngineConfig()

    def get_rapid_ocr(self):
        """按需延迟加载并全局共享 RapidOCR 实例（基于 ONNXRuntime，轻量极速）。"""
        if UniversalTextRecognizer._shared_rapid_ocr is None and not UniversalTextRecognizer._rapid_init_attempted:
            UniversalTextRecognizer._rapid_init_attempted = True
            for mod_name in ("rapidocr_onnxruntime", "rapidocr"):
                try:
                    mod = __import__(mod_name, fromlist=["RapidOCR"])
                    UniversalTextRecognizer._shared_rapid_ocr = mod.RapidOCR()
                    break
                except Exception:
                    continue
        return UniversalTextRecognizer._shared_rapid_ocr

    def get_paddle_ocr(self):
        """按需延迟加载并全局共享百度 PaddleOCR 实例，避免纯矢量/标准 SHX 图纸启动卡顿。"""
        if not HAS_PADDLE:
            return None
        if UniversalTextRecognizer._shared_paddle_ocr is None and not UniversalTextRecognizer._paddle_init_attempted:
            UniversalTextRecognizer._paddle_init_attempted = True
            try:
                from paddleocr import PaddleOCR
                for kwargs in (
                    {"use_angle_cls": True, "lang": "ch", "show_log": False},
                    {"use_angle_cls": True, "lang": "ch"},
                    {"lang": "ch"},
                ):
                    try:
                        UniversalTextRecognizer._shared_paddle_ocr = PaddleOCR(**kwargs)
                        break
                    except Exception:
                        continue
            except Exception:
                pass
        return UniversalTextRecognizer._shared_paddle_ocr

    @staticmethod
    def rotate_pts(pts, center, angle_rad):
        cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
        cx, cy = center
        return [
            (cx + (x - cx) * cos_a - (y - cy) * sin_a, cy + (x - cx) * sin_a + (y - cy) * cos_a)
            for x, y in pts
        ]

    def render_strokes_to_pil(self, strokes_pt, angle_deg=0.0, target_height=80):
        all_pts = [p for s in strokes_pt for p in s]
        cx = 0.5 * (min(p[0] for p in all_pts) + max(p[0] for p in all_pts))
        cy = 0.5 * (min(p[1] for p in all_pts) + max(p[1] for p in all_pts))

        rad = -math.radians(angle_deg)
        rot_strokes = [self.rotate_pts(s, (cx, cy), rad) for s in strokes_pt]
        r_pts = [p for s in rot_strokes for p in s]

        x0, y0 = min(p[0] for p in r_pts), min(p[1] for p in r_pts)
        x1, y1 = max(p[0] for p in r_pts), max(p[1] for p in r_pts)
        w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)

        scale = target_height / h
        pad = 20
        img_w = max(48, int(math.ceil(w * scale)) + 2 * pad)
        img_h = target_height + 2 * pad

        canvas = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
        stroke_w = max(2, int(round(target_height / 18.0)))

        for s in rot_strokes:
            if len(s) >= 2:
                pix_pts = np.array([
                    [int(round(pad + (p[0] - x0) * scale)), int(round(img_h - pad - (p[1] - y0) * scale))]
                    for p in s
                ], dtype=np.int32)
                cv2.polylines(canvas, [pix_pts], isClosed=False, color=(0, 0, 0), thickness=stroke_w, lineType=cv2.LINE_AA)

        img = Image.fromarray(canvas)
        return img, rot_strokes

    @staticmethod
    def is_standalone_ascii_stroke(stroke, total_h):
        n = len(stroke)
        if n not in (3, 4, 5, 11, 12, 13, 14, 15, 17, 23, 29):
            return False
        xs = [p[0] for p in stroke]
        ys = [p[1] for p in stroke]
        h = max(ys) - min(ys)
        w = max(xs) - min(xs)
        return (h >= 0.52 * total_h) and (w <= 0.88 * total_h)

    def classify_single_shx_glyph_topology(self, glyph_strokes, allow_cjk_fallback=False):
        pts = [p for s in glyph_strokes for p in s]
        if len(pts) < 2:
            return ""
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
        w, h = x1 - x0, y1 - y0
        aspect = w / max(h, 1e-4)
        n_strokes = len(glyph_strokes)
        n_verts = len(pts)

        if n_strokes == 3 and all(len(s) == 2 for s in glyph_strokes):
            return "*"
        if n_strokes == 2:
            lens = sorted(len(s) for s in glyph_strokes)
            if lens == [2, 2]:
                return "+"
            if lens == [2, 3]:
                return "A"
            if lens[0] == 2 and lens[1] >= 10:
                s_line = [s for s in glyph_strokes if len(s) == 2][0]
                lx_mean = 0.5 * (s_line[0][0] + s_line[1][0])
                return "d" if lx_mean > x0 + 0.72 * w else "Ø"

        if n_strokes == 1:
            s = glyph_strokes[0]
            n = len(s)
            end_dist = math.hypot(s[0][0] - s[-1][0], s[0][1] - s[-1][1]) / max(h, 1e-4)
            is_closed = end_dist < 0.08

            if n == 3:
                mid_y = (s[1][1] - y0) / max(h, 1e-4)
                return "L" if mid_y < 0.35 else "7"
            if n == 4:
                d01 = math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1])
                d23 = math.hypot(s[3][0] - s[2][0], s[3][1] - s[2][1])
                return "1" if (aspect < 0.45 or d23 > d01 * 1.4) else "4"
            if n == 5 and not is_closed:
                return "M"
            if 11 <= n <= 14 and is_closed:
                return "D"
            if n == 14 and not is_closed:
                return "2"
            if n == 15 and not is_closed:
                return "3"
            if n in (16, 17):
                return "0" if is_closed else "5"
            if n == 23:
                cy = sum(p[1] for p in s) / n
                return "6" if s[0][1] > cy else "9"
            if n >= 26:
                return "8"

        if allow_cjk_fallback and n_strokes >= 4 and 0.50 <= aspect <= 1.35:
            if 4 <= n_strokes <= 6 and 40 <= n_verts <= 47:
                return "地"
            if 10 <= n_strokes <= 11 and 51 <= n_verts <= 57:
                return "脚"
            if 12 <= n_strokes <= 15 and 50 <= n_verts <= 58:
                return "螺"
            if 9 <= n_strokes <= 12 and 44 <= n_verts <= 50:
                return "栓"

        return ""

    def segment_and_decode_upright_strokes(self, rot_strokes, allow_cjk_fallback=False):
        items = []
        all_y = [p[1] for s in rot_strokes for p in s]
        total_h = max(all_y) - min(all_y) if all_y else 1.0
        for s in rot_strokes:
            xs = [p[0] for p in s]
            ys = [p[1] for p in s]
            if max(xs) - min(xs) < 1e-3 and max(ys) - min(ys) < 1e-3:
                continue
            items.append([min(xs), max(xs), min(ys), max(ys), [s]])

        items.sort(key=lambda it: (it[0], it[1]))
        overlap_counts = []
        for i, it in enumerate(items):
            ic = 0.5 * (it[0] + it[1])
            cnt = sum(1 for j, other in enumerate(items) if i != j and (other[0] - 0.1 * total_h <= ic <= other[1] + 0.1 * total_h))
            overlap_counts.append(cnt)

        char_boxes = []
        for i, it in enumerate(items):
            is_isolated_ascii = (overlap_counts[i] == 0) and self.is_standalone_ascii_stroke(it[4][0], total_h)
            it_ext = it + [is_isolated_ascii]
            if not char_boxes:
                char_boxes.append(it_ext)
            else:
                prev = char_boxes[-1]
                overlap = min(prev[1], it[1]) - max(prev[0], it[0])
                min_w = max(min(prev[1] - prev[0], it[1] - it[0]), 1e-3)
                merged_w = max(prev[1], it[1]) - min(prev[0], it[0])
                ic = 0.5 * (it[0] + it[1])
                pc = 0.5 * (prev[0] + prev[1])
                center_inside = (prev[0] - 1e-3 <= ic <= prev[1] + 1e-3) or (it[0] - 1e-3 <= pc <= it[1] + 1e-3)

                prev_is_ascii = prev[5] and len(prev[4]) == 1
                it_is_ascii = is_isolated_ascii

                if ((overlap / min_w > 0.25 or center_inside) and not (prev_is_ascii and it_is_ascii)) or \
                   (not prev_is_ascii and not it_is_ascii and overlap > -0.10 * total_h and merged_w <= 0.96 * total_h):
                    prev[0] = min(prev[0], it[0])
                    prev[1] = max(prev[1], it[1])
                    prev[2] = min(prev[2], it[2])
                    prev[3] = max(prev[3], it[3])
                    prev[4].extend(it[4])
                    prev[5] = False
                else:
                    char_boxes.append(it_ext)

        decoded_chars = []
        unknown_boxes = 0
        for cb in char_boxes:
            ch = self.classify_single_shx_glyph_topology(cb[4], allow_cjk_fallback=allow_cjk_fallback)
            if ch:
                decoded_chars.append(ch)
            else:
                unknown_boxes += 1
                decoded_chars.append("?")

        final_str = []
        for idx, ch in enumerate(decoded_chars):
            if idx > 0 and ord(decoded_chars[idx - 1]) > 127 and ord(ch) < 127:
                final_str.append(" ")
            final_str.append(ch)
        return "".join(final_str), unknown_boxes, char_boxes

    def call_llm_ocr(self, img: Image.Image) -> str:
        url = self.cfg.llm_url.strip()
        if not url:
            return ""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        model_name = self.cfg.llm_model.strip() or "deepseek-ai/DeepSeek-OCR"

        is_deepseek = "deepseek" in model_name.lower()
        prompt = "Free OCR." if is_deepseek else "请准确识别图中的CAD工程文字或尺寸数字，仅输出识别出的纯文本内容，不要任何解释。"

        headers = {"Content-Type": "application/json"}
        if self.cfg.llm_key.strip():
            headers["Authorization"] = f"Bearer {self.cfg.llm_key.strip()}"

        if ":11434" in url or "/api/chat" in url or "/api/generate" in url:
            payload = json.dumps({
                "model": model_name,
                "messages": [{"role": "user", "content": prompt, "images": [b64]}],
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                rjson = json.loads(resp.read().decode("utf-8"))
                return rjson.get("message", {}).get("content", "").strip()

        payload = json.dumps({
            "model": model_name,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ]
            }],
            "temperature": 0.0,
            "max_tokens": 128,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            rjson = json.loads(resp.read().decode("utf-8"))
            return rjson["choices"][0]["message"]["content"].strip()

    def run_rapid_on_image(self, arr_rgb):
        """调用 RapidOCR (rapidocr_onnxruntime / rapidocr) 识别单块图像文字。"""
        rapid_inst = self.get_rapid_ocr()
        if rapid_inst is None:
            return ""
        try:
            out = rapid_inst(arr_rgb)
            res = out[0] if isinstance(out, tuple) else out
            if not res:
                return ""
            if hasattr(res, "txts") and res.txts:
                return "".join(str(t) for t in res.txts if t).strip()
            lines_txt = []
            for item in res:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    lines_txt.append(str(item[1]))
                elif isinstance(item, dict) and "txt" in item:
                    lines_txt.append(str(item["txt"]))
            return "".join(lines_txt).strip()
        except Exception:
            return ""

    def run_paddle_on_image(self, arr_rgb):
        """同时兼容百度 PaddleOCR 2.x (`[[box, (txt, score)], ...]`) 与 PaddleOCR 3.x (`[{'rec_texts': [...]}]`)。"""
        paddle_inst = self.get_paddle_ocr()
        if paddle_inst is None:
            return ""
        res = None
        for call_fn in (
            lambda: paddle_inst.ocr(arr_rgb, cls=False),
            lambda: paddle_inst.ocr(arr_rgb),
            lambda: paddle_inst.predict(arr_rgb),
        ):
            try:
                res = call_fn()
                break
            except Exception:
                continue
        if not res:
            return ""
        lines_txt = []
        first = res[0]
        if isinstance(first, dict) or hasattr(first, "get"):
            rec_texts = first.get("rec_texts") if hasattr(first, "get") else None
            if rec_texts:
                lines_txt.extend(str(t) for t in rec_texts if t)
        elif isinstance(first, (list, tuple)):
            for line in first:
                if isinstance(line, dict) and "rec_texts" in line:
                    lines_txt.extend(str(t) for t in line["rec_texts"] if t)
                elif isinstance(line, (list, tuple)) and len(line) >= 2:
                    if isinstance(line[1], (list, tuple)) and len(line[1]) >= 1:
                        lines_txt.append(str(line[1][0]))
                    elif isinstance(line[1], str):
                        lines_txt.append(line[1])
        return "".join(lines_txt).strip()

    def recognize_cluster(self, strokes_pt, angle_deg=0.0):
        img, rot_strokes = self.render_strokes_to_pil(strokes_pt, angle_deg=angle_deg)
        mode = self.cfg.ocr_mode.lower()

        # 1. 纯数字/ASCII 工程单线符号优先走零误差几何拓扑解析
        topo_ascii, unk_ascii, char_boxes = self.segment_and_decode_upright_strokes(rot_strokes, allow_cjk_fallback=False)
        if unk_ascii == 0 and topo_ascii:
            return topo_ascii

        # 2. 模式 3: 接入第三方 LLM (接口地址、模型名称、秘钥)
        if mode == "llm":
            try:
                api_txt = self.call_llm_ocr(img)
                if api_txt:
                    return api_txt
            except Exception:
                pass

        # 3. 模式 1: RapidOCR (默认推荐，轻量高速离线识别)
        if mode in ("rapidocr", "rapid", "builtin_1", "auto"):
            txt = self.run_rapid_on_image(np.array(img))
            if txt:
                return txt
            if mode == "auto":
                txt_p = self.run_paddle_on_image(np.array(img))
                if txt_p:
                    return txt_p

        # 4. 模式 2: 百度 PaddleOCR (PP-OCR 2.x / 3.x)
        if mode in ("paddleocr", "paddle", "builtin_2"):
            txt = self.run_paddle_on_image(np.array(img))
            if txt:
                return txt
            txt_r = self.run_rapid_on_image(np.array(img))
            if txt_r:
                return txt_r

        topo_cjk, unk_cjk, _ = self.segment_and_decode_upright_strokes(rot_strokes, allow_cjk_fallback=True)
        if unk_cjk == 0 and topo_cjk:
            return topo_cjk
        return topo_ascii.replace("?", "").strip()
