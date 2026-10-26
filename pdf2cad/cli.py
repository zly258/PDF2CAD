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
"""命令行入口：带参数走 CLI 批量/单文件转换，不带参数启动 wxPython 图形界面（与参考脚本 __main__ 同构）。"""
import argparse
import json
import os
from datetime import datetime

from .core.config import EngineConfig
from .core.converter import convert_any_to_dxf
from .ui.helpers import _collect_input_files_from_folder, generate_timestamped_dxf_path
from .version import GUI_TITLE, __copyright__, __version__


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=f"{GUI_TITLE} v{__version__} ({__copyright__})",
                        epilog="不带参数运行时启动图形界面。"
    )
    parser.add_argument("-v", "--version", action="version", version=f"pdf2cad v{__version__} ({__copyright__})")
    parser.add_argument("input", nargs="*", help="输入 PDF/图像路径，或包含图纸的目录")
    parser.add_argument("-o", "--output", type=str, default=None, help="输出 .dxf 文件路径（单文件）或输出目录（批量）")
    parser.add_argument("--scale", type=float, default=None, help="手动指定比例（毫米/磅）；留空按尺寸标注自动 1:1 标定")
    parser.add_argument(
        "--ocr",
        type=str,
        default="rapidocr",
        choices=["rapidocr", "paddleocr", "llm", "builtin_1", "builtin_2", "auto"],
        help="识别方式：rapidocr（默认）/ paddleocr / llm",
    )
    parser.add_argument("--llm-url", type=str, default=os.environ.get("LLM_API_URL", "http://localhost:8000/v1/chat/completions"), help="LLM API endpoint URL")
    parser.add_argument("--llm-model", type=str, default=os.environ.get("LLM_MODEL", "deepseek-ai/DeepSeek-OCR"), help="LLM model name")
    parser.add_argument("--llm-key", type=str, default=os.environ.get("LLM_API_KEY", ""), help="LLM API Key")
    parser.add_argument("--gui", action="store_true", help="强制启动图形界面")
    args = parser.parse_args(argv)

    if args.input and not args.gui:
        cfg = EngineConfig(
            ocr_mode=args.ocr,
            llm_url=args.llm_url,
            llm_model=args.llm_model,
            llm_key=args.llm_key,
            user_scale=args.scale,
        )
        # 兼容 `pdf2cad input.pdf output.dxf` 显式指定输出文件名调用
        if len(args.input) == 2 and os.path.isfile(args.input[0]) and args.input[1].lower().endswith(".dxf") and args.output is None:
            res = convert_any_to_dxf(args.input[0], args.input[1], config=cfg)
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            cli_files = []
            for item in args.input:
                if os.path.isdir(item):
                    cli_files.extend(_collect_input_files_from_folder(item))
                elif os.path.isfile(item):
                    cli_files.append(os.path.abspath(item))
            if not cli_files:
                parser.error("未找到有效的输入文件或目录！")
            batch_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if len(cli_files) == 1 and args.output and args.output.lower().endswith(".dxf"):
                res = convert_any_to_dxf(cli_files[0], args.output, config=cfg)
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                out_dir = args.output if (args.output and os.path.isdir(args.output)) else None
                batch_res = []
                for fp in cli_files:
                    op = generate_timestamped_dxf_path(fp, batch_ts=batch_ts, output_dir=out_dir)
                    st = convert_any_to_dxf(fp, op, config=cfg)
                    batch_res.append({"input": fp, "output": op, "stats": st})
                print(json.dumps({"batch_timestamp": batch_ts, "batch_count": len(batch_res), "results": batch_res}, ensure_ascii=False, indent=2))
    else:
        from .ui.app import launch
        return launch()
    return 0
