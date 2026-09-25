# -*- coding: utf-8 -*-
"""开发期验证：三个界面子进程能否正常弹出、截图、回传结果。

用法: python dev_test_ui.py [mode ...]    默认测 basemap search settings
"""
from __future__ import print_function

import ctypes
import io
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

from PIL import Image

PKG = r"D:\Work\projects\arcmap\TiandituTools"
PYW = r"C:\Python27\ArcGIS10.4\pythonw.exe"
TMPD = r"D:\Work\projects\arcmap\_ui_tmp"

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
EnumWindows = u32.EnumWindows
CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BI(ctypes.Structure):
    _fields_ = [("bmiHeader", BIH), ("bmiColors", wintypes.DWORD * 3)]


def cap(hwnd, path):
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)
    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    return (w, h)


def windows_of(pid):
    res = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            t = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, t, 512)
            if t.value:
                res.append((hwnd, t.value))
        return True

    EnumWindows(CB(cb), 0)
    return res


def test_mode(mode, close_after=7, pick=True):
    print("\n########## mode = %s ##########" % mode)
    if not os.path.isdir(TMPD):
        os.makedirs(TMPD)
    in_path = os.path.join(TMPD, "%s_in.json" % mode)
    out_path = os.path.join(TMPD, "%s_out.json" % mode)
    with io.open(in_path, "wb") as f:
        f.write(b"{}")
    if os.path.exists(out_path):
        os.remove(out_path)

    p = subprocess.Popen([PYW, os.path.join(PKG, "ui_main.py"), mode, in_path, out_path],
                         cwd=PKG)
    print("  子进程 PID:", p.pid)
    time.sleep(close_after)
    wins = windows_of(p.pid)
    print("  可见窗口:", [(h, t) for h, t in wins])
    if wins:
        hwnd, title = wins[0]
        size = cap(hwnd, os.path.join(r"D:\Work\projects\arcmap\_ui_%s.png" % mode))
        print("  截图 _ui_%s.png 尺寸=%s" % (mode, size))
        if pick and mode == "basemap":
            # 键盘下移 + 回车，模拟"选中第一项并添加"
            u32.SetForegroundWindow(hwnd)
            time.sleep(0.5)
            for _ in range(2):
                u32.keybd_event(0x28, 0, 0, 0)       # VK_DOWN
                u32.keybd_event(0x28, 0, 2, 0)
                time.sleep(0.2)
            u32.keybd_event(0x0D, 0, 0, 0)           # VK_RETURN
            u32.keybd_event(0x0D, 0, 2, 0)
        else:
            u32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
    else:
        print("  !! 无可见窗口, rc=%s" % p.poll())

    for _ in range(60):
        if p.poll() is not None:
            break
        time.sleep(0.25)
    rc = p.poll()
    if rc is None:
        print("  未自行退出，强制结束")
        subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        print("  退出码:", rc)
    if os.path.exists(out_path):
        raw = io.open(out_path, "rb").read().decode("utf-8")
        print("  回传结果:", raw[:300] if raw.strip() else "(空)")
    else:
        print("  无结果文件（等价于用户取消）")
    return rc


def main():
    modes = sys.argv[1:] or ["basemap", "search", "settings"]
    for m in modes:
        test_mode(m)
    print("\n=== UI 测试完成 ===")


if __name__ == "__main__":
    main()
