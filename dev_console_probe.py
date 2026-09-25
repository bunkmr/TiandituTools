# -*- coding: utf-8 -*-
"""诊断实验：抓出 ARCMAP 里 DFORRT 那条「还没打印出来就崩掉」的 Fortran 消息。

原理
----
报错固定是 `forrtl: severe (38): error during write, unit 0, file CONOUT$`。
unit 0 = stderr，文件 = CONOUT$（控制台）。也就是说：**Fortran 运行时本来想
打印一条消息，但写控制台失败，于是 severe(38) 并中止进程**。真正想看的那条
消息就被吞掉了。

所以要设法让这次写「成功」：
  1. CREATE_NEW_CONSOLE —— 给 ArcMap 一个属于它自己的、生命周期稳定的真控制台
     （不是继承我们 bash 那个随时会被回收的 ConPTY）；
  2. FOR_DIAGNOSTIC_LOG_FILE / FOR_DEFAULT_DIAGNOSTIC_FILE —— 让 Intel/Compaq
     Fortran 运行时把诊断信息写进文件，绕开控制台。

同时全程截图，万一弹了 Fortran 对话框也能直接看到。

用法：python dev_console_probe.py [启动等待秒] [观察秒]
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
LOGDIR = os.path.join(PROJ, "_fortran")

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        u32.SetProcessDPIAware()
    except Exception:
        pass


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
                out.append((h, t))
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


def shot(tag):
    try:
        from PIL import ImageGrab
        im = ImageGrab.grab(all_screens=True).convert("RGB")
        w, h = im.size
        s = min(1.0, 1900.0 / max(w, h))
        if s < 1.0:
            im = im.resize((int(w * s), int(h * s)), 1)
        p = os.path.join(LOGDIR, "%s.jpg" % tag)
        im.save(p, quality=78)
        log("截图 -> %s" % p)
    except Exception as e:
        log("截图失败 %r" % (e,))


def run_py27(script, extra_env=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TIANDITU_NO_UI"] = "1"
    if extra_env:
        env.update(extra_env)
    try:
        out = subprocess.check_output(
            [PY27, "-u", script], cwd=PROJ, env=env,
            stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW, timeout=180)
    except subprocess.CalledProcessError as e:
        out = e.output
    except Exception as e:
        return "运行 %s 失败: %r" % (script, e)
    txt = out.decode("utf-8", "replace")
    return "\n".join(l for l in txt.splitlines()
                     if not any(k in l for k in ("sitecustomize", "Code page",
                                                 "WARNING")))


def main():
    wait_s = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    watch_s = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)
    else:
        for fn in os.listdir(LOGDIR):
            try:
                os.remove(os.path.join(LOGDIR, fn))
            except Exception:
                pass

    diag = os.path.join(LOGDIR, "fortran_diag.txt")
    for pid in arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=CREATE_NO_WINDOW)
    time.sleep(2)

    log("=== 以「自带独立控制台」方式启动 ArcMap ===")
    env = dict(os.environ)
    env["FOR_DIAGNOSTIC_LOG_FILE"] = diag
    env["FOR_DEFAULT_DIAGNOSTIC_FILE"] = diag
    env["FORT_BUFFERED"] = "FALSE"
    proc = subprocess.Popen([ARCMAP],
                            creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP,
                            env=env, close_fds=True)
    log("pid=%d  控制台=新建  FOR_DIAGNOSTIC_LOG_FILE=%s" % (proc.pid, diag))

    for i in range(wait_s):
        time.sleep(1)
        if not alive(proc.pid):
            log("!!! 启动阶段就死了（%ds）" % (i + 1))
            shot("died_early")
            return 1
    log("启动稳定 %ds，开始加底图" % wait_s)

    log(run_py27("dev_test_apply.py"))

    t0 = time.time()
    while time.time() - t0 < watch_s:
        time.sleep(4)
        el = time.time() - t0
        up = alive(proc.pid)
        ts = [t for (_h, t) in titles()
              if any(k in t for k in ("Arc", "ESRI", "Fortran", "Runtime",
                                      "错误", "严重", "Visual", "控制台"))]
        log("t=%3ds alive=%-5s pids=%s 窗口=%s" % (el, up, arcmap_pids(), ts[:5]))
        if not up:
            log("!!! ArcMap 于加图层后 %.0fs 死亡" % el)
            time.sleep(1)
            shot("died_after_add")
            break

    if os.path.isfile(diag):
        log("=== Fortran 诊断文件 ===")
        try:
            with open(diag, "rb") as f:
                log(f.read().decode("utf-8", "replace")[:2000])
        except Exception as e:
            log("读取失败 %r" % (e,))
    else:
        log("（没有生成 Fortran 诊断文件）")

    log("=== 兜底：再看 ArcMap 是否仍在 ===")
    log("pids=%s" % arcmap_pids())
    run_py27("_probe_layers.py", extra_env=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
