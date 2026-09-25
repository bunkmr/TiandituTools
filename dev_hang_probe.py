# -*- coding: utf-8 -*-
"""复现「ArcMap 未响应」并抓现场：网络连接、线程数、CPU、窗口状态。

重点看三样：
  1. 卡住时 ArcMap 有没有挂着 TCP 连接（ESTABLISHED / SYN_SENT / TIME_WAIT）；
  2. 系统代理（dev-sidecar 之类）有没有拦住本地回环请求；
  3. 主线程是不是真的在空转（CPU）。

用法：python dev_hang_probe.py [观察秒数]
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
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
    if any("未响应" in t for t, c in ts):
        return "NOT-RESPONDING"
    if any(c.startswith("Afx") for t, c in ts):
        return "OK"
    return "OTHER"


def pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ArcMap.exe", "/FO", "CSV"],
                         capture_output=True, text=True).stdout
    r = []
    for line in out.splitlines()[1:]:
        p = [q.strip('"') for q in line.split('","')]
        if p and p[0].lower().startswith("arcmap"):
            r.append(p[1])
    return r


def netstat(pid=None):
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        if "TCP" not in line:
            continue
        cols = line.split()
        if len(cols) < 5:
            continue
        if pid and cols[-1] != str(pid):
            continue
        if not pid and cols[-1] not in ("0", "4"):
            pass
        rows.append((cols[1], cols[2], cols[3], cols[-1]))
    return rows


def proxy_settings():
    import winreg
    p = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, p) as k:
        out = {}
        for n in ("ProxyEnable", "ProxyServer", "ProxyOverride",
                  "AutoConfigURL", "AutoDetect"):
            try:
                out[n] = winreg.QueryValueEx(k, n)[0]
            except FileNotFoundError:
                out[n] = None
    return out


def main():
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    print("== 代理设置 ==")
    for k, v in proxy_settings().items():
        print("   %-14s = %r" % (k, v))

    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(2)

    env = dict(os.environ)
    env["TIANDITU_SELFTEST"] = "img,cia"
    env["TIANDITU_NO_UI"] = "1"
    print("== 启动 ArcMap（带自检）==")
    proc = subprocess.Popen([ARCMAP], env=env, creationflags=0x00000010)
    print("   pid=%d" % proc.pid)

    t0 = time.time()
    last = None
    hung_since = None
    probes = 0
    while time.time() - t0 < secs:
        st = state()
        el = time.time() - t0
        if st != last:
            print("   [%6.1fs] 状态 = %s" % (el, st))
            if st == "NOT-RESPONDING":
                hung_since = el
            last = st
        if st == "NOT-RESPONDING" and probes < 2 and hung_since is not None \
                and el - hung_since > 12:
            probes += 1
            print("   [%6.1fs] ---- 卡死现场 #%d ----" % (el, probes))
            rows = netstat(proc.pid)
            print("      ArcMap 持有 TCP 连接 %d 条:" % len(rows))
            for r in rows[:25]:
                print("        %-24s -> %-24s %-12s" % (r[0], r[1], r[2]))
            ps = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process -Id %d | Select-Object -ExpandProperty Threads "
                 "| Measure-Object | Select-Object -ExpandProperty Count"
                 % proc.pid],
                capture_output=True, text=True).stdout.strip()
            print("      线程数:", ps)
            cpu = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-Process -Id %d).TotalProcessorTime.TotalSeconds" % proc.pid],
                capture_output=True, text=True).stdout.strip()
            time.sleep(3)
            cpu2 = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-Process -Id %d).TotalProcessorTime.TotalSeconds" % proc.pid],
                capture_output=True, text=True).stdout.strip()
            print("      CPU: %s -> %s (3s 内 +%.2fs)"
                  % (cpu, cpu2, float(cpu2 or 0) - float(cpu or 0)))
        time.sleep(1.0)

    print("   最终状态: %s" % state())
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
