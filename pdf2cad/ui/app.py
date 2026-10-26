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
"""纯正 wxPython 极简桌面 GUI（英文 / 中文双语，默认英文，语言选择持久化记忆）。

语言规则：
- 默认 English；通过菜单 Language -> 中文（简体） 即时切换并重建界面；
- 语言选择写入 `~/.pdf2cad/gui.json`，下次启动自动恢复上次选择。
"""
import json
import os
import sys
import threading
from datetime import datetime

from .convert_api import convert_any_to_dxf, EngineConfig
from ..version import __version__, __copyright__


# ==============================================================================
# 多语言状态与持久化（默认英文，切换后记住）
# ==============================================================================

_STATE = {"lang": "en"}
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pdf2cad")
CONFIG_PATH = os.path.join(CONFIG_DIR, "gui.json")

STR = {
    "en": {
        "title": "Print PDF Drawings to DXF",
        "menu_file": "File(&F)",
        "menu_ocr": "OCR Config(&O)",
        "menu_help": "Help(&H)",
        "menu_lang": "Language(&G)",
        "lang_en": "English",
        "lang_zh": "中文（简体）",
        "add_files": "Add &Files...\tCtrl+O",
        "add_files_help": "Add one or more PDF/image drawings to the list",
        "add_folder": "Add &Folder...\tCtrl+D",
        "add_folder_help": "Scan a folder and add every drawing in it",
        "remove_sel": "&Remove Selected\tDel",
        "remove_sel_help": "Remove the selected drawings from the list",
        "clear_list": "&Clear List",
        "clear_list_help": "Clear the file list",
        "exit": "E&xit\tCtrl+Q",
        "exit_help": "Quit the program",
        "ocr_rapid": "RapidOCR — Lightweight && Fast(&R)",
        "ocr_paddle": "Baidu PaddleOCR — High Accuracy(&P)",
        "ocr_llm": "LLM Vision API(&L)",
        "ocr_settings": "OCR / Recognition Settings(&S)...\tCtrl+P",
        "ocr_settings_help": "Configure RapidOCR / Baidu PaddleOCR / LLM endpoint and key",
        "usage": "&Usage Guide\tF1",
        "usage_help": "Show the quick guide",
        "about": "&About",
        "about_help": "About this program and its copyright",
        "btn_add": "Add Files...",
        "btn_add_dir": "Add Folder...",
        "btn_remove": "Remove Selected",
        "btn_clear": "Clear List",
        "btn_open_dir": "Open Folder",
        "btn_start": "Start Conversion",
        "col0": "#",
        "col1": "Drawing File",
        "col2": "Source Folder",
        "col3": "Status / Generated DXF (batch timestamp)",
        "ready": "Ready — click \"Add Files...\" or drag drawings into the list",
        "statusbar_right": "OCR: {0}  |  v{1}  |  {2}",
        "switched_ocr": "OCR engine switched to: {0}",
        "updated_ocr": "OCR configuration updated: {0}",
        "list_total": "List has {0} file(s) ({1} added this time)",
        "removed": "Removed {0} item(s), {1} file(s) remain in the list",
        "cleared": "List cleared",
        "pending": "Pending",
        "converting": "Converting...",
        "done_row": "Done -> {0}",
        "failed_row": "Failed: {0}",
        "dlg_add_files": "Add drawing files (single or multi-select)",
        "wildcard": ("PDF and image drawings (*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff)"
                     "|*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff|All files (*.*)|*.*"),
        "dlg_add_folder": "Choose a folder containing drawings",
        "msg_warn_title": "Notice",
        "msg_no_files": "No supported PDF or image drawings found in the selected folder!",
        "msg_need_files": "Please click \"Add Files...\" or drag drawings into the list first!",
        "msg_scale_invalid": "Scale must be a number (or leave it empty for automatic 1:1)!",
        "msg_lang_busy": "A conversion is running — please wait until it finishes before switching the language.",
        "log_batch": "=== Conversion batch [{0}] started ({1} file(s), OCR={2}) ===",
        "status_converting": "Converting [{0}/{1}]: {2}",
        "log_ok": "[{0}/{1}] OK: {2} (dimensions={3}, blocks={4}, circles={5}, arcs={6})",
        "log_fail": "[{0}/{1}] FAILED ({2}): {3}",
        "done_summary": "Conversion finished: {0}/{1} file(s) OK (timestamp suffix _{2}.dxf)",
        "dlg_done_title": "Conversion finished",
        "dlg_done": "Conversion finished!\nOK: {0} / {1} file(s)\nBatch timestamp suffix: _{2}.dxf",
        "dlg_ocr_title": "OCR / Recognition Settings",
        "box_engine": " Select OCR engine ",
        "box_llm": " LLM endpoint & drawing scale ",
        "lbl_url": "LLM endpoint URL:",
        "lbl_model": "LLM model name:",
        "lbl_key": "LLM API key:",
        "lbl_scale": "Scale (empty = auto 1:1):",
        "btn_ok": "Save",
        "btn_cancel": "Cancel",
        "about_title": "About - {0}",
        "usage_title": "Usage Guide",
        "ocr_label_rapidocr": "RapidOCR (lightweight & fast)",
        "ocr_label_paddleocr": "Baidu PaddleOCR (high accuracy)",
        "ocr_label_llm": "LLM vision API",
    },
    "zh": {
        "title": "打印PDF图纸转DXF",
        "menu_file": "文件(&F)",
        "menu_ocr": "OCR配置(&O)",
        "menu_help": "帮助(&H)",
        "menu_lang": "语言(&G)",
        "lang_en": "English",
        "lang_zh": "中文（简体）",
        "add_files": "添加文件(&A)...\tCtrl+O",
        "add_files_help": "添加单张或多张 PDF/图像图纸到列表",
        "add_folder": "添加文件夹(&D)...\tCtrl+D",
        "add_folder_help": "扫描文件夹并将全部图纸加入列表",
        "remove_sel": "移除选中(&R)\tDel",
        "remove_sel_help": "从列表中移除选中的图纸",
        "clear_list": "清空列表(&C)",
        "clear_list_help": "清空待转换文件列表",
        "exit": "退出(&X)\tCtrl+Q",
        "exit_help": "关闭程序",
        "ocr_rapid": "RapidOCR — 轻量极速(&R)",
        "ocr_paddle": "百度 PaddleOCR — 高精度(&P)",
        "ocr_llm": "LLM 视觉大模型 API(&L)",
        "ocr_settings": "OCR 与识别参数设置(&S)...\tCtrl+P",
        "ocr_settings_help": "配置 RapidOCR / 百度 PaddleOCR / LLM 接口地址与秘钥",
        "usage": "使用说明(&U)\tF1",
        "usage_help": "查看操作说明",
        "about": "关于(&A)",
        "about_help": "查看软件说明与版权信息",
        "btn_add": "添加文件...",
        "btn_add_dir": "添加文件夹...",
        "btn_remove": "移除选中",
        "btn_clear": "清空列表",
        "btn_open_dir": "打开所在目录",
        "btn_start": "开始转换",
        "col0": "序号",
        "col1": "图纸文件名",
        "col2": "源文件目录",
        "col3": "状态 / 生成 DXF 文件（统一时间后缀）",
        "ready": "就绪 — 请点击“添加文件”或直接拖拽图纸到列表中",
        "statusbar_right": "OCR: {0}  |  v{1}  |  {2}",
        "switched_ocr": "已切换 OCR 引擎为：{0}",
        "updated_ocr": "已更新 OCR 配置：{0}",
        "list_total": "列表共有 {0} 个图纸文件（本次新增 {1} 个）",
        "removed": "已移除 {0} 项，当前列表剩余 {1} 个文件",
        "cleared": "列表已清空",
        "pending": "待转换",
        "converting": "正在转换...",
        "done_row": "已完成 -> {0}",
        "failed_row": "失败: {0}",
        "dlg_add_files": "添加图纸文件（可单选或多选）",
        "wildcard": "PDF 与图像图纸 (*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff)|*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff|所有文件 (*.*)|*.*",
        "dlg_add_folder": "选择包含图纸的文件夹",
        "msg_warn_title": "提示",
        "msg_no_files": "所选文件夹下未找到支持的 PDF 或图像图纸！",
        "msg_need_files": "请先点击“添加文件”或拖拽图纸到列表中！",
        "msg_scale_invalid": "比例系数必须为数字（或留空自动按 1:1 计算）！",
        "msg_lang_busy": "正在转换图纸，请等待转换完成后再切换语言。",
        "log_batch": "=== 开始转换批次 [{0}]（共 {1} 个文件，OCR={2}） ===",
        "status_converting": "正在转换 [{0}/{1}]: {2}",
        "log_ok": "[{0}/{1}] 成功: {2} (尺寸标注={3}, 块引用={4}, 圆={5}, 圆弧={6})",
        "log_fail": "[{0}/{1}] 失败 ({2}): {3}",
        "done_summary": "转换完成：成功 {0}/{1} 个文件（时间后缀 _{2}.dxf）",
        "dlg_done_title": "转换完成",
        "dlg_done": "转换完成！\n成功：{0} / {1} 个文件\n统一时间后缀：_{2}.dxf",
        "dlg_ocr_title": "OCR 与识别参数配置",
        "box_engine": " 选择 OCR 识别引擎 ",
        "box_llm": " LLM 接口与图纸比例参数 ",
        "lbl_url": "LLM 接口地址：",
        "lbl_model": "LLM 模型名称：",
        "lbl_key": "LLM 接口秘钥：",
        "lbl_scale": "比例系数 (留空自动1:1)：",
        "btn_ok": "保存设置",
        "btn_cancel": "取消",
        "about_title": "关于 - {0}",
        "usage_title": "使用说明",
        "ocr_label_rapidocr": "RapidOCR (轻量极速)",
        "ocr_label_paddleocr": "百度 PaddleOCR (高精度)",
        "ocr_label_llm": "LLM 视觉大模型 API",
    },
}


def _t(key):
    """取当前语言的文案；缺键时回落英文，再缺则返回键名。"""
    return STR.get(_STATE["lang"], STR["en"]).get(key, STR["en"].get(key, key))


def current_language():
    """当前界面语言（'en' / 'zh'）。"""
    return _STATE["lang"]


def load_gui_config():
    """读取 GUI 持久化配置（不存在或损坏时返回空 dict，保持默认英文）。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_gui_config(data):
    """写入 GUI 持久化配置；失败静默（不影响转换功能）。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def apply_saved_language():
    """启动时恢复上次语言；无记录或值非法则保持默认英文。"""
    saved = load_gui_config().get("language")
    _STATE["lang"] = saved if saved in ("en", "zh") else "en"
    return _STATE["lang"]


def set_language(lang):
    """切换语言并持久化（下次启动自动恢复）。"""
    if lang not in ("en", "zh"):
        return
    _STATE["lang"] = lang
    cfg = load_gui_config()
    cfg["language"] = lang
    save_gui_config(cfg)


def ocr_mode_label(mode):
    """OCR 引擎的本地化显示名。"""
    return _t("ocr_label_" + str(mode)) if "ocr_label_" + str(mode) in STR.get(_STATE["lang"], {}) else str(mode)


def about_text():
    """关于对话框文案（跟随当前语言）。"""
    if _STATE["lang"] == "zh":
        return (
            f"软件名称：{_t('title')}\n"
            f"当前版本：v{__version__}\n"
            f"版权所有：{__copyright__}\n\n"
            "【核心功能说明】\n"
            "1. 通用零硬编码解析：自动将打印/导出的矢量 PDF 及扫描图纸转换为标准可编辑 CAD (DXF)；\n"
            "2. 原生标注与特殊元素识别：智能还原尺寸标注 (DIMENSION)、焊合引出线 (LEADER)、剖切符号、\n"
            "   表面粗糙度、形位公差、基准符号、标高/坡度、技术要求块、工程表格与标题栏 (TABLE)、\n"
            "   剖面填充区域块 (HATCH_REGION) 以及重复符号块定义归一化复用 (BLOCK / INSERT)；\n"
            "3. 几何轮廓高精度重构：自动还原真圆 (CIRCLE)、圆弧/倒圆角 (ARC)、SVD 微线段中心线/圆弧重构；\n"
            "4. 全自动防乱码：内置 ANSI_936 (GBK) 与 txt.shx + gbcbig.shx 国标双字库绑定，中文与工程符号零乱码；\n"
            "5. 极简统一转换：支持单张或多张图纸统一列表管理，生成 DXF 自动带批次统一时间戳后缀。"
        )
    return (
        f"Software: {_t('title')}\n"
        f"Version: v{__version__}\n"
        f"Copyright: {__copyright__}\n\n"
        "[Key Features]\n"
        "1. Universal zero-hardcoding parsing: converts printed/exported vector PDFs and scanned\n"
        "   drawings into standard editable CAD (DXF);\n"
        "2. Native annotations & special elements: dimensions (DIMENSION), weld leaders (LEADER),\n"
        "   section marks, surface roughness, geometric tolerance frames (FCF), datums, elevation /\n"
        "   slope marks, technical notes, engineering tables and title blocks (TABLE), hatch regions\n"
        "   (HATCH_REGION), plus normalized BLOCK / INSERT reuse of repeated symbols;\n"
        "3. High-accuracy geometry rebuild: true circles (CIRCLE), arcs / fillets (ARC), SVD\n"
        "   micro-segment centre-line and arc reconstruction;\n"
        "4. Zero-garbage encoding: ANSI_936 (GBK) with txt.shx + gbcbig.shx national fonts bound,\n"
        "   Chinese and engineering symbols are never garbled;\n"
        "5. Minimal unified workflow: single or batch drawings in one list; generated DXF files share\n"
        "   a batch timestamp suffix automatically."
    )


def usage_text():
    """使用说明对话框文案（跟随当前语言）。"""
    if _STATE["lang"] == "zh":
        return (
            "【快速使用说明】\n\n"
            "1. 添加图纸：点击主界面“添加文件”（支持单选或框选多个 PDF/图片）或“添加文件夹”，也可直接将文件/文件夹拖拽到文件列表中。\n"
            "2. 开始转换：无需区分单个或批量，直接点击“开始转换”，程序会依次转换列表中的全部图纸，\n"
            "   并在源图纸同目录下生成带统一批次时间戳后缀的 DXF 文件（例如：`轴承座_20261024_214500.dxf`）。\n"
            "3. OCR 配置（顶部菜单【OCR配置】）：\n"
            "   - RapidOCR（默认推荐）：基于 ONNXRuntime 的轻量级高速离线识别；\n"
            "   - 百度 PaddleOCR：百度飞桨 PP-OCR 引擎，适合复杂单线字与扫描图纸；\n"
            "   - LLM 视觉大模型：支持配置接口地址 URL、模型名称 Model 与秘钥 API Key。"
        )
    return (
        "[Quick Guide]\n\n"
        "1. Add drawings: click \"Add Files...\" (single or multi-select PDF/images) or \"Add Folder...\",\n"
        "   or drag files / folders straight into the list.\n"
        "2. Convert: no single/batch switch — just click \"Start Conversion\". Every drawing in the list\n"
        "   is converted in order, producing DXF files with a shared batch timestamp suffix next to the\n"
        "   sources (e.g. `bearing_20261024_214500.dxf`).\n"
        "3. OCR configuration (menu \"OCR Config\"):\n"
        "   - RapidOCR (default): lightweight, fast, fully offline via ONNXRuntime;\n"
        "   - Baidu PaddleOCR: PP-OCR engine, good for complex single-stroke glyphs and scanned sheets;\n"
        "   - LLM vision API: configure the endpoint URL, model name and API key."
    )


SUPPORTED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def _enable_windows_high_dpi():
    """在 Windows 下开启高分屏 DPI 感知，消除字体与控件发虚。"""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _collect_input_files_from_folder(folder_path):
    """扫描指定文件夹下的所有支持图纸文件（排除已生成的 .dxf）。"""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    files = []
    for fn in sorted(os.listdir(folder_path)):
        full_p = os.path.join(folder_path, fn)
        if os.path.isfile(full_p) and os.path.splitext(fn)[1].lower() in SUPPORTED_EXTS:
            files.append(os.path.abspath(full_p))
    return files


def generate_timestamped_dxf_path(input_path: str, batch_ts: str = None, output_dir: str = None) -> str:
    """生成带统一批次时间戳后缀的 DXF 输出路径（如 `图纸名_20261024_214500.dxf`）。"""
    ts = batch_ts or datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = os.path.splitext(os.path.basename(input_path))[0]
    out_name = f"{stem}_{ts}.dxf"
    target_dir = output_dir if (output_dir and os.path.isdir(output_dir)) else os.path.dirname(os.path.abspath(input_path))
    return os.path.join(target_dir, out_name)


def _open_folder_in_explorer(path_str):
    """在系统文件管理器中打开输出目录。"""
    if not path_str:
        return
    target_dir = path_str if os.path.isdir(path_str) else os.path.dirname(os.path.abspath(path_str))
    if not os.path.isdir(target_dir):
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(target_dir)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", target_dir])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target_dir])
    except Exception:
        pass


def launch():
    """启动 wxPython 极简桌面界面（主界面：文件列表 + 一键开始转换；菜单：文件 / OCR配置 / 语言 / 帮助）。"""
    try:
        import wx
    except ImportError as exc:
        raise RuntimeError("当前环境未安装 wxPython，请先执行 `pip install wxPython -f https://extras.wxpython.org/wxPython/4.x/` 后再启动 GUI。") from exc

    apply_saved_language()
    _enable_windows_high_dpi()
    app = wx.App(False)

    class FileDropTarget(wx.FileDropTarget):
        """支持直接将 PDF/图像文件或文件夹拖拽进主界面列表。"""
        def __init__(self, frame):
            super().__init__()
            self.frame = frame

        def OnDropFiles(self, x, y, filenames):
            added = []
            for p in filenames:
                if os.path.isdir(p):
                    added.extend(_collect_input_files_from_folder(p))
                elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in SUPPORTED_EXTS:
                    added.append(os.path.abspath(p))
            if added:
                self.frame.add_files_to_list(added)
            return True

    class OcrConfigDialog(wx.Dialog):
        """菜单【OCR配置】弹出的配置对话框（支持 RapidOCR / 百度 PaddleOCR / LLM 及比例设置）。"""
        def __init__(self, parent, cfg: EngineConfig):
            super().__init__(parent, title=_t("dlg_ocr_title"), size=(560, 340), style=wx.DEFAULT_DIALOG_STYLE)
            self.cfg = cfg
            font_normal = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, "Microsoft YaHei")
            font_bold = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, False, "Microsoft YaHei")
            self.SetFont(font_normal)

            panel = wx.Panel(self)
            vbox = wx.BoxSizer(wx.VERTICAL)

            box_engine = wx.StaticBox(panel, label=_t("box_engine"))
            box_engine.SetFont(font_bold)
            s_engine = wx.StaticBoxSizer(box_engine, wx.VERTICAL)

            mode_row = wx.BoxSizer(wx.HORIZONTAL)
            self.rb_rapid = wx.RadioButton(panel, label=_t("ocr_rapid"), style=wx.RB_GROUP)
            self.rb_paddle = wx.RadioButton(panel, label=_t("ocr_paddle"))
            self.rb_llm = wx.RadioButton(panel, label=_t("ocr_llm"))
            cur_m = cfg.ocr_mode.lower()
            if cur_m in ("paddleocr", "paddle", "builtin_2"):
                self.rb_paddle.SetValue(True)
            elif cur_m == "llm":
                self.rb_llm.SetValue(True)
            else:
                self.rb_rapid.SetValue(True)

            mode_row.Add(self.rb_rapid, 0, wx.RIGHT, 14)
            mode_row.Add(self.rb_paddle, 0, wx.RIGHT, 14)
            mode_row.Add(self.rb_llm, 0)
            s_engine.Add(mode_row, 0, wx.ALL, 8)
            vbox.Add(s_engine, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

            box_llm = wx.StaticBox(panel, label=_t("box_llm"))
            box_llm.SetFont(font_bold)
            s_llm = wx.StaticBoxSizer(box_llm, wx.VERTICAL)

            grid = wx.FlexGridSizer(rows=4, cols=2, vgap=8, hgap=8)
            grid.AddGrowableCol(1, 1)

            self.txt_url = wx.TextCtrl(panel, value=cfg.llm_url)
            self.txt_model = wx.TextCtrl(panel, value=cfg.llm_model)
            self.txt_key = wx.TextCtrl(panel, value=cfg.llm_key, style=wx.TE_PASSWORD)
            sc_val = "" if cfg.user_scale is None else str(cfg.user_scale)
            self.txt_scale = wx.TextCtrl(panel, value=sc_val, size=(150, -1))

            grid.Add(wx.StaticText(panel, label=_t("lbl_url")), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_url, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=_t("lbl_model")), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_model, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=_t("lbl_key")), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_key, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label=_t("lbl_scale")), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_scale, 0, wx.ALIGN_LEFT)

            s_llm.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
            vbox.Add(s_llm, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            btn_ok = wx.Button(panel, wx.ID_OK, label=_t("btn_ok"), size=(96, 30))
            btn_ok.SetFont(font_bold)
            btn_cancel = wx.Button(panel, wx.ID_CANCEL, label=_t("btn_cancel"), size=(86, 30))
            btn_row.AddStretchSpacer(1)
            btn_row.Add(btn_ok, 0, wx.RIGHT, 8)
            btn_row.Add(btn_cancel, 0)
            vbox.Add(btn_row, 0, wx.EXPAND | wx.ALL, 12)

            panel.SetSizer(vbox)

            self.rb_rapid.Bind(wx.EVT_RADIOBUTTON, lambda e: self._update_state())
            self.rb_paddle.Bind(wx.EVT_RADIOBUTTON, lambda e: self._update_state())
            self.rb_llm.Bind(wx.EVT_RADIOBUTTON, lambda e: self._update_state())
            self._update_state()
            self.CentreOnParent()

        def _update_state(self):
            en = self.rb_llm.GetValue()
            self.txt_url.Enable(en)
            self.txt_model.Enable(en)
            self.txt_key.Enable(en)

        def apply_to_config(self) -> bool:
            sc_s = self.txt_scale.GetValue().strip()
            if sc_s:
                try:
                    self.cfg.user_scale = float(sc_s)
                except ValueError:
                    wx.MessageBox(_t("msg_scale_invalid"), _t("msg_warn_title"), wx.OK | wx.ICON_WARNING, self)
                    return False
            else:
                self.cfg.user_scale = None

            if self.rb_paddle.GetValue():
                self.cfg.ocr_mode = "paddleocr"
            elif self.rb_llm.GetValue():
                self.cfg.ocr_mode = "llm"
            else:
                self.cfg.ocr_mode = "rapidocr"
            self.cfg.llm_url = self.txt_url.GetValue().strip()
            self.cfg.llm_model = self.txt_model.GetValue().strip()
            self.cfg.llm_key = self.txt_key.GetValue().strip()
            return True

    class MainFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title=_t("title"), size=(800, 540))
            self.SetMinSize((700, 460))
            self.cfg = EngineConfig(ocr_mode="rapidocr")
            self.file_items = []  # list of dicts: {'path': str, 'out_path': str, 'status': str}
            self._converting = False

            font_normal = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, "Microsoft YaHei")
            font_bold = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, False, "Microsoft YaHei")
            self.SetFont(font_normal)

            # 1. 顶部菜单栏：文件(F) / OCR配置(O) / 语言(G) / 帮助(H) -> 关于(A)
            menubar = wx.MenuBar()

            file_menu = wx.Menu()
            m_add_files = file_menu.Append(wx.ID_OPEN, _t("add_files"), _t("add_files_help"))
            m_add_folder = file_menu.Append(wx.ID_ANY, _t("add_folder"), _t("add_folder_help"))
            m_remove_sel = file_menu.Append(wx.ID_DELETE, _t("remove_sel"), _t("remove_sel_help"))
            m_clear_list = file_menu.Append(wx.ID_CLEAR, _t("clear_list"), _t("clear_list_help"))
            file_menu.AppendSeparator()
            m_exit = file_menu.Append(wx.ID_EXIT, _t("exit"), _t("exit_help"))

            ocr_menu = wx.Menu()
            self.m_ocr_rapid = ocr_menu.AppendRadioItem(wx.ID_ANY, _t("ocr_rapid"))
            self.m_ocr_paddle = ocr_menu.AppendRadioItem(wx.ID_ANY, _t("ocr_paddle"))
            self.m_ocr_llm = ocr_menu.AppendRadioItem(wx.ID_ANY, _t("ocr_llm"))
            self.m_ocr_rapid.Check(True)
            ocr_menu.AppendSeparator()
            m_ocr_settings = ocr_menu.Append(wx.ID_PREFERENCES, _t("ocr_settings"), _t("ocr_settings_help"))

            lang_menu = wx.Menu()
            self.m_lang_en = lang_menu.AppendRadioItem(wx.ID_ANY, _t("lang_en"))
            self.m_lang_zh = lang_menu.AppendRadioItem(wx.ID_ANY, _t("lang_zh"))
            if _STATE["lang"] == "zh":
                self.m_lang_zh.Check(True)
            else:
                self.m_lang_en.Check(True)

            help_menu = wx.Menu()
            m_usage = help_menu.Append(wx.ID_HELP, _t("usage"), _t("usage_help"))
            help_menu.AppendSeparator()
            m_about = help_menu.Append(wx.ID_ABOUT, _t("about"), _t("about_help"))

            menubar.Append(file_menu, _t("menu_file"))
            menubar.Append(ocr_menu, _t("menu_ocr"))
            menubar.Append(lang_menu, _t("menu_lang"))
            menubar.Append(help_menu, _t("menu_help"))
            self.SetMenuBar(menubar)

            # 2. 极简主界面：顶部工具栏 + 中部文件列表 + 底部进度条与日志区
            panel = wx.Panel(self)
            panel.SetBackgroundColour(wx.Colour(246, 248, 250))
            main_sizer = wx.BoxSizer(wx.VERTICAL)

            # 顶部操作栏
            top_bar = wx.BoxSizer(wx.HORIZONTAL)
            self.btn_add = wx.Button(panel, label=_t("btn_add"), size=(110, 34))
            self.btn_add_dir = wx.Button(panel, label=_t("btn_add_dir"), size=(116, 34))
            self.btn_remove = wx.Button(panel, label=_t("btn_remove"), size=(118, 34))
            self.btn_clear = wx.Button(panel, label=_t("btn_clear"), size=(96, 34))
            self.btn_open_dir = wx.Button(panel, label=_t("btn_open_dir"), size=(112, 34))
            self.btn_start = wx.Button(panel, label=_t("btn_start"), size=(136, 34))
            self.btn_start.SetFont(font_bold)

            top_bar.Add(self.btn_add, 0, wx.RIGHT, 6)
            top_bar.Add(self.btn_add_dir, 0, wx.RIGHT, 6)
            top_bar.Add(self.btn_remove, 0, wx.RIGHT, 6)
            top_bar.Add(self.btn_clear, 0, wx.RIGHT, 6)
            top_bar.AddStretchSpacer(1)
            top_bar.Add(self.btn_open_dir, 0, wx.RIGHT, 8)
            top_bar.Add(self.btn_start, 0)
            main_sizer.Add(top_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

            # 中部文件列表（支持单选/多选/拖拽文件，不区分单个或批量）
            self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
            self.list_ctrl.InsertColumn(0, _t("col0"), width=52)
            self.list_ctrl.InsertColumn(1, _t("col1"), width=200)
            self.list_ctrl.InsertColumn(2, _t("col2"), width=225)
            self.list_ctrl.InsertColumn(3, _t("col3"), width=225)
            self.list_ctrl.SetDropTarget(FileDropTarget(self))
            main_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            # 进度条与日志区
            prog_row = wx.BoxSizer(wx.HORIZONTAL)
            self.gauge = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
            prog_row.Add(self.gauge, 1, wx.EXPAND)
            main_sizer.Add(prog_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

            self.txt_log = wx.TextCtrl(panel, size=(-1, 105), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
            main_sizer.Add(self.txt_log, 0, wx.EXPAND | wx.ALL, 12)

            panel.SetSizer(main_sizer)

            # 底部状态栏：单字段，仅显示版权信息（整行独占，不再截断）
            self.statusbar = self.CreateStatusBar(1)
            self.statusbar.SetStatusWidths([-1])
            self._refresh_statusbar()

            # 绑定事件
            self.Bind(wx.EVT_MENU, self.on_add_files, m_add_files)
            self.Bind(wx.EVT_MENU, self.on_add_folder, m_add_folder)
            self.Bind(wx.EVT_MENU, self.on_remove_selected, m_remove_sel)
            self.Bind(wx.EVT_MENU, self.on_clear_list, m_clear_list)
            self.Bind(wx.EVT_MENU, lambda e: self.Close(), m_exit)

            self.Bind(wx.EVT_MENU, lambda e: self.set_quick_ocr_mode("rapidocr"), self.m_ocr_rapid)
            self.Bind(wx.EVT_MENU, lambda e: self.set_quick_ocr_mode("paddleocr"), self.m_ocr_paddle)
            self.Bind(wx.EVT_MENU, lambda e: self.set_quick_ocr_mode("llm"), self.m_ocr_llm)
            self.Bind(wx.EVT_MENU, self.on_open_ocr_config, m_ocr_settings)

            self.Bind(wx.EVT_MENU, self.on_switch_language, self.m_lang_en)
            self.Bind(wx.EVT_MENU, self.on_switch_language, self.m_lang_zh)

            self.Bind(wx.EVT_MENU, lambda e: wx.MessageBox(usage_text(), _t("usage_title"), wx.OK | wx.ICON_INFORMATION, self), m_usage)
            self.Bind(wx.EVT_MENU, lambda e: wx.MessageBox(about_text(), _t("about_title").format(_t("title")), wx.OK | wx.ICON_INFORMATION, self), m_about)

            self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_files)
            self.btn_add_dir.Bind(wx.EVT_BUTTON, self.on_add_folder)
            self.btn_remove.Bind(wx.EVT_BUTTON, self.on_remove_selected)
            self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear_list)
            self.btn_open_dir.Bind(wx.EVT_BUTTON, self.on_open_selected_dir)
            self.btn_start.Bind(wx.EVT_BUTTON, self.on_start_convert)
            self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_selected_dir)

            self.Centre()

        # ---------------- 语言切换（立即重建界面，选择持久化） ----------------
        def on_switch_language(self, event):
            # 菜单事件的 GetEventObject() 不是 wx.MenuItem，必须按菜单项 ID 判别
            new_lang = "zh" if event.GetId() == self.m_lang_zh.GetId() else "en"
            if new_lang == _STATE["lang"]:
                return
            if self._converting:
                # 转换进行中禁止重建窗口，避免工作线程 CallAfter 悬挂到已销毁窗口
                wx.MessageBox(_t("msg_lang_busy"), _t("msg_warn_title"), wx.OK | wx.ICON_WARNING, self)
                if _STATE["lang"] == "zh":
                    self.m_lang_zh.Check(True)
                else:
                    self.m_lang_en.Check(True)
                return
            set_language(new_lang)  # 写入 ~/.pdf2cad/gui.json，下次启动自动恢复
            wx.CallAfter(self._reopen_with_new_language)

        def _reopen_with_new_language(self):
            new_frame = MainFrame()
            new_frame.Show()
            self.Destroy()

        # ---------------- 状态栏与 OCR 快捷切换 ----------------
        def _refresh_statusbar(self, *_ignored):
            # 状态栏固定只显示版权信息；操作提示与进度由文件列表、进度条与日志区承担
            self.statusbar.SetStatusText(__copyright__, 0)

        def set_quick_ocr_mode(self, mode_str):
            self.cfg.ocr_mode = mode_str
            self._refresh_statusbar(_t("switched_ocr").format(ocr_mode_label(mode_str)))
            if mode_str == "llm":
                self.on_open_ocr_config(None)

        def on_open_ocr_config(self, event):
            with OcrConfigDialog(self, self.cfg) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    if dlg.apply_to_config():
                        m = self.cfg.ocr_mode
                        if m == "paddleocr":
                            self.m_ocr_paddle.Check(True)
                        elif m == "llm":
                            self.m_ocr_llm.Check(True)
                        else:
                            self.m_ocr_rapid.Check(True)
                        self._refresh_statusbar(_t("updated_ocr").format(ocr_mode_label(m)))

        # ---------------- 文件列表操作 ----------------
        def add_files_to_list(self, paths):
            existing = {it['path'] for it in self.file_items}
            added_cnt = 0
            for p in paths:
                ap = os.path.abspath(p)
                if os.path.isfile(ap) and ap not in existing:
                    existing.add(ap)
                    self.file_items.append({'path': ap, 'out_path': '', 'status': _t("pending")})
                    added_cnt += 1
            self._rebuild_list_ui()
            self._refresh_statusbar(_t("list_total").format(len(self.file_items), added_cnt))

        def _rebuild_list_ui(self):
            self.list_ctrl.DeleteAllItems()
            for idx, it in enumerate(self.file_items, start=1):
                row = self.list_ctrl.InsertItem(idx - 1, str(idx))
                self.list_ctrl.SetItem(row, 1, os.path.basename(it['path']))
                self.list_ctrl.SetItem(row, 2, os.path.dirname(it['path']))
                self.list_ctrl.SetItem(row, 3, it['status'])

        def on_add_files(self, event):
            with wx.FileDialog(self, _t("dlg_add_files"), wildcard=_t("wildcard"), style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    self.add_files_to_list(dlg.GetPaths())

        def on_add_folder(self, event):
            with wx.DirDialog(self, _t("dlg_add_folder"), style=wx.DD_DEFAULT_STYLE) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    files = _collect_input_files_from_folder(dlg.GetPath())
                    if not files:
                        wx.MessageBox(_t("msg_no_files"), _t("msg_warn_title"), wx.OK | wx.ICON_WARNING, self)
                        return
                    self.add_files_to_list(files)

        def on_remove_selected(self, event):
            sel_indices = []
            idx = self.list_ctrl.GetFirstSelected()
            while idx != -1:
                sel_indices.append(idx)
                idx = self.list_ctrl.GetNextSelected(idx)
            if not sel_indices:
                return
            for i in sorted(sel_indices, reverse=True):
                if 0 <= i < len(self.file_items):
                    self.file_items.pop(i)
            self._rebuild_list_ui()
            self._refresh_statusbar(_t("removed").format(len(sel_indices), len(self.file_items)))

        def on_clear_list(self, event):
            self.file_items.clear()
            self.list_ctrl.DeleteAllItems()
            self.gauge.SetValue(0)
            self._refresh_statusbar(_t("cleared"))

        def on_open_selected_dir(self, event):
            idx = self.list_ctrl.GetFirstSelected()
            if idx != -1 and 0 <= idx < len(self.file_items):
                target = self.file_items[idx].get('out_path') or self.file_items[idx]['path']
                _open_folder_in_explorer(target)
            elif self.file_items:
                target = self.file_items[0].get('out_path') or self.file_items[0]['path']
                _open_folder_in_explorer(target)

        # ---------------- 转换执行 ----------------
        def append_log(self, msg):
            self.txt_log.AppendText(msg + "\n")

        def update_row_status(self, row_idx, status_text, out_path=""):
            if 0 <= row_idx < len(self.file_items):
                self.file_items[row_idx]['status'] = status_text
                if out_path:
                    self.file_items[row_idx]['out_path'] = out_path
                if row_idx < self.list_ctrl.GetItemCount():
                    self.list_ctrl.SetItem(row_idx, 3, status_text)

        def _re_enable_buttons(self):
            self._converting = False
            self.btn_start.Enable(True)
            self.btn_add.Enable(True)
            self.btn_add_dir.Enable(True)
            self.btn_remove.Enable(True)
            self.btn_clear.Enable(True)

        def on_start_convert(self, event):
            if not self.file_items:
                wx.MessageBox(_t("msg_need_files"), _t("msg_warn_title"), wx.OK | wx.ICON_WARNING, self)
                return

            self._converting = True
            self.btn_start.Enable(False)
            self.btn_add.Enable(False)
            self.btn_add_dir.Enable(False)
            self.btn_remove.Enable(False)
            self.btn_clear.Enable(False)
            self.gauge.SetValue(0)

            # 同一批次所有文件共享统一的时间戳后缀 (_YYYYMMDD_HHMMSS.dxf)
            batch_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            tasks = [(idx, it['path']) for idx, it in enumerate(self.file_items)]
            cfg_snapshot = EngineConfig(
                ocr_mode=self.cfg.ocr_mode,
                llm_url=self.cfg.llm_url,
                llm_model=self.cfg.llm_model,
                llm_key=self.cfg.llm_key,
                user_scale=self.cfg.user_scale,
            )

            def worker():
                ok_cnt = 0
                total_n = len(tasks)
                wx.CallAfter(self.append_log, _t("log_batch").format(batch_ts, total_n, cfg_snapshot.ocr_mode))
                try:
                    for seq_i, (row_idx, src_path) in enumerate(tasks, start=1):
                        out_dxf = generate_timestamped_dxf_path(src_path, batch_ts=batch_ts)
                        out_name = os.path.basename(out_dxf)
                        wx.CallAfter(self.update_row_status, row_idx, _t("converting"))
                        wx.CallAfter(self._refresh_statusbar, _t("status_converting").format(seq_i, total_n, os.path.basename(src_path)))
                        try:
                            st = convert_any_to_dxf(src_path, out_dxf, config=cfg_snapshot)
                            ok_cnt += 1
                            wx.CallAfter(self.update_row_status, row_idx, _t("done_row").format(out_name), out_dxf)
                            wx.CallAfter(
                                self.append_log,
                                _t("log_ok").format(
                                    seq_i, total_n, out_dxf,
                                    st.get('native_dimensions_assembled', 0),
                                    st.get('annotation_blocks_assembled', 0),
                                    st.get('circles', 0), st.get('arcs', 0),
                                )
                            )
                        except Exception as file_ex:
                            wx.CallAfter(self.update_row_status, row_idx, _t("failed_row").format(file_ex))
                            wx.CallAfter(self.append_log, _t("log_fail").format(seq_i, total_n, src_path, file_ex))
                        pct = int(round(seq_i * 100.0 / total_n))
                        wx.CallAfter(self.gauge.SetValue, pct)

                    wx.CallAfter(self._refresh_statusbar, _t("done_summary").format(ok_cnt, total_n, batch_ts))
                    wx.CallAfter(
                        wx.MessageBox,
                        _t("dlg_done").format(ok_cnt, total_n, batch_ts),
                        _t("dlg_done_title"),
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                finally:
                    wx.CallAfter(self._re_enable_buttons)

            threading.Thread(target=worker, daemon=True).start()

    frame = MainFrame()
    frame.Show()
    app.MainLoop()
