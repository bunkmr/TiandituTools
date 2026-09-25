# -*- coding: utf-8 -*-
"""界面窗口的**摆放**小工具（Tkinter，只在独立进程里跑）。

为什么需要它
------------
本机是 3072x1920 的屏 + 225% 缩放，ArcGIS 自带的 Python 2.7 是
DPI-unaware 的，Tk 因此只看到 1365x853 的"逻辑屏"。窗口如果按默认
方式摆放（Tk 会级联到右下），很容易把底部的按钮条压到任务栏下面 ——
实测帮助窗口 820x660 被放到底部时，右下角的「关闭」按钮就看不见了。

所以统一在这里做三件事：按屏幕**夹取**尺寸、居中、并给个安全的上边距。
所有 ui_*.py 的窗口都应该调 place()，别各自写 geometry()。

本模块不 import arcpy、不 import layer_manager。
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)


#: 屏幕四周的呼吸空间（逻辑像素）
MARGIN_X = 40
MARGIN_Y = 70


def screen_size(win):
    try:
        return int(win.winfo_screenwidth()), int(win.winfo_screenheight())
    except Exception:
        return 1280, 800


def clamp_size(win, width, height):
    """把请求的尺寸夹进屏幕（留出边距），返回 (w, h)"""
    sw, sh = screen_size(win)
    w = max(320, min(int(width), sw - MARGIN_X))
    h = max(240, min(int(height), sh - MARGIN_Y))
    return w, h


def place(win, width, height, min_width=None, min_height=None,
          top_ratio=0.05):
    """给窗口设定位置与大小：夹取到屏幕内、水平居中、靠上放。

    top_ratio 是上边距占屏幕高度的比例 —— 0.05 大约是"标题栏下方一点点"，
    比垂直居中好看（内容从上方开始读），也比 Tk 的默认级联安全得多。
    """
    w, h = clamp_size(win, width, height)
    sw, sh = screen_size(win)
    x = max(0, (sw - w) // 2)
    y = max(0, int(sh * top_ratio))
    y = min(y, max(0, sh - h - 20))
    try:
        if min_width or min_height:
            mw = min(int(min_width or w), w)
            mh = min(int(min_height or h), h)
            win.minsize(mw, mh)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    except Exception:
        pass
    return w, h


def fit(win, max_width=None, max_height=None):
    """窗口**自定尺寸**（不调 geometry 的、resizable(False,False) 的那种）
    建完控件后调一次。

    两件事：
      * 尺寸装得下屏幕 -> 只挪位置，**不动尺寸**（Tk 自动算出来的那种
        "刚好包住控件"的窗口最好看，硬塞一个尺寸反而会留一大片空白）；
      * 装不下 -> 按屏幕夹取，然后再挪。
    """
    try:
        win.update_idletasks()
        w = int(max_width or win.winfo_reqwidth())
        h = int(max_height or win.winfo_reqheight())
    except Exception:
        return None
    sw, sh = screen_size(win)
    x = max(0, (sw - w) // 2)
    y = max(0, min(int(sh * 0.05), max(0, sh - h - 20)))
    if w <= sw - MARGIN_X and h <= sh - MARGIN_Y:
        try:
            win.geometry("+%d+%d" % (x, y))          # 只挪位，不改尺寸
        except Exception:
            pass
        return w, h
    w, h = clamp_size(win, w, h)
    x = max(0, (sw - w) // 2)
    y = max(0, min(int(sh * 0.05), max(0, sh - h - 20)))
    try:
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    except Exception:
        pass
    return w, h


def center_on(win, parent, width, height):
    """以 parent 为参照居中（parent 为空则等同于 place）"""
    if parent is None:
        return place(win, width, height)
    try:
        parent.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except Exception:
        return place(win, width, height)
    w, h = clamp_size(win, width, height)
    sw, sh = screen_size(win)
    x = max(0, min(px + (pw - w) // 2, sw - w))
    y = max(0, min(py + (ph - h) // 2, sh - h - 20))
    try:
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
    except Exception:
        pass
    return w, h
