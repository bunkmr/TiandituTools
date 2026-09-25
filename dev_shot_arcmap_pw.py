# -*- coding: utf-8 -*-
"""用 PrintWindow 抓 ArcMap 自己的像素（即使被别的窗口挡住也能抓到）。"""
import ctypes
from ctypes import wintypes

u32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    u32.SetProcessDPIAware()

EnumWindows = u32.EnumWindows
CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
found = []


def cb(h, l):
    n = u32.GetWindowTextLengthW(h)
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, buf, n + 1)
        t = buf.value
        if "ArcMap" in t and u32.IsWindowVisible(h):
            r = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            found.append((h, t, r.left, r.top, r.right, r.bottom))
    return True


EnumWindows(CB(cb), 0)
print("屏幕:", u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))
for f in found:
    print("  hwnd=%s title=%r rect=(%s,%s,%s,%s)" % f)

if not found:
    print("没找到 ArcMap 窗口")
    raise SystemExit(1)

h, title, l, t, r, b = max(found, key=lambda x: (x[4] - x[2]) * (x[5] - x[3]))
w, hh = r - l, b - t

hdc = u32.GetWindowDC(h)
mem = gdi32.CreateCompatibleDC(hdc)
bmp = gdi32.CreateCompatibleBitmap(hdc, w, hh)
gdi32.SelectObject(mem, bmp)

# PW_RENDERFULLCONTENT = 2（能抓到 DirectComposition 内容）
ok = u32.PrintWindow(h, mem, 2)
print("PrintWindow ->", ok)

buf_sz = w * hh * 4
buf = ctypes.create_string_buffer(buf_sz)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


bi = BITMAPINFOHEADER()
bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bi.biWidth = w
bi.biHeight = -hh          # 负值 = 自顶向下
bi.biPlanes = 1
bi.biBitCount = 32
bi.biCompression = 0
gdi32.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0)

from PIL import Image, ImageOps
im = Image.frombuffer("RGBA", (w, hh), buf, "raw", "BGRA", 0, 1).convert("RGB")
try:
    im = ImageOps.autocontrast(im)
except Exception:
    pass
s = min(1.0, 1600.0 / max(w, hh))
if s < 1.0:
    im = im.resize((int(w * s), int(hh * s)), 1)
out = r"D:\Work\projects\arcmap\_arcmap_pw.jpg"
im.save(out, quality=85)
print("saved", out, im.size)

gdi32.DeleteObject(bmp)
gdi32.DeleteDC(mem)
u32.ReleaseDC(h, hdc)
