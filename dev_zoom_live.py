# -*- coding: utf-8 -*-
"""外部驱动的「真实缩放」实验：自检只加图层，缩放由本脚本一步步做。

为什么要把缩放搬到外部
----------------------
自检在主线程里连续快速改范围时，几次绘制互相覆盖，「哪一档画了、哪一档没画」
说不清（实测被这个坑过）。本脚本改成：一次只改一个范围 -> 等 8 秒 ->
抓屏（用户视角）-> 数瓦片 -> 再下一档。这样每一档的因果是干净的。

同时它也回答最核心的那个问题：
**缩放之后，ArcMap 到底有没有去取新一级的瓦片？**

用法: <py27> dev_zoom_live.py [总等待秒]
"""
from __future__ import print_function, unicode_literals

import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

import dev_e2e_run as E                                  # noqa: E402

ARCMAP = u"C:/Program Files (x86)/ArcGIS/Desktop10.4/bin/ArcMap.exe"
PY3 = u"C:/Python314/python.exe"
PY27 = u"C:/Python27/ArcGIS10.4/python.exe"
GRAB = os.path.join(HERE, u"_grab_screen.py")
# 注意：本模块开了 unicode_literals，`r"C:\Users\..."` 会变成 unicode 原始串，
# `\U` 会被当成 unicode 转义报 SyntaxError —— 一律用正斜杠，省事。
CACHE = (u"C:/Users/bunkr/AppData/Local/ESRI/Desktop10.4/AssemblyCache"
         u"/{A1B2C3D4-1234-5678-9ABC-DEF012345678}")
APPD = os.path.join(os.environ.get("APPDATA") or "", "TiandituTools")
SELFTEST_LOG = os.path.join(APPD, "selftest.log")
TILE_LOG = os.path.join(APPD, "tile_proxy.log")

sys.path.insert(0, os.path.join(HERE, u"TiandituTools"))
import tile_proxy                                         # noqa: E402


def relay_stats():
    """直接问中转服务要统计（走 /stats，不经代理）。"""
    p = tile_proxy.port() or tile_proxy.read_port_file()[0]
    if not p:
        return u"(无中转)"
    try:
        st, body = tile_proxy._local_get(p, "/stats", timeout=3)
        import json
        d = json.loads(body.decode("utf-8", "replace"))
        return (u"port=%s 瓦片=%s 缓存命中=%s 平均=%sms 错误=%s DNS=%s"
                % (d["port"], d["tiles"], d["cached"], d["avg_ms"], d["errors"],
                   d["dns"]))
    except Exception as e:
        return u"(取统计失败 %r)" % (e,)


def start_relay():
    """先把独立中拉起（由本脚本当父进程；端口固定 17817）。

    必须由**外部**先起好：ArcMap 自己起的话，一旦 ArcMap 被 taskkill，
    子进程会跟着没，后面几档缩放就没中转了。
    """
    p, pid = tile_proxy.read_port_file()
    if p and not tile_proxy.ping(p):
        if tile_proxy._pid_looks_like_python(pid):
            E.log(u"  清掉旧的中转 pid=%s" % pid)
            tile_proxy._kill_pid(pid)
    if tile_proxy.ping():
        E.log(u"  中转已在跑：%s" % relay_stats())
        return 0
    script = os.path.join(HERE, u"TiandituTools", u"tile_server.py")
    E.log(u"  拉起独立中转 ...")
    subprocess.Popen([PY27, script, "17817"],
                     cwd=os.path.join(HERE, u"TiandituTools"),
                     creationflags=E.CREATE_NO_WINDOW)
    t0 = time.time()
    while time.time() - t0 < 20:
        time.sleep(0.5)
        if tile_proxy.ping():
            E.log(u"  中转就绪：%s" % relay_stats())
            return 0
    E.log(u"  !!! 中转起不来")
    return 1

#: (标签, 经纬度框 或 None=全图)
STEPS = [
    (u"1-全图",      None),
    (u"2-中国",      (73.0, 18.0, 135.0, 54.0)),
    (u"3-华北",      (112.0, 34.0, 122.0, 43.0)),
    (u"4-北京市区",  (116.20, 39.75, 116.60, 40.05)),
    (u"5-北京街道",  (116.38, 39.89, 116.42, 39.93)),
]


def tail(path, n=400):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


def tiles():
    return [l for l in tail(TILE_LOG, 5000) if u"[tile]" in l]


def clean(name):
    return re.sub(u"tk=[a-f0-9]+", u"tk=KEY", name)


def grab(tag, idx=0):
    # 文件名必须是纯 ASCII：py2 的 subprocess 在 Windows 上按 ascii 编码命令行，
    # 路径里带中文会直接 UnicodeEncodeError（抓屏就白抓了）。
    safe = re.sub(u"[^0-9A-Za-z_-]", u"", tag) or u"step"
    out = os.path.join(HERE, "_live_%d_%s.png" % (idx + 1, safe))
    try:
        p = subprocess.Popen([PY3, GRAB, out], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        o, _ = p.communicate()
        E.log(u"    [抓屏] %s" % (o.decode("utf-8", "replace").strip().replace(u"\n", u" | ")))
    except Exception as e:
        E.log(u"    [抓屏] 失败 %r" % (e,))
    return out


def main():
    wait_s = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    E.log("=== 清场 ===")
    for pid in E.arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=E.CREATE_NO_WINDOW)
    time.sleep(2)
    for p in (SELFTEST_LOG, TILE_LOG):
        try:
            os.remove(p)
        except Exception:
            pass

    E.log("=== 先起独立中转（在 ArcMap 之外，这样 ArcMap 被 kill 也不影响）===")
    if start_relay():
        return 1

    env = {}
    for k, v in os.environ.items():
        env[str(k)] = str(v)
    env[str("TIANDITU_SELFTEST")] = str("img,cia")
    env[str("TIANDITU_SELFTEST_QUIET")] = str("1")     # 自检只加图层，别改范围
    env[str("TIANDITU_NO_UI")] = str("1")
    E.log("=== 启动 ArcMap（自检安静模式）===")
    proc = subprocess.Popen([ARCMAP], env=env,
                            creationflags=E.CREATE_NEW_CONSOLE, close_fds=True)

    # 等自检把图层加完
    t0 = time.time()
    ready = False
    while time.time() - t0 < 150:
        time.sleep(4)
        if not E.alive(proc.pid):
            E.log("!!! ArcMap 死了")
            return 1
        for ln in tail(SELFTEST_LOG):
            if u"加完 LayerCount" in ln:
                E.log("  " + ln)
                ready = True
        if ready:
            break
    if not ready:
        E.log("!!! 等不到图层加完，日志：")
        for ln in tail(SELFTEST_LOG, 30):
            E.log("  | " + ln)
        return 1
    E.log("=== 图层已就绪，开始逐档缩放 ===")
    time.sleep(5)

    # 从外部调 COM 改范围（跨进程也能改；真正决定画不画的是 ArcMap 自己）
    sys.path.insert(0, CACHE)
    import arcobjects                                     # noqa: E402
    import dev_selftest as S                              # noqa: E402

    for i, (tag, box) in enumerate(STEPS):
        before = tiles()
        try:
            mx = arcobjects.document()
            av = mx.ActiveView
            if box:
                S._set_box(av, *box)
            else:
                arcobjects.zoom_full_extent()
            arcobjects.refresh()
            m = mx.FocusMap
            E.log(u"---- %s：设范围后 1:%.0f  Extent=(%.0f,%.0f)-(%.0f,%.0f)"
                  % (tag, m.MapScale, av.Extent.XMin, av.Extent.YMin,
                     av.Extent.XMax, av.Extent.YMax))
        except Exception as e:
            E.log(u"---- %s：设范围失败 %r" % (tag, e))

        time.sleep(8)
        grab(tag, i)
        after = tiles()
        new = after[len(before):]
        E.log(u"     瓦片新增 %d 张（累计 %d）" % (len(new), len(after)))
        E.log(u"     中转：%s" % relay_stats())
        lv = {}
        for l in new:
            mm = re.search(u"TileMatrix=([0-9]+)&TileRow=([0-9]+)&TileCol=([0-9]+)", l)
            if mm:
                lv.setdefault(mm.group(1), []).append((mm.group(2), mm.group(3)))
        for k in sorted(lv, key=int):
            E.log(u"       TM=%s  共 %d 张  例 %s" % (k, len(lv[k]), lv[k][:3]))
        if new:
            E.log(u"       首张原文: %s" % clean(new[0]))

    E.log("=== 结束（ArcMap 存活=%s）===" % E.alive(proc.pid))
    E.log("=== 中转：本次最慢的 5 张瓦片（上游耗时）===")
    ms = []
    for l in tiles():
        mm = re.search(u"([0-9]+) ms", l)
        if mm:
            ms.append((int(mm.group(1)), l))
    ms.sort(key=lambda x: -x[0])
    for v, l in ms[:5]:
        E.log(u"  %7d ms  %s" % (v, clean(l)))
    E.log(u"  共 %d 张，最慢 %s ms" % (len(ms), ms[0][0] if ms else u"-"))
    E.log("=== selftest.log 末尾（含卡顿记录）===")
    for ln in tail(SELFTEST_LOG, 25):
        E.log("  | " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
