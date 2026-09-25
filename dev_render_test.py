# -*- coding: utf-8 -*-
"""决定性实验：外部进程加底图 -> 趁进程活着截图（看能不能渲染）
              -> 进程退出 -> 观察 ArcMap 是否随即死亡。

要回答两个问题
--------------
Q1 图层是「加进去了但画不出来」，还是「画得出来」？
    —— 在加图层的那个进程还活着的时候截图，排除掉代理失效的干扰。
Q2 ArcMap 的死亡是否由「加图层的进程退出」触发？
    —— 图层对象是在**外部进程**里 new 出来的（esriCarto.WMTSLayer 是 in-proc
       组件），经 COM 跨进程封送进 ArcMap。外部进程一退，ArcMap 手里就只剩
       一个断了的代理 —— 重绘时就会崩。
"""
from __future__ import print_function

import ctypes
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
PY27 = r"C:\Python27\ArcGIS10.4\python.exe"
PY3 = r"C:\Users\bunkr\.workbuddy\binaries\python\versions\3.13.12\python.exe"
PROJ = r"D:\Work\projects\arcmap"
OUT = os.path.join(PROJ, "_render")

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
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


def fortran_dlgs():
    out = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, l):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                if any(k in buf.value for k in ("Fortran", "Runtime",
                                                "严重", "已停止", "无响应",
                                                "错误", "Error")):
                    out.append(buf.value)
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
    return [l.split('","')[1] for l in out.decode("gbk", "replace").splitlines()
            if "ArcMap.exe" in l]


def shot(tag):
    try:
        subprocess.call([PY3, "dev_shot_arcmap_pw.py"], cwd=PROJ,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW, timeout=60)
        src = os.path.join(PROJ, "_arcmap_pw.jpg")
        if os.path.isfile(src):
            dst = os.path.join(OUT, "%s.jpg" % tag)
            shutil.copy(src, dst)
            log("  截图 -> %s" % dst)
    except Exception as e:
        log("  截图失败 %r" % (e,))


def main():
    hold = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    after = int(sys.argv[2]) if len(sys.argv) > 2 else 120

    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)

    for pid in arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=CREATE_NO_WINDOW)
    time.sleep(2)

    log("=== 启动 ArcMap（无控制台，等价双击）===")
    p = subprocess.Popen([ARCMAP],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
    log("ArcMap pid=%d" % p.pid)
    for _ in range(40):
        time.sleep(1)
        if not alive(p.pid):
            log("!!! 启动阶段就死了")
            return 1
    log("启动稳定，开始外部进程加底图（进程保持 %ds）" % hold)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["TIANDITU_NO_UI"] = "1"
    env["HOLD_SECONDS"] = str(hold)
    child = subprocess.Popen([PY27, "-u", "dev_test_lifetime.py"],
                             cwd=PROJ, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)

    # 趁子进程活着，每 15 秒截一张
    t0 = time.time()
    n = 0
    while child.poll() is None and time.time() - t0 < hold + 60:
        time.sleep(15)
        n += 1
        up = alive(p.pid)
        log("  [creator alive] t=%ds ArcMap=%s 弹窗=%s"
            % (time.time() - t0, up, fortran_dlgs()[:2]))
        shot("alive_%02d" % n)
        if not up:
            log("  !!! 加图层的进程还活着，ArcMap 已死")
            break

    try:
        out = child.communicate(timeout=30)[0].decode("utf-8", "replace")
    except Exception:
        child.kill()
        out = b""
    out = out or b""
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    keep = [l for l in out.splitlines()
            if not any(k in l for k in ("sitecustomize", "Code page", "WARNING"))]
    log("=== 加图层进程输出 ===")
    for l in keep[:20]:
        log("   " + l)

    log("=== 加图层进程已退出（ArcMap=%s），继续观察 %ds ==="
        % (alive(p.pid), after))
    t1 = time.time()
    while time.time() - t1 < after:
        time.sleep(6)
        up = alive(p.pid)
        log("  [t+%ds] ArcMap=%s pids=%s 弹窗=%s"
            % (time.time() - t1, up, arcmap_pids(), fortran_dlgs()[:2]))
        if not up:
            log("!!! ArcMap 在加图层进程退出后 %.0fs 死亡" % (time.time() - t1))
            time.sleep(1)
            shot("died")
            break
    else:
        log("=== ArcMap 在加图层进程退出后 %ds 依然存活 ===" % after)
        shot("survived")

    log("画布截图：")
    for fn in sorted(os.listdir(OUT)):
        log("   %s" % fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
