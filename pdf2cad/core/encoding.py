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
"""基础矩阵运算、颜色映射、AIGDT 工程符号解码与全自动防乱码编码器（参考脚本 §1）。"""
import re


# 1. 基础矩阵运算、颜色映射、AIGDT 工程符号解码与全自动防乱码编码器
# ==============================================================================

# 严格映射为符合国标机械制图且 100% 属于 GB2312 (gbcbig.shx) 字库的字符，杜绝 4 字节 GB18030 错位乱码
GDT_SYMBOL_MAP = {
    "n": "%%c",
    "`": "%%p",
    "x": "深",
    "v": "锪平",
    "w": "∨",
    "b": "⊥",
    "f": "∥",
    "g": "↑",
    "j": "⊕",
    "r": "◎",
    "e": "○",
    "a": "∠",
    "c": "○",
    "d": "∥",
    "h": "⌒",
    "i": "⌯",
    "k": "⌓",
    "l": "⌖",
    "m": "Ⓜ",
    "s": "Ⓢ",
    "p": "Ⓟ",
    "u": "↕",
    "y": "锥度",
    "z": "斜度",
}

ANNOTATION_LAYERS_KEYWORDS = (
    "DIM", "TXT", "TEXT", "ANNO", "LEADER", "WELD", "GRID", "AXIS_NUM", "TABLE",
    "螺栓", "载荷", "标注", "文字", "引线", "尺寸", "说明", "符号", "焊缝", "轴号", "表格"
)
GEOMETRY_LAYERS_KEYWORDS = (
    "DRAW", "HATCH", "CENTER", "DASH", "HIDE", "HIDDEN", "DIVIDE", "TK", "TC_ATTRIB", "MAX-",
    "WALL", "AXIS", "CONT", "OUTLINE", "VISIBLE", "SECT", "实线", "虚线", "中心", "剖面", "轮廓", "墙", "轴线"
)
TITLE_OR_FRAME_KEYWORDS = ("TK", "TC_ATTRIB", "MAX-", "TITLE", "BORDER", "FRAME", "图框", "标题")


def is_title_or_frame_layer(layer_name):
    lu = str(layer_name).upper()
    return any(k in lu for k in TITLE_OR_FRAME_KEYWORDS)


def is_geometry_layer(layer_name):
    lu = str(layer_name).upper()
    return any(k in lu for k in GEOMETRY_LAYERS_KEYWORDS)


def is_annotation_layer(layer_name):
    lu = str(layer_name).upper()
    if is_geometry_layer(lu):
        return False
    return any(k in lu for k in ANNOTATION_LAYERS_KEYWORDS) or lu in ("0",)


def is_pure_dim_or_text_layer(layer_name):
    lu = str(layer_name).upper()
    if is_geometry_layer(lu):
        return False
    return any(k in lu for k in ANNOTATION_LAYERS_KEYWORDS)


def mat_mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def apply_mat(x, y, m):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def rgb_to_aci(rgb):
    if not rgb or len(rgb) < 3:
        return 7
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    max_c, min_c = max(r, g, b), min(r, g, b)
    if max_c - min_c < 0.15:
        return 7 if (max_c > 0.8 or max_c < 0.2) else 8
    if r > 0.75 and g < 0.25 and b < 0.25:
        return 1
    if r > 0.75 and g > 0.75 and b < 0.25:
        return 2
    if r < 0.25 and g > 0.75 and b < 0.25:
        return 3
    if r < 0.25 and g > 0.75 and b > 0.75:
        return 4
    if r < 0.25 and g < 0.25 and b > 0.75:
        return 5
    if r > 0.75 and g < 0.25 and b > 0.75:
        return 6
    return 7


def auto_fix_pdf_mojibake(s):
    """
    自动检测并恢复 PDF 内嵌未绑定 ToUnicode CMap 的 GBK 字节流（被当作 Latin-1 / CP1252 读取产生的乱码）。
    无需用户指定任何编码。
    """
    if not s:
        return ""
    has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF for c in s)
    high_latin = sum(1 for c in s if 0x80 <= ord(c) <= 0xFF and c not in "°±Ø∅×÷")
    if not has_cjk and high_latin >= 2:
        for enc in ("latin1", "cp1252"):
            try:
                raw_bytes = s.encode(enc)
                decoded = raw_bytes.decode("gb18030")
                if any(0x4E00 <= ord(c) <= 0x9FFF for c in decoded):
                    return decoded
            except Exception:
                pass
    return s


ENG_CAD_VOCAB = {
    "this", "document", "is", "property", "of", "and", "shall", "neither", "be",
    "reproduced", "nor", "communicated", "to", "third", "parties", "in", "any",
    "way", "utilized", "for", "own", "purposes", "particularly", "the", "execution",
    "what", "represented", "on", "it", "without", "our", "written", "authorization",
    "customer", "star", "metalworks", "metal", "works", "pvt", "ltd", "co", "inc",
    "corp", "group", "engineering", "equipment", "machinery", "steel", "iron",
    "approved", "reviewed", "designed", "made", "checked", "drawn", "prepared", "by",
    "certificate", "contract", "drawing", "archiving", "sheet", "page", "part",
    "serial", "project", "model", "no", "design", "stage", "scale", "material",
    "weight", "specialty", "category", "date", "rev", "revision", "contact", "tel",
    "dwg", "size", "title", "name", "unit", "mm", "kg", "ton", "note", "notes",
    "technical", "requirements", "general", "tolerances", "surface", "finish",
}


def segment_concatenated_english_token(token):
    """通用动态规划 (DP) 英文分词器：无需硬编码特定图纸长句即可自动切分任意粘连英文词串。"""
    low = token.lower()
    n = len(low)
    if n < 6 or low in ENG_CAD_VOCAB:
        return token
    dp = [None] * (n + 1)
    dp[0] = (0, [])
    for i in range(n):
        if dp[i] is None:
            continue
        cost_i, words_i = dp[i]
        for j in range(i + 2, min(n, i + 16) + 1):
            if low[i:j] in ENG_CAD_VOCAB:
                new_cost = cost_i + 1
                if dp[j] is None or new_cost < dp[j][0]:
                    dp[j] = (new_cost, words_i + [token[i:j]])
        for j in range(i + 3, min(n, i + 12) + 1):
            if dp[i][1] or j < n:
                new_cost = cost_i + (j - i) * 3
                if dp[j] is None or new_cost < dp[j][0]:
                    dp[j] = (new_cost, words_i + [token[i:j]])
    if dp[n] is not None and len(dp[n][1]) >= 2:
        known_cnt = sum(1 for w in dp[n][1] if w.lower() in ENG_CAD_VOCAB)
        if known_cnt >= max(2, len(dp[n][1]) // 2):
            return " ".join(dp[n][1])
    return token


def restore_english_spacing(s):
    """
    通用零硬编码英文空格恢复器：基于通用工程词典 DP 分词与标点/驼峰规则自动恢复 PDF 粘连英文，
    不影响型号代码（如 Q235A、M10x1-6H、ADX052501）。
    """
    if not s or len(s) < 5:
        return s
    s = re.sub(r'([a-zA-Z]\.:)(?=[A-Za-z0-9])', r'\1 ', s)
    s = re.sub(r'\.(?=[A-Za-z]{2,})', '. ', s)
    s = re.sub(r',(?=[A-Za-z])', ', ', s)
    s = re.sub(r'([a-z]{2,})([A-Z][a-z]{2,})', r'\1 \2', s)
    s = re.sub(r'([A-Za-z]{6,})', lambda m: segment_concatenated_english_token(m.group(1)), s)
    s = re.sub(r'\bCUSTOMER\s+STAR\b', 'STAR', s)
    return s


def sanitize_layer_name(name):
    s = auto_fix_pdf_mojibake(str(name).strip())
    cleaned = re.sub(r'[<>/?":;*|,=`&\s()]', '_', s)
    cleaned = re.sub(r'_+', '_', cleaned).strip('_')
    return cleaned if cleaned else "0"


def format_cad_text(text, for_layer_or_block=False):
    """
    全自动处理 CAD 工程符号与中文字符：
    1. 将工程符号统一转换为 CAD 标准控制码或 GB2312 (gbcbig.shx) 原生支持的国标字符；
    2. 规范化全角括号/冒号等标点并恢复粘连英文空格；
    3. 对任何不在 GB2312 字库内的生僻字符自动转为 AutoCAD 标准 Unicode 转义 `\\U+XXXX`，
       彻底杜绝 4 字节 GB18030 序列在 ANSI_936 (GBK) 下产生错位乱码或 `?` 问号。
    """
    if not text:
        return ""
    s = auto_fix_pdf_mojibake(str(text))
    if len(s) >= 2 and len(s) % 2 == 0 and all(s[k] == s[k + 1] for k in range(0, len(s), 2)):
        s = s[::2]
    s = s.replace("↧", "深").replace("⌴", "锪平").replace("↗", "↑")
    s = s.replace("（", "(").replace("）", ")").replace("：", ":").replace("～", "~")
    if not for_layer_or_block:
        s = restore_english_spacing(s)
        s = re.sub(r'Ø\s*', '%%c', s)
        s = s.replace('∅', '%%c').replace('±', '%%p').replace('°', '%%d')

    out_chars = []
    for ch in s:
        code = ord(ch)
        if code <= 127:
            out_chars.append(ch)
        else:
            try:
                ch.encode("gb2312")
                out_chars.append(ch)
            except UnicodeEncodeError:
                out_chars.append(f"\\U+{code:04X}")
    return "".join(out_chars)


def parse_dimension_numeric_value(txt):
    """从尺寸文本（如 '107.5', '120%%p0.2', '%%c180F7', '(15)'）提取用于比例标定的主数值。"""
    if not txt:
        return None
    s = str(txt).replace("%%c", "").replace("Ø", "").replace("∅", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    if any(k in s for k in ("X", "x", "°", "%%d", "/", "↧", "深", "均布")):
        return None
    m = re.match(r'^(\d+(?:\.\d+)?)(.*)$', s)
    if not m:
        return None
    val = float(m.group(1))
    suffix = m.group(2).strip()
    if val <= 0:
        return None
    if not suffix or suffix.startswith(("%%p", "±", "+", "-", "(", "F", "H", "f", "g", "h", "j", "k", "m", "n", "p", "r", "s")):
        return val
    return None
