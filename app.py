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
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（GUI 程序，无控制台窗口）。

保持极薄：带参数走 CLI、不带参数走图形界面，全部逻辑在 pdf2cad.cli 内。
"""
import os
import sys

# 源码直跑与冻结运行都保证项目根在 sys.path 首位
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pdf2cad.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
