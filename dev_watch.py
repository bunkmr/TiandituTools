# -*- coding: utf-8 -*-
"""启动 ArcMap 并持续观察：进程存活 + 定时全屏截图。

用途：搞清 ArcMap 为什么启动后约 40~60 秒就消失。
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime

from PIL import ImageGrab

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
OUTDIR = r"D:\Work\projects\arcmap\_watch"
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    u32.SetProcessDPIAware()


def alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def titles():
    """当前所有可见顶层窗口标题"""
    out = []
    EnumWindows = u32.EnumWindows
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, l):
        if not u32.IsWindowVisible(h):
            return True
        n = u32.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            t = buf.value.strip()
            if t:
                out.append(t)
        return True

    EnumWindows(CB(cb), 0)
    return out


def log(*a):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"),
                       " ".join(str(x) for x in a)))
    sys.stdout.flush()


def main():
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    for fn in os.listdir(OUTDIR):
        try:
            os.remove(os.path.join(OUTDIR, fn))
        except Exception:
            pass

    log("启动 ArcMap ...")
    p = subprocess.Popen([ARCMAP])
    log("pid = %d" % p.pid)

    t0 = time.time()
    shot_i = 0
    died_at = None
    while time.time() - t0 < 110:
        el = time.time() - t0
        up = alive(p.pid)
        ts = titles()
        interesting = [t for t in ts
                       if any(k in t for k in ("Arc", "ESRI", "esri",
                                               "Runtime", "Error", "错误",
                                               "Microsoft Visual"))]
        log("t=%5.1fs alive=%-5s 相关窗口=%s" % (el, up, interesting[:4]))
        if not up and died_at is None:
            died_at = el
            log("!!! 进程结束于 %.1fs，退出码=%s" % (el, p.poll()))
            try:
                im = ImageGrab.grab(all_screens=True).convert("RGB")
                im.save(os.path.join(OUTDIR, "death_full.jpg"), quality=80)
                log("已保存死亡瞬间全屏截图")
            except Exception as e:
                log("截图失败 %r" % (e,))
            break
        # 每 8 秒截图
        if int(el) % 8 < 2:
            try:
                im = ImageGrab.grab(all_screens=True).convert("RGB")
                w, h = im.size
                s = min(1.0, 1600.0 / max(w, h))
                if s < 1.0:
                    im = im.resize((int(w * s), int(h * s)), 1)
                im.save(os.path.join(OUTDIR, "shot_%02d.jpg" % shot_i), quality=70)
                shot_i += 1
            except Exception:
                pass
        time.sleep(2)

    if died_at is None:
        log("观察结束：进程一直存活（>=110s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
