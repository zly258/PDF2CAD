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
"""纯正 wxPython 极简桌面 GUI：窗口“打印PDF图纸转DXF”，文件列表 + 一键开始转换（参考脚本 §10）。"""
import os
import sys
import threading
from datetime import datetime

from .convert_api import convert_any_to_dxf, EngineConfig
from ..version import __version__, __copyright__


GUI_TITLE = "打印PDF图纸转DXF"
SUPPORTED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")

OCR_MODE_LABELS = {
    "rapidocr": "RapidOCR (轻量极速)",
    "paddleocr": "百度 PaddleOCR (高精度)",
    "llm": "LLM 视觉大模型 API",
}

ABOUT_TEXT = (
    f"软件名称：{GUI_TITLE}\n"
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

USAGE_TEXT = (
    "【快速使用说明】\n\n"
    "1. 添加图纸：点击主界面“添加文件”（支持单选或框选多个 PDF/图片）或“添加文件夹”，也可直接将文件/文件夹拖拽到文件列表中。\n"
    "2. 开始转换：无需区分单个或批量，直接点击“开始转换”，程序会依次转换列表中的全部图纸，\n"
    "   并在源图纸同目录下生成带统一批次时间戳后缀的 DXF 文件（例如：`轴承座_20261024_214500.dxf`）。\n"
    "3. OCR 配置（顶部菜单【OCR配置】）：\n"
    "   - RapidOCR（默认推荐）：基于 ONNXRuntime 的轻量级高速离线识别；\n"
    "   - 百度 PaddleOCR：百度飞桨 PP-OCR 引擎，适合复杂单线字与扫描图纸；\n"
    "   - LLM 视觉大模型：支持配置接口地址 URL、模型名称 Model 与秘钥 API Key。"
)


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
    """启动纯正 wxPython 极简桌面界面（主界面：文件列表 + 添加文件 + 开始转换；菜单栏：文件 / OCR配置 / 帮助->关于）。"""
    try:
        import wx
    except ImportError as exc:
        raise RuntimeError("当前环境未安装 wxPython，请先执行 `pip install wxPython -f https://extras.wxpython.org/wxPython/4.x/` 后再启动 GUI。") from exc

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
            super().__init__(parent, title="OCR 与识别参数配置", size=(520, 340), style=wx.DEFAULT_DIALOG_STYLE)
            self.cfg = cfg
            font_normal = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, "Microsoft YaHei")
            font_bold = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, False, "Microsoft YaHei")
            self.SetFont(font_normal)

            panel = wx.Panel(self)
            vbox = wx.BoxSizer(wx.VERTICAL)

            box_engine = wx.StaticBox(panel, label=" 选择 OCR 识别引擎 ")
            box_engine.SetFont(font_bold)
            s_engine = wx.StaticBoxSizer(box_engine, wx.VERTICAL)

            mode_row = wx.BoxSizer(wx.HORIZONTAL)
            self.rb_rapid = wx.RadioButton(panel, label="RapidOCR (轻量极速)", style=wx.RB_GROUP)
            self.rb_paddle = wx.RadioButton(panel, label="百度 PaddleOCR (高精度)")
            self.rb_llm = wx.RadioButton(panel, label="LLM 视觉大模型 API")
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

            box_llm = wx.StaticBox(panel, label=" LLM 接口与图纸比例参数 ")
            box_llm.SetFont(font_bold)
            s_llm = wx.StaticBoxSizer(box_llm, wx.VERTICAL)

            grid = wx.FlexGridSizer(rows=4, cols=2, vgap=8, hgap=8)
            grid.AddGrowableCol(1, 1)

            self.txt_url = wx.TextCtrl(panel, value=cfg.llm_url)
            self.txt_model = wx.TextCtrl(panel, value=cfg.llm_model)
            self.txt_key = wx.TextCtrl(panel, value=cfg.llm_key, style=wx.TE_PASSWORD)
            sc_val = "" if cfg.user_scale is None else str(cfg.user_scale)
            self.txt_scale = wx.TextCtrl(panel, value=sc_val, size=(150, -1))

            grid.Add(wx.StaticText(panel, label="LLM 接口地址："), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_url, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label="LLM 模型名称："), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_model, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label="LLM 接口秘钥："), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_key, 1, wx.EXPAND)
            grid.Add(wx.StaticText(panel, label="比例系数 (留空自动1:1)："), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(self.txt_scale, 0, wx.ALIGN_LEFT)

            s_llm.Add(grid, 1, wx.EXPAND | wx.ALL, 8)
            vbox.Add(s_llm, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            btn_row = wx.BoxSizer(wx.HORIZONTAL)
            btn_ok = wx.Button(panel, wx.ID_OK, label="保存设置", size=(96, 30))
            btn_ok.SetFont(font_bold)
            btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="取消", size=(86, 30))
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
                    wx.MessageBox("比例系数必须为数字（或留空自动按 1:1 计算）！", "提示", wx.OK | wx.ICON_WARNING, self)
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
            super().__init__(None, title=GUI_TITLE, size=(780, 540))
            self.SetMinSize((680, 460))
            self.cfg = EngineConfig(ocr_mode="rapidocr")
            self.file_items = []  # list of dicts: {'path': str, 'out_path': str, 'status': str}

            font_normal = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, "Microsoft YaHei")
            font_bold = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, False, "Microsoft YaHei")
            self.SetFont(font_normal)

            # 1. 顶部菜单栏：文件(F) / OCR配置(O) / 帮助(H) -> 关于(A)
            menubar = wx.MenuBar()

            file_menu = wx.Menu()
            m_add_files = file_menu.Append(wx.ID_OPEN, "添加文件(&A)...	Ctrl+O", "添加单张或多张 PDF/图像图纸到列表")
            m_add_folder = file_menu.Append(wx.ID_ANY, "添加文件夹(&D)...	Ctrl+D", "扫描文件夹并将全部图纸加入列表")
            m_remove_sel = file_menu.Append(wx.ID_DELETE, "移除选中(&R)	Del", "从列表中移除选中的图纸")
            m_clear_list = file_menu.Append(wx.ID_CLEAR, "清空列表(&C)", "清空待转换文件列表")
            file_menu.AppendSeparator()
            m_exit = file_menu.Append(wx.ID_EXIT, "退出(&X)	Ctrl+Q", "关闭程序")

            ocr_menu = wx.Menu()
            self.m_ocr_rapid = ocr_menu.AppendRadioItem(wx.ID_ANY, "RapidOCR — 轻量极速(&R)")
            self.m_ocr_paddle = ocr_menu.AppendRadioItem(wx.ID_ANY, "百度 PaddleOCR — 高精度(&P)")
            self.m_ocr_llm = ocr_menu.AppendRadioItem(wx.ID_ANY, "LLM 视觉大模型 API(&L)")
            self.m_ocr_rapid.Check(True)
            ocr_menu.AppendSeparator()
            m_ocr_settings = ocr_menu.Append(wx.ID_PREFERENCES, "OCR 与识别参数设置(&S)...	Ctrl+P", "配置 RapidOCR / 百度 PaddleOCR / LLM 接口地址与秘钥")

            help_menu = wx.Menu()
            m_usage = help_menu.Append(wx.ID_HELP, "使用说明(&U)	F1", "查看操作说明")
            help_menu.AppendSeparator()
            m_about = help_menu.Append(wx.ID_ABOUT, "关于(&A)", "查看软件说明与版权信息")

            menubar.Append(file_menu, "文件(&F)")
            menubar.Append(ocr_menu, "OCR配置(&O)")
            menubar.Append(help_menu, "帮助(&H)")
            self.SetMenuBar(menubar)

            # 2. 极简主界面：顶部工具栏 + 中部文件列表 + 底部进度条与状态栏
            panel = wx.Panel(self)
            panel.SetBackgroundColour(wx.Colour(246, 248, 250))
            main_sizer = wx.BoxSizer(wx.VERTICAL)

            # 顶部操作栏
            top_bar = wx.BoxSizer(wx.HORIZONTAL)
            self.btn_add = wx.Button(panel, label="添加文件...", size=(104, 34))
            self.btn_add_dir = wx.Button(panel, label="添加文件夹...", size=(108, 34))
            self.btn_remove = wx.Button(panel, label="移除选中", size=(86, 34))
            self.btn_clear = wx.Button(panel, label="清空列表", size=(86, 34))
            self.btn_open_dir = wx.Button(panel, label="打开所在目录", size=(106, 34))
            self.btn_start = wx.Button(panel, label="开始转换", size=(132, 34))
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
            self.list_ctrl.InsertColumn(0, "序号", width=52)
            self.list_ctrl.InsertColumn(1, "图纸文件名", width=185)
            self.list_ctrl.InsertColumn(2, "源文件目录", width=245)
            self.list_ctrl.InsertColumn(3, "状态 / 生成 DXF 文件（统一时间后缀）", width=260)
            self.list_ctrl.SetDropTarget(FileDropTarget(self))
            main_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            # 进度条与精简日志区
            prog_row = wx.BoxSizer(wx.HORIZONTAL)
            self.gauge = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
            prog_row.Add(self.gauge, 1, wx.EXPAND)
            main_sizer.Add(prog_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

            self.txt_log = wx.TextCtrl(panel, size=(-1, 105), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL)
            main_sizer.Add(self.txt_log, 0, wx.EXPAND | wx.ALL, 12)

            panel.SetSizer(main_sizer)

            # 底部状态栏
            self.statusbar = self.CreateStatusBar(2)
            self.statusbar.SetStatusWidths([-3, -2])
            self._refresh_statusbar("就绪 — 请点击“添加文件”或直接拖拽图纸到列表中")

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

            self.Bind(wx.EVT_MENU, lambda e: wx.MessageBox(USAGE_TEXT, "使用说明", wx.OK | wx.ICON_INFORMATION, self), m_usage)
            self.Bind(wx.EVT_MENU, lambda e: wx.MessageBox(ABOUT_TEXT, f"关于 - {GUI_TITLE}", wx.OK | wx.ICON_INFORMATION, self), m_about)

            self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_files)
            self.btn_add_dir.Bind(wx.EVT_BUTTON, self.on_add_folder)
            self.btn_remove.Bind(wx.EVT_BUTTON, self.on_remove_selected)
            self.btn_clear.Bind(wx.EVT_BUTTON, self.on_clear_list)
            self.btn_open_dir.Bind(wx.EVT_BUTTON, self.on_open_selected_dir)
            self.btn_start.Bind(wx.EVT_BUTTON, self.on_start_convert)
            self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_selected_dir)

            self.Centre()

        def _refresh_statusbar(self, left_msg=None):
            if left_msg is not None:
                self.statusbar.SetStatusText(left_msg, 0)
            ocr_label = OCR_MODE_LABELS.get(self.cfg.ocr_mode, self.cfg.ocr_mode)
            self.statusbar.SetStatusText(f"OCR: {ocr_label}  |  v{__version__}  |  {__copyright__}", 1)

        def set_quick_ocr_mode(self, mode_str):
            self.cfg.ocr_mode = mode_str
            self._refresh_statusbar(f"已切换 OCR 引擎为：{OCR_MODE_LABELS.get(mode_str, mode_str)}")
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
                        self._refresh_statusbar(f"已更新 OCR 配置：{OCR_MODE_LABELS.get(m, m)}")

        def add_files_to_list(self, paths):
            existing = {it['path'] for it in self.file_items}
            added_cnt = 0
            for p in paths:
                ap = os.path.abspath(p)
                if os.path.isfile(ap) and ap not in existing:
                    existing.add(ap)
                    self.file_items.append({'path': ap, 'out_path': '', 'status': '待转换'})
                    added_cnt += 1
            self._rebuild_list_ui()
            self._refresh_statusbar(f"列表共有 {len(self.file_items)} 个图纸文件（本次新增 {added_cnt} 个）")

        def _rebuild_list_ui(self):
            self.list_ctrl.DeleteAllItems()
            for idx, it in enumerate(self.file_items, start=1):
                row = self.list_ctrl.InsertItem(idx - 1, str(idx))
                self.list_ctrl.SetItem(row, 1, os.path.basename(it['path']))
                self.list_ctrl.SetItem(row, 2, os.path.dirname(it['path']))
                self.list_ctrl.SetItem(row, 3, it['status'])

        def on_add_files(self, event):
            wildcard = "PDF 与图像图纸 (*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff)|*.pdf;*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff|所有文件 (*.*)|*.*"
            with wx.FileDialog(self, "添加图纸文件（可单选或多选）", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    self.add_files_to_list(dlg.GetPaths())

        def on_add_folder(self, event):
            with wx.DirDialog(self, "选择包含图纸的文件夹", style=wx.DD_DEFAULT_STYLE) as dlg:
                if dlg.ShowModal() == wx.ID_OK:
                    files = _collect_input_files_from_folder(dlg.GetPath())
                    if not files:
                        wx.MessageBox("所选文件夹下未找到支持的 PDF 或图像图纸！", "提示", wx.OK | wx.ICON_WARNING, self)
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
            self._refresh_statusbar(f"已移除 {len(sel_indices)} 项，当前列表剩余 {len(self.file_items)} 个文件")

        def on_clear_list(self, event):
            self.file_items.clear()
            self.list_ctrl.DeleteAllItems()
            self.gauge.SetValue(0)
            self._refresh_statusbar("列表已清空")

        def on_open_selected_dir(self, event):
            idx = self.list_ctrl.GetFirstSelected()
            if idx != -1 and 0 <= idx < len(self.file_items):
                target = self.file_items[idx].get('out_path') or self.file_items[idx]['path']
                _open_folder_in_explorer(target)
            elif self.file_items:
                target = self.file_items[0].get('out_path') or self.file_items[0]['path']
                _open_folder_in_explorer(target)

        def append_log(self, msg):
            self.txt_log.AppendText(msg + "\n")

        def update_row_status(self, row_idx, status_text, out_path=""):
            if 0 <= row_idx < len(self.file_items):
                self.file_items[row_idx]['status'] = status_text
                if out_path:
                    self.file_items[row_idx]['out_path'] = out_path
                if row_idx < self.list_ctrl.GetItemCount():
                    self.list_ctrl.SetItem(row_idx, 3, status_text)

        def on_start_convert(self, event):
            if not self.file_items:
                wx.MessageBox("请先点击“添加文件”或拖拽图纸到列表中！", "提示", wx.OK | wx.ICON_WARNING, self)
                return

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
                wx.CallAfter(self.append_log, f"=== 开始转换批次 [{batch_ts}]（共 {total_n} 个文件，OCR={cfg_snapshot.ocr_mode}） ===")
                try:
                    for seq_i, (row_idx, src_path) in enumerate(tasks, start=1):
                        out_dxf = generate_timestamped_dxf_path(src_path, batch_ts=batch_ts)
                        out_name = os.path.basename(out_dxf)
                        wx.CallAfter(self.update_row_status, row_idx, "正在转换...")
                        wx.CallAfter(self._refresh_statusbar, f"正在转换 [{seq_i}/{total_n}]: {os.path.basename(src_path)}")
                        try:
                            st = convert_any_to_dxf(src_path, out_dxf, config=cfg_snapshot)
                            ok_cnt += 1
                            wx.CallAfter(self.update_row_status, row_idx, f"已完成 -> {out_name}", out_dxf)
                            wx.CallAfter(
                                self.append_log,
                                f"[{seq_i}/{total_n}] 成功: {out_dxf} (尺寸标注={st.get('native_dimensions_assembled', 0)}, "
                                f"块引用={st.get('annotation_blocks_assembled', 0)}, 圆={st.get('circles', 0)}, 圆弧={st.get('arcs', 0)})"
                            )
                        except Exception as file_ex:
                            wx.CallAfter(self.update_row_status, row_idx, f"失败: {file_ex}")
                            wx.CallAfter(self.append_log, f"[{seq_i}/{total_n}] 失败 ({src_path}): {file_ex}")
                        pct = int(round(seq_i * 100.0 / total_n))
                        wx.CallAfter(self.gauge.SetValue, pct)

                    wx.CallAfter(self._refresh_statusbar, f"转换完成：成功 {ok_cnt}/{total_n} 个文件（时间后缀 _{batch_ts}.dxf）")
                    wx.CallAfter(
                        wx.MessageBox,
                        f"转换完成！\n成功：{ok_cnt} / {total_n} 个文件\n统一时间后缀：_{batch_ts}.dxf",
                        "转换完成",
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                finally:
                    wx.CallAfter(self.btn_start.Enable, True)
                    wx.CallAfter(self.btn_add.Enable, True)
                    wx.CallAfter(self.btn_add_dir.Enable, True)
                    wx.CallAfter(self.btn_remove.Enable, True)
                    wx.CallAfter(self.btn_clear.Enable, True)

            threading.Thread(target=worker, daemon=True).start()

    frame = MainFrame()
    frame.Show()
    app.MainLoop()
