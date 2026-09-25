# -*- coding: utf-8 -*-
"""监视已在运行的 ArcMap.exe 是否存活（不自己启动），供存活实验使用。"""
import ctypes
import subprocess
import sys
import time
from datetime import datetime

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 200.0
CREATE_NO_WINDOW = 0x08000000


def arcmap_pids():
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq ArcMap.exe", "/FO", "CSV", "/NH"],
            creationflags=CREATE_NO_WINDOW)
    except Exception:
        return []
    pids = []
    for line in out.decode("gbk", "replace").splitlines():
        if "ArcMap.exe" in line:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1:
                pids.append(parts[1])
    return pids


def titles():
    u32 = ctypes.windll.user32
    out = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, l):
        if not u32.IsWindowVisible(h):
            return True
        n = u32.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            t = buf.value.strip()
            if "Arc" in t or "Runtime" in t or "严重" in t:
                out.append(t)
        return True

    u32.EnumWindows(CB(cb), 0)
    return out


t0 = time.time()
prev = None
while time.time() - t0 < DURATION:
    pids = arcmap_pids()
    state = "alive" if pids else "GONE"
    if state != prev:
        print("[%s] t=%6.1fs %s pids=%s windows=%s"
              % (datetime.now().strftime("%H:%M:%S"), time.time() - t0, state, pids, titles()))
        sys.stdout.flush()
        prev = state
    time.sleep(2)
print("[%s] 监视结束（%.0fs）" % (datetime.now().strftime("%H:%M:%S"), DURATION))
