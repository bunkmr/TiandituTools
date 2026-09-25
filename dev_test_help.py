# -*- coding: utf-8 -*-
"""逐页截图检查帮助窗口 / 图源管理窗口 / 底图窗口（开发工具，不随插件发布）。

为什么要"截图看"而不是"看代码"：帮助页里全是中文、缩进、等宽示例，
以及一张 GIF 页眉和一张二维码占位图 —— 排版错位、字体缺失、
图片加载失败（Tk 8.5 不认 PNG 是踩过的坑）这些问题只有肉眼看得见。

做法：用 **ArcGIS 的 python 2.7** 起真实的独立界面进程（和 ArcMap 里
点按钮走的是同一条链路：ui_main.py <mode>），等窗口出现后截屏，
再杀掉进程。全程不碰 ArcMap。

用法：
    python dev_test_help.py            # 全部
    python dev_test_help.py help       # 只看帮助页
    python dev_test_help.py xyz        # 只看图源管理窗
"""

from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "TiandituTools")
MAIN = os.path.join(PKG, "ui_main.py")

PY_CANDIDATES = [
    r"C:\Python27\ArcGIS10.10\pythonw.exe",
    r"C:\Python27\ArcGIS10.8\pythonw.exe",
    r"C:\Python27\ArcGIS10.4\pythonw.exe",
    r"C:\Python27\pythonw.exe",
]

u32 = ctypes.windll.user32
u32.SetProcessDPIAware()


def find_python():
    for p in PY_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise SystemExit("找不到 ArcGIS Python 2.7 (pythonw.exe)")


def windows(substr):
    """枚举可见窗口 -> [(hwnd, title, l, t, r, b)]

    坐标用 **DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)**：
    它就是"屏幕上看得见的那一圈"（不含阴影、不含被 DPI 虚拟化后的偏差）。
    GetWindowRect 在"调用进程 DPI-aware、目标窗口 DPI-unaware"的组合下
    给出来的值会跟屏幕实况对不上，实测截出来的图会整体偏掉。
    """
    out = []
    dwm = ctypes.windll.dwmapi

    def cb(h, _l):
        n = u32.GetWindowTextLengthW(h)
        if n and u32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            if substr in buf.value:
                rc = wintypes.RECT()
                got = dwm.DwmGetWindowAttribute(
                    h, 9, ctypes.byref(rc), ctypes.sizeof(rc))   # 9 = FRAME_BOUNDS
                if got != 0 or rc.right - rc.left <= 0:
                    u32.GetWindowRect(h, ctypes.byref(rc))
                out.append((h, buf.value, rc.left, rc.top, rc.right, rc.bottom))
        return True

    u32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return out


def wait_window(substr, timeout=25.0):
    end = time.time() + timeout
    while time.time() < end:
        ws = windows(substr)
        if ws:
            return max(ws, key=lambda x: (x[4] - x[2]) * (x[5] - x[3]))
        time.sleep(0.25)
    return None


def shot(rect, out):
    l, t, r, b = rect[2], rect[3], rect[4], rect[5]
    img = ImageGrab.grab()
    W, H = img.size
    box = (max(0, min(l, W - 1)), max(0, min(t, H - 1)), min(r, W), min(b, H))
    crop = img.crop(box)
    crop.save(out)
    return crop


def shoot_mode(mode, payload, title_substr, out, extra_shots=()):
    """起一个界面进程 -> 截屏 -> 杀掉。

    extra_shots: [(页签标的, 输出文件名)]，会**再起一个进程**用
    payload={"tab": 页签标的} 直接打开那一页（比去点页签稳）。
    """
    py = find_python()
    tmpd = tempfile.mkdtemp(prefix="dev_help_")
    print("\n=== mode=%s ===" % mode)
    rc = _one(py, tmpd, mode, payload, out)
    if rc is None:
        return False
    for tab, name in extra_shots:
        _one(py, tmpd, mode, {"tab": tab}, os.path.join(HERE, name))
    return True


def _one(py, tmpd, mode, payload, out):
    import json

    in_path = os.path.join(tmpd, "in.json")
    out_path = os.path.join(tmpd, "out.json")
    with open(in_path, "wb") as f:
        f.write(json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"))
    if os.path.isfile(out_path):
        os.remove(out_path)

    proc = subprocess.Popen([py, MAIN, mode, in_path, out_path], cwd=PKG)
    rect = wait_window(u"天地图 Tools")
    if not rect:
        proc.kill()
        print("  ! 窗口没出现（mode=%s payload=%s）" % (mode, payload))
        return None

    time.sleep(2.2)           # 等 topmost 撤掉、图片解码完、Text 排版完成
    # 【必须在截屏前重新量一次窗口位置】窗口出生时在 Tk 的默认位置，
    # 之后才被 place()/fit() 挪到屏幕中间 —— 用出生时那个 rect 去裁，
    # 裁出来的图会整体偏掉（踩过）。
    fresh = wait_window(u"天地图 Tools", timeout=3.0)
    if fresh:
        rect = fresh
    crop = shot(rect, out)
    print("  + %s  %dx%d  %r  rect=%s" % (os.path.relpath(out, HERE),
                                          crop.size[0], crop.size[1], rect[1],
                                          rect[2:]))

    # 顺手统计一下"是不是一片空白"（背景 #FDFDFE / 白 / 深蓝页眉）
    px = crop.convert("RGB").load()
    nw = tot = 0
    for y in range(0, crop.size[1], 7):
        for x in range(0, crop.size[0], 7):
            tot += 1
            c = px[x, y]
            if c not in ((253, 253, 254), (255, 255, 255), (16, 74, 128),
                         (240, 240, 240), (247, 249, 250)):
                nw += 1
    print("      有内容采样 %d/%d (%.1f%%)" % (nw, tot, 100.0 * nw / max(1, tot)))

    proc.kill()
    try:
        proc.wait()
    except Exception:
        pass
    time.sleep(0.6)           # 等窗口真的消失，免得下一轮截到上一轮的残影
    return True


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if which in ("", "help"):
        shoot_mode(
            "help", None, u"帮助", os.path.join(HERE, "_help_1.png"),
            extra_shots=[
                (u"图源说明", "_help_2.png"),
                (u"自定义 XYZ", "_help_3.png"),
                (u"常见问题", "_help_4.png"),
                (u"关于", "_help_5.png"),
            ],
        )
    if which in ("", "xyz"):
        shoot_mode("xyz", None, u"图源管理", os.path.join(HERE, "_xyz_1.png"))
    if which in ("", "basemap"):
        shoot_mode("basemap", None, u"添加底图", os.path.join(HERE, "_basemap_1.png"))
    if which in ("", "settings"):
        shoot_mode("settings", None, u"设置", os.path.join(HERE, "_settings_1.png"),
                   extra_shots=[(u"图源管理", "_settings_2.png")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
