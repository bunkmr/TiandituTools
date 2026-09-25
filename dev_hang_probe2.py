# -*- coding: utf-8 -*-
"""挂起现场探针：尽量复现「ArcMap 主线程卡死」，并抓下当时的现场。

抓三样东西：
  1. 窗口响应性 —— SendMessageTimeout(WM_NULL)，超时即判定「未响应」
  2. ArcMap 进程的 TCP 连接（netstat -ano）—— 卡在哪个 socket 上，状态是什么
  3. 中转日志时间线 —— 卡住前最后请求了哪张瓦片

用法: <py27> dev_hang_probe2.py [观察秒数]
"""
from __future__ import print_function, unicode_literals

import ctypes
import ctypes.wintypes as wt
import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

import dev_e2e_run as E                                   # noqa: E402

ARCMAP = u"C:/Program Files (x86)/ArcGIS/Desktop10.4/bin/ArcMap.exe"
APPD = os.path.join(os.environ.get("APPDATA") or "", "TiandituTools")
SELFTEST_LOG = os.path.join(APPD, "selftest.log")
TILE_LOG = os.path.join(APPD, "tile_proxy.log")

u32 = ctypes.windll.user32


def arcmap_hwnd():
    found = []

    def cb(h, l):
        n = u32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            if b.value.endswith(u"- ArcMap"):
                found.append((h, b.value))
        return True

    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                       ctypes.c_void_p)(cb), 0)
    return found[0] if found else (0, u"")


def responsive(h, ms=2500):
    """返回 (bool, 耗时秒)。False = 未响应"""
    t0 = time.time()
    res = ctypes.c_ulong()
    ok = u32.SendMessageTimeoutW(h, 0, 0, 0, 0x0002, ms, ctypes.byref(res))
    return bool(ok), time.time() - t0


def netstat(pid):
    try:
        out = subprocess.check_output(["netstat", "-ano"], creationflags=E.CREATE_NO_WINDOW)
    except Exception as e:
        return [u"netstat 失败 %r" % (e,)]
    lines = out.decode("gbk", "ignore").splitlines()
    return [l.strip() for l in lines if re.search(r"\s%d\s*$" % pid, l)]


def tail(path, n=12):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 180

    for pid in E.arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid], creationflags=E.CREATE_NO_WINDOW)
    time.sleep(2)
    for p in (SELFTEST_LOG, TILE_LOG):
        try:
            os.remove(p)
        except Exception:
            pass

    env = {}
    for k, v in os.environ.items():
        env[str(k)] = str(v)
    env[str("TIANDITU_SELFTEST")] = str("img,cia")
    env[str("TIANDITU_SELFTEST_QUIET")] = str("1")
    env[str("TIANDITU_NO_UI")] = str("1")
    proc = subprocess.Popen([ARCMAP], env=env,
                            creationflags=E.CREATE_NEW_CONSOLE, close_fds=True)
    pid = proc.pid
    E.log("=== ArcMap pid=%d ===" % pid)

    t0 = time.time()
    port = None
    last_tiles = 0
    hang_reported = False
    while time.time() - t0 < secs:
        time.sleep(3)
        if not E.alive(pid):
            E.log("!!! ArcMap 已退出（t=%ds）" % int(time.time() - t0))
            break
        h, title = arcmap_hwnd()
        if not h:
            E.log("  t=%3ds 找不到 ArcMap 主窗口" % int(time.time() - t0))
            continue
        ok, dt = responsive(h)
        if port is None:
            for ln in tail(SELFTEST_LOG, 40):
                m = re.search(u"中转端口=(\\d+)", ln)
                if m:
                    port = m.group(1)
        tiles = [l for l in tail(TILE_LOG, 5000) if u"[tile]" in l]
        E.log("  t=%3ds 响应=%-5s(%.2fs) 瓦片累计=%3d(本次+%d) port=%s"
              % (int(time.time() - t0), ok, dt, len(tiles),
                 len(tiles) - last_tiles, port))
        if len(tiles) != last_tiles:
            for ln in tiles[last_tiles:][-3:]:
                E.log("        " + re.sub(u"tk=[a-f0-9]+", u"tk=KEY", ln))
            last_tiles = len(tiles)
        if not ok and not hang_reported:
            hang_reported = True
            E.log("!!!! 判定为未响应，抓现场 !!!!")
            for l in netstat(pid):
                E.log("    [net] " + l)
            for ln in tail(SELFTEST_LOG, 15):
                E.log("    [self] " + ln)
            E.log("    [提示] 若 [net] 里大量 ESTABLISHED/SYN_SENT 指向 "
                  "127.0.0.1:%s，说明卡在中转这条链上" % port)
        elif ok and hang_reported:
            E.log("  （又恢复响应了）")
            hang_reported = False

    h, title = arcmap_hwnd()
    if h:
        ok, dt = responsive(h, 4000)
        E.log("=== 收尾：响应=%s(%.2fs) 存活=%s ===" % (ok, dt, E.alive(pid)))
        E.log("=== 现场 netstat ===")
        for l in netstat(pid):
            E.log("  " + l)
    E.log("=== 中转日志末尾 ===")
    for ln in tail(TILE_LOG, 15):
        E.log("  " + re.sub(u"tk=[a-f0-9]+", u"tk=KEY", ln))
    E.log("=== selftest 末尾（含卡顿记录）===")
    for ln in tail(SELFTEST_LOG, 20):
        E.log("  " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
