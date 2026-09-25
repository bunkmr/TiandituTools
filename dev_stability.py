# -*- coding: utf-8 -*-
"""稳定性实验：以「完全脱离控制台」的方式启动 ArcMap，再加底图，观察是否崩溃。

关键点
------
ArcMap 是 32 位 GUI 程序，但它会**继承父进程的控制台**。DFORRT.DLL（Fortran
运行时）在报错时要往 CONOUT$（控制台屏幕缓冲区）写日志；如果它继承的是一个
已经死掉/被回收的控制台，这次写就会失败，Fortran 运行时随即 severe(38) 并
中止整个进程 —— 表现就是 ArcMap 毫无征兆地消失。

所以本脚本用 DETACHED_PROCESS 启动 ArcMap：不给它任何控制台，与用户双击
快捷方式完全等价。这样才能分清「插件的问题」和「启动方式的问题」。

用法：
    python dev_stability.py [等待秒数] [观察秒数]
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
PY27 = r"C:\Python27\ArcGIS10.4\python.exe"
PROJ = r"D:\Work\projects\arcmap"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32


def log(*a):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"),
                       " ".join(str(x) for x in a)))
    sys.stdout.flush()


def alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def titles():
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
            if t:
                out.append(t)
        return True

    u32.EnumWindows(CB(cb), 0)
    return out


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


def launch_detached():
    """完全脱离控制台启动 ArcMap"""
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        p = subprocess.Popen([ARCMAP], creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                             close_fds=True)
        return p, "DETACHED|BREAKAWAY"
    except Exception:
        p = subprocess.Popen([ARCMAP], creationflags=flags, close_fds=True)
        return p, "DETACHED"


def run_py27(script, env_extra=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TIANDITU_NO_UI"] = "1"
    if env_extra:
        env.update(env_extra)
    try:
        out = subprocess.check_output(
            [PY27, "-u", script], cwd=PROJ, env=env,
            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW, timeout=180)
    except subprocess.CalledProcessError as e:
        out = e.output
    except Exception as e:
        return "运行 %s 失败: %r" % (script, e)
    txt = out.decode("utf-8", "replace")
    keep = [l for l in txt.splitlines()
            if not any(k in l for k in ("sitecustomize", "Code page", "WARNING"))]
    return "\n".join(keep)


def main():
    wait_s = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    watch_s = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    log("=== 清场：结束残留 ArcMap ===")
    for pid in arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=CREATE_NO_WINDOW)
    time.sleep(2)

    log("=== 以「无控制台」模式启动 ArcMap（等价双击）===")
    proc, how = launch_detached()
    log("pid=%d  启动方式=%s" % (proc.pid, how))

    for i in range(wait_s):
        time.sleep(1)
        if i % 10 == 9:
            log("  启动等待 %ds，alive=%s" % (i + 1, alive(proc.pid)))
        if not alive(proc.pid):
            log("!!! ArcMap 在启动后 %ds 就死了（还没做任何操作）" % (i + 1))
            return 1

    log("=== 启动稳定（%ds 无操作仍存活），现在加底图 ===" % wait_s)
    log(run_py27("dev_test_apply.py"))

    t0 = time.time()
    died = None
    while time.time() - t0 < watch_s:
        time.sleep(5)
        el = time.time() - t0
        up = alive(proc.pid)
        ts = [t for t in titles()
              if any(k in t for k in ("Arc", "ESRI", "Fortran", "Runtime",
                                      "错误", "严重", "Visual"))]
        log("t=%3ds alive=%-5s pids=%s 窗口=%s"
            % (el, up, arcmap_pids(), ts[:4]))
        if not up:
            died = el
            break

    if died is None:
        log("=== 结论：加底图后 %ds 内 ArcMap 一直存活 ===" % watch_s)
    else:
        log("=== 结论：加底图后 %.0fs ArcMap 死亡 ===" % died)

    try:
        out = run_py27("_probe_layers.py")
        log("图层复查:\n%s" % out)
    except Exception as e:
        log("图层复查失败 %r" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
