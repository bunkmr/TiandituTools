# -*- coding: utf-8 -*-
"""对照实验：把加载项临时移走，看 ArcMap 自己启动后会不会也「未响应」。

为什么要做这个：自检期间 ArcMap 会整段卡死（窗口标题变成「未响应」、
Windows 给它建了 Ghost 窗口）。必须分清是**我们代码**卡住了 ArcMap，
还是 ArcMap 自己在启动后就要去网络上耗一阵（10.4 连 ArcGIS Online 很容易这样）。

用法：python dev_ctrl_hang.py [观察秒数]
      python dev_ctrl_hang.py 150 --with-addin     # 保留加载项做对比

只做**可还原的改名**，结束时一定恢复。
"""
from __future__ import print_function

import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
CACHE = r"C:\Users\bunkr\AppData\Local\ESRI\Desktop10.4\AssemblyCache"
GUID = "{A1B2C3D4-1234-5678-9ABC-DEF012345678}"
ADDINS = r"C:\Users\bunkr\Documents\ArcGIS\AddIns\Desktop10.4"
STASH = r"D:\Work\projects\arcmap\_addin_removed_backup"

u32 = ctypes.windll.user32
_SIG = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def titles():
    out = []

    def cb(h, l):
        n = u32.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            t = buf.value
            if "ArcMap" in t:
                cls = ctypes.create_unicode_buffer(128)
                u32.GetClassNameW(h, cls, 128)
                out.append((t, cls.value))
        return True
    u32.EnumWindows(_SIG(cb), 0)
    return out


def state():
    ts = titles()
    if not ts:
        return "NO-WINDOW"
    if any("未响应" in t for t, c in ts):
        return "NOT-RESPONDING"
    if any(c.startswith("Afx") for t, c in ts):
        return "OK"
    return "OTHER:%r" % (ts[:2],)


def pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ArcMap.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    r = []
    for line in out.splitlines()[1:]:
        parts = [p.strip('"') for p in line.split('","')]
        if parts and parts[0].lower().startswith("arcmap"):
            r.append(parts[1])
    return r


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    keep = "--with-addin" in sys.argv

    print("== 停止 ArcMap ==")
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(2)

    moved = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if not keep:
        os.makedirs(STASH, exist_ok=True)
        for base in (CACHE, ADDINS):
            src = os.path.join(base, GUID)
            if os.path.exists(src):
                dst = os.path.join(STASH, "HANGCTRL_%s_%s_%s"
                                   % (os.path.basename(base), GUID, stamp))
                shutil.move(src, dst)
                moved.append((dst, src))
                print("   移走:", src)

    try:
        print("== 启动 ArcMap（%s）==" % ("保留加载项" if keep else "无加载项"))
        env = dict(os.environ)
        # 清掉自检开关，保证不跑我们的自检代码
        env.pop("TIANDITU_SELFTEST", None)
        env.pop("TIANDITU_NO_UI", None)
        proc = subprocess.Popen([ARCMAP], env=env,
                                creationflags=0x00000010)   # CREATE_NEW_CONSOLE
        print("   pid=%d" % proc.pid)

        t0 = time.time()
        last = None
        while time.time() - t0 < secs:
            st = state()
            el = time.time() - t0
            if st != last:
                print("   [%6.1fs] %s" % (el, st))
                last = st
            if proc.poll() is not None:
                print("   [%6.1fs] ArcMap 进程已退出 rc=%s" % (el, proc.returncode))
                break
            time.sleep(1.0)
        print("   最终状态: %s  存活=%s" % (state(), proc.poll() is None))
    finally:
        print("== 停止并恢复 ==")
        subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
        time.sleep(2)
        for dst, src in moved:
            if os.path.exists(src):
                print("   (目标已存在，先移开)", src)
                shutil.move(src, dst + "_dup")
            shutil.move(dst, src)
            print("   恢复:", src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
