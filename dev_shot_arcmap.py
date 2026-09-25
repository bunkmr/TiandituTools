"""抓取 ArcMap 主窗口截图（Python 3 + PIL）"""
import ctypes
from ctypes import wintypes

from PIL import ImageGrab

u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    u32.SetProcessDPIAware()

EnumWindows = u32.EnumWindows
CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

found = []


def cb(h, l):
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    n = u32.GetWindowTextLengthW(h)
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, buf, n + 1)
        title = buf.value
        if "ArcMap" in title and u32.IsWindowVisible(h):
            r = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            found.append((h, pid.value, title, r.left, r.top, r.right, r.bottom))
    return True


EnumWindows(CB(cb), 0)
print("屏幕:", u32.GetSystemMetrics(0), u32.GetSystemMetrics(1))
for f in found:
    print("  hwnd=%s pid=%s title=%r rect=(%s,%s,%s,%s)" % (f[0], f[1], f[2], f[3], f[4], f[5], f[6]))

if found:
    h, pid, title, l, t, r, b = found[0]
    u32.SetForegroundWindow(h)
    im = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).convert("RGB")
    w, hh = im.size
    s = min(1.0, 1600.0 / max(w, hh))
    if s < 1.0:
        im = im.resize((int(w * s), int(hh * s)), 1)
    out = r"D:\Work\projects\arcmap\_arcmap_win.jpg"
    im.save(out, quality=85)
    print("saved", out, im.size)
else:
    print("没找到 ArcMap 窗口")
