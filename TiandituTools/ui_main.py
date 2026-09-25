# -*- coding: utf-8 -*-
"""ui_main —— 独立进程中的 Tkinter 界面入口。

不要在本模块以外的 ArcMap 进程里 import 各 ui_*.py 的 GUI 部分。

调用方式（由 ui_bridge.run_ui 负责）：
    <ArcGIS pythonw.exe> ui_main.py <mode> <in.json> <out.json>

mode:
    settings  设置对话框（界面内部自行读写 config.json，结果为空）
    basemap   底图选择窗口 -> {"kind": "maptype|group|catalog|xyz", ...}
    search    搜索窗口     -> {"kind": "point", "name":..., "lon":..., "lat":...}
    xyz       自定义 XYZ 图源管理器（自读自写 config.json，结果为空）
    help      帮助窗口（纯展示，结果为空）

约定：结果以 JSON 写在 out.json（写 {} 表示用户取消）；任何异常都记入
      %APPDATA%\\TiandituTools\\ui_error.log，保证父进程不会因界面崩溃而挂住。
"""

from __future__ import print_function

import io
import json
import os
import sys
import traceback

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)


def _log(text):
    try:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                         "TiandituTools")
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(os.path.join(d, "ui_error.log"), "ab") as f:
            f.write((u"%s\n" % text).encode("utf-8", "ignore"))
    except Exception:
        pass


def _bring_to_front(win):
    """让独立进程的窗口冒到最前（否则容易被 ArcMap 挡住）"""
    for fn in ("deiconify", "lift", "focus_force"):
        try:
            getattr(win, fn)()
        except Exception:
            pass
    try:
        win.attributes("-topmost", True)
        win.after(900, lambda: _unset_topmost(win))
    except Exception:
        pass


def _unset_topmost(win):
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass


def _read_payload(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with io.open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception:
        return {}


def _write_result(path, result):
    if not path:
        return
    try:
        data = json.dumps(result if result is not None else {}, ensure_ascii=False)
        with io.open(path, "wb") as f:
            f.write(data.encode("utf-8"))
    except Exception:
        _log("ui_main: 写入结果失败\n%s" % traceback.format_exc())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    in_path = sys.argv[2] if len(sys.argv) > 2 else ""
    out_path = sys.argv[3] if len(sys.argv) > 3 else ""

    payload = _read_payload(in_path)
    _log("ui_main: start mode=%s payload=%s" % (mode, payload))

    result = None
    try:
        if mode == "settings":
            import ui_settings
            # payload 可带 {"tab": "图源管理"}
            result = ui_settings.run_standalone(payload)
        elif mode == "basemap":
            import ui_menus
            result = ui_menus.run_standalone()
        elif mode == "search":
            import ui_search
            result = ui_search.run_standalone()
        elif mode == "xyz":
            import ui_xyz
            result = ui_xyz.run_standalone()
        elif mode == "help":
            # 接受可选的 {"tab": "常见问题"} —— 便于从别处"直接打开某一页"，
            # 也方便开发时逐页截图检查（见 dev_test_help.py）。
            import ui_help
            result = ui_help.run_standalone(payload)
        else:
            _log("ui_main: 未知 mode=%r" % mode)
    except Exception:
        _log("ui_main(%s) 抛出异常:\n%s" % (mode, traceback.format_exc()))
        result = None

    # 【重要】本进程只负责「让用户选」，**不负责把图层加进地图**。
    #
    # 曾经在这里 import layer_manager 就地加图层，有两个致命问题：
    #   1. WMTSLayer 是 in-proc 组件，在本进程 new 出来再加进 ArcMap，
    #      ArcMap 拿到的是跨进程代理 —— 画布空白，且本进程一退出 ArcMap 就崩；
    #   2. layer_manager/arcobjects 会（直接或间接）import arcpy，
    #      把 Geoprocessing/Raster/DFORRT 拉进来；本进程是 CREATE_NO_WINDOW
    #      起的、没有控制台，DFORRT 写 CONOUT$ 失败就弹模态框卡死。
    # 所以：界面在独立进程，选完把结果交给 ArcMap 进程去应用（见 __init__.py）。

    _write_result(out_path, result)
    _log("ui_main: done mode=%s" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
