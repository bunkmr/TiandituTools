# -*- coding: utf-8 -*-
"""优雅退出 ArcMap（避免像上次那样被强杀导致 Normal.mxt 写坏）"""
from __future__ import print_function

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "TiandituTools"))


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def main():
    import ctypes
    from ctypes import wintypes

    import arcobjects

    u32 = ctypes.windll.user32
    try:
        app = arcobjects.application()
    except Exception as e:
        log("取 application 失败: %r" % (e,))
        app = None

    if app is not None:
        # 先试着走官方 Quit
        for name in ("Quit", "Shutdown", "Exit"):
            fn = getattr(app, name, None)
            if fn is None:
                continue
            try:
                fn()
                log("已调用 Application.%s()" % name)
                time.sleep(6)
                return 0
            except Exception as e:
                log("Application.%s() 失败: %r" % (name, e))

    # 退路：给主窗口发 WM_CLOSE（等同于点右上角关闭，ArcMap 会正常收尾）
    EnumWindows = u32.EnumWindows
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    hits = []

    def cb(h, l):
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        n = u32.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            if "ArcMap" in buf.value and u32.IsWindowVisible(h):
                hits.append(h)
        return True

    EnumWindows(CB(cb), 0)
    if not hits:
        log("没找到 ArcMap 窗口，可能已经退出")
        return 0
    WM_CLOSE = 0x0010
    for h in hits:
        u32.PostMessageW(h, WM_CLOSE, 0, 0)
        log("已向 hwnd=%s 发送 WM_CLOSE" % h)
    time.sleep(8)
    return 0


if __name__ == "__main__":
    sys.exit(main())
