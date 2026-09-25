# -*- coding: utf-8 -*-
"""列出所有可见顶层窗口及其所属进程 —— 用来确认「Visual Fortran run-time error」
这个对话框到底是 ArcMap.exe 弹的，还是我们那个 python 子进程弹的。
"""
from __future__ import print_function

import ctypes
import subprocess
import sys

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def proc_name(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(600)
        size = ctypes.c_ulong(600)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return "?"
    finally:
        k32.CloseHandle(h)


rows = []
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def cb(h, l):
    if not u32.IsWindowVisible(h):
        return True
    n = u32.GetWindowTextLengthW(h)
    if not n:
        return True
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(h, buf, n + 1)
    title = buf.value.strip()
    if not title:
        return True
    pid = ctypes.c_ulong()
    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(h, cls, 256)
    rows.append((pid.value, title, cls.value, h))
    return True


u32.EnumWindows(CB(cb), 0)

print("=== 全部可见窗口 ===")
for pid, title, cls, h in rows:
    print("  pid=%-6d cls=%-22s %s" % (pid, cls, title))

print()
print("=== 含 Arc / Fortran / Runtime / 错误 的窗口 ===")
for pid, title, cls, h in rows:
    if any(k in title for k in ("Arc", "Fortran", "Runtime", "错误", "严重",
                                "Visual", "python")):
        print("  pid=%-6d cls=%-22s %s" % (pid, cls, title))
        print("        -> %s" % proc_name(pid))

print()
print("=== 各进程一览 ===")
try:
    out = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"], creationflags=0x08000000)
    for line in out.decode("gbk", "replace").splitlines():
        low = line.lower()
        if any(k in low for k in ("arcmap", "python", "pythonw", "cmd", "conhost")):
            print("  " + line)
except Exception as e:
    print("tasklist 失败 %r" % (e,))
