# -*- coding: utf-8 -*-
"""窗口结构探针：摸清 ArcMap 主窗口的子窗口布局（工具条在哪儿），
并排查意外出现的顶层窗口（例如标题为 "tk" 的 Tk 根窗口是哪个进程开的）。

用法: python dev_win_kids.py [观测秒数]
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
ROOT = os.path.dirname(os.path.abspath(__file__))
SHOT = os.path.join(ROOT, "_kids_shot.png")
PS1 = os.path.join(ROOT, "_ps_shot.ps1")

u32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindows = u32.EnumWindows
EnumChildWindows = u32.EnumChildWindows
CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def out(s):
    if isinstance(s, unicode):        # noqa: F821
        s = s.encode("utf-8")
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return (p.communicate()[0] or b"").decode("gbk", "replace")


def wtext(h):
    b = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(h, b, 512)
    return b.value


def wclass(h):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, b, 256)
    return b.value


def wrect(h):
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    return r


def win_pid(h):
    p = wintypes.DWORD()
    u32.GetWindowThreadProcessId(h, ctypes.byref(p))
    return p.value


def top_windows(pred=None):
    res = []

    def cb(h, _):
        if pred is None or pred(h):
            res.append(h)
        return True

    EnumWindows(CB(cb), 0)
    return res


def descendants(root, max_depth=6):
    rows = []

    def walk(h, depth):
        if depth > max_depth:
            return
        kids = []

        def cb(c, _):
            kids.append(c)
            return True

        EnumChildWindows(h, CB(cb), 0)
        for c in kids:
            rows.append((depth, c))
            walk(c, depth + 1)

    walk(root, 1)
    return rows


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    out("=== 屏幕/DPI ===")
    out("  DPI-unaware 视角: %dx%d" % (u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)))

    out("\n=== 当前所有顶层可见窗口（非 ArcMap）===")
    for h in top_windows(lambda x: u32.IsWindowVisible(x)):
        t = wtext(h)
        if u32.IsWindowVisible(h) and t:
            pid = win_pid(h)
            r = wrect(h)
            out("  pid=%-6d cls=%-24r title=%-30r rect=%s"
                % (pid, wclass(h), t, (r.left, r.top, r.right, r.bottom)))
    # 全量含隐藏的，找 "tk"
    out("\n=== 标题为 tk / Tk 的窗口（含隐藏）===")
    for h in top_windows():
        t = wtext(h)
        if t.strip().lower() in ("tk", "tk "):
            r = wrect(h)
            out("  hwnd=%s pid=%s cls=%r vis=%s rect=%s"
                % (h, win_pid(h), wclass(h), bool(u32.IsWindowVisible(h)),
                   (r.left, r.top, r.right, r.bottom)))

    out("\n=== 进程名对照 ===")
    txt = run_cmd(["tasklist", "/FO", "CSV", "/NH"])
    pids = set()
    for h in top_windows():
        if wtext(h).strip().lower() == "tk":
            pids.add(str(win_pid(h)))
    for line in txt.splitlines():
        parts = line.split('","')
        if len(parts) >= 2 and parts[1].strip('"') in pids:
            out("  " + line[:120])

    out("\n=== 启动 ArcMap，观测 %ds ===" % secs)
    p = subprocess.Popen([ARCMAP], creationflags=0x00000008)
    time.sleep(secs)
    if p.poll() is not None:
        out("  !! ArcMap 已退出 rc=%s" % p.poll())
        return 1

    wins = [h for h in top_windows(lambda x: win_pid(x) == p.pid and u32.IsWindowVisible(x))]
    if not wins:
        out("  !! 无可见顶层窗口")
        return 1
    mainw = max(wins, key=lambda h: (lambda r: (r.right - r.left) * (r.bottom - r.top))(wrect(h)))
    r = wrect(mainw)
    out("  主窗口 hwnd=%s cls=%r title=%r rect=%s size=%dx%d"
        % (mainw, wclass(mainw), wtext(mainw), (r.left, r.top, r.right, r.bottom),
           r.right - r.left, r.bottom - r.top))

    out("\n=== 子窗口树（深度<=5，只显示有 rect 的）===")
    for depth, h in descendants(mainw, 5):
        rr = wrect(h)
        w, ht = rr.right - rr.left, rr.bottom - rr.top
        if w < 4 or ht < 4:
            continue
        t = wtext(h)
        cls = wclass(h)
        out("  %s%-22r %-28r %s  %dx%d"
            % ("  " * depth, cls, t[:26], (rr.left, rr.top), w, ht))

    out("\n=== 截图 ===")
    if os.path.isfile(PS1):
        out("  " + run_cmd(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", PS1, SHOT]).strip())
    run_cmd(["taskkill", "/F", "/IM", "ArcMap.exe"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
