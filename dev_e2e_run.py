# -*- coding: utf-8 -*-
"""一把梭的端到端验证：启动 ArcMap → 起中转 → 加底图 → 截图 → 汇总。

为什么必须「一把梭」
--------------------
沙箱会在每次工具调用结束时回收子进程，ArcMap 活不过一次调用；
而且 DFORRT.dll（Fortran 运行时，被 arcpy 整条栈拉进来）在写诊断信息时
要往 **unit 0 = CONOUT$** 写 —— 如果进程没有可用控制台（CREATE_NO_WINDOW）
或者继承的控制台已经死了，这次写就会失败，运行时随即
`forrtl: severe (38): error during write, unit 0, file CONOUT$`
并弹模态框把进程卡死。
所以这里用 **CREATE_NEW_CONSOLE** 给 ArcMap 一个属于自己的、有效的控制台，
把「控制台问题」这个干扰项排除掉，专心看底图能不能出图。

用法：<py27> dev_e2e_run.py [启动等待秒] [观察秒]
"""
from __future__ import print_function, unicode_literals

import ctypes
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime

#: 提前把函数对象抓在手里 —— 加载 ArcObjects 过程中会有别的模块把
#: 本模块全局里的 `datetime` 换成 datetime 模块（实测踩过），
#: 直接调用 datetime.now() 会炸 AttributeError('module' object has no attribute 'now')
_STRFTIME = time.strftime

sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "TiandituTools"))

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
PROJ = HERE

DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32


def log(*a):
    out = []
    for x in a:
        if isinstance(x, unicode):        # noqa: F821
            out.append(x)
        elif isinstance(x, str):
            out.append(x.decode("utf-8", "replace"))
        else:
            out.append(unicode(x))        # noqa: F821
    print(u"[%s] %s" % (_STRFTIME("%H:%M:%S"), u" ".join(out)))
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


def shot(tag):
    """PrintWindow + GetDIBits + PIL 抓 ArcMap 主窗口（即使被挡住也能抓到）。

    别用 GDI+ 的 GdipSaveImageToFile —— 这条路上静默失败（文件根本不生成），
    查起来很费劲。GetDIBits 拿原始像素再交给 PIL 最省事。
    """
    try:
        from ctypes import wintypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            u32.SetProcessDPIAware()

        found = []
        CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, l):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                t = buf.value
                if "ArcMap" in t and u32.IsWindowVisible(h):
                    r = wintypes.RECT()
                    u32.GetWindowRect(h, ctypes.byref(r))
                    found.append((h, t, r.left, r.top, r.right, r.bottom))
            return True

        u32.EnumWindows(CB(cb), 0)
        if not found:
            log("  [shot %s] 找不到 ArcMap 窗口" % tag)
            return
        h, title, l, t, r, b = max(found, key=lambda x: (x[4] - x[2]) *
                                   (x[5] - x[3]))
        w, hh = r - l, b - t
        if w <= 0 or hh <= 0:
            log("  [shot %s] 尺寸异常 %sx%s" % (tag, w, hh))
            return

        gdi32 = ctypes.windll.gdi32
        u32.GetWindowDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
        hdc = u32.GetWindowDC(h)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, hh)
        gdi32.SelectObject(mem, bmp)
        u32.PrintWindow(h, mem, 2)          # PW_RENDERFULLCONTENT

        buf = ctypes.create_string_buffer(w * hh * 4)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bi = BIH()
        bi.biSize = ctypes.sizeof(BIH)
        bi.biWidth = w
        bi.biHeight = -hh               # 负值 = 自顶向下
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0
        gdi32.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0)

        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        u32.ReleaseDC(h, hdc)

        # ArcGIS 自带的 py2 里**没有 PIL**，直接写 32bpp BMP（行倒序即可），
        # 之后用 py3 + PIL 转 jpg。
        path = os.path.join(PROJ, "_e2e_%s.bmp" % tag)
        _write_bmp(buf.raw, w, hh, path)
        log("  [shot %s] -> %s (%dx%d)" % (tag, os.path.basename(path), w, hh))
    except Exception as e:
        log("  [shot %s] 失败 %r" % (tag, e))


def _write_bmp(raw, w, h, path):
    """把 32bpp BGRA（自顶向下）写成 BMP（BMP 要求行自底向上）"""
    import struct
    row = w * 4
    out = bytearray()
    for y in range(h - 1, -1, -1):
        out += raw[y * row:(y + 1) * row]
    hdr = 14 + 40
    with open(path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI", hdr + len(out), 0, 0, hdr))
        f.write(struct.pack("<IiiHHIIiiII", 40, w, h, 1, 32, 0, len(out),
                            2835, 2835, 0, 0))
        f.write(bytes(out))


def probe_map(arcobjects, tag):
    """打印地图状态：范围 / 单位 / 空间参考 / 每个图层的可见性与 AOI。

    「ArcMap 取了 capabilities 但一个瓦片都不请求」时，答案基本都在这几行里：
    数据框范围是空的、单位不对、或者图层根本没被判定为可见。
    """
    try:
        mx = arcobjects.document()
        if mx is None:
            log("  [map %s] 拿不到 IMxDocument" % tag)
            return
        m = mx.FocusMap
        av = mx.ActiveView
        try:
            e = av.Extent
            log("  [map %s] Name=%r LayerCount=%s MapUnits=%s "
                "Extent=(%.1f,%.1f)-(%.1f,%.1f)"
                % (tag, m.Name, m.LayerCount, m.MapUnits,
                   e.XMin, e.YMin, e.XMax, e.YMax))
        except Exception as ex:
            log("  [map %s] Extent 读取失败 %r" % (tag, ex))
        try:
            fe = av.FullExtent
            log("  [map %s] FullExtent=(%.1f,%.1f)-(%.1f,%.1f) empty=%s"
                % (tag, fe.XMin, fe.YMin, fe.XMax, fe.YMax, fe.IsEmpty))
        except Exception as ex:
            log("  [map %s] FullExtent 读取失败 %r" % (tag, ex))
        try:
            sr = m.SpatialReference
            log("  [map %s] 地图 SR=%r" % (tag, sr.Name if sr else None))
        except Exception as ex:
            log("  [map %s] SR 读取失败 %r" % (tag, ex))
        # 有几张地图？FocusMap 是不是屏幕上显示的那张？
        # （ArcMap 刚启动时 FocusMap 可能指向别的地图，会导致
        #   「图层加到了另一张图上、屏幕这张是空的」这种假象）
        try:
            maps = mx.Maps
            log("  [map %s] Maps.Count=%s FocusMap.Name=%r"
                % (tag, maps.Count, m.Name))
            for j in range(maps.Count):
                try:
                    mm = maps.get_Element(j)
                    log("  [map %s]   map[%d] Name=%r LayerCount=%s"
                        % (tag, j, mm.Name, mm.LayerCount))
                except Exception as ex:
                    log("  [map %s]   map[%d] 读取失败 %r" % (tag, j, ex))
        except Exception as ex:
            log("  [map %s] Maps 读取失败 %r" % (tag, ex))
        for i in range(m.LayerCount):
            try:
                l = m.Layer[i]
                s = u"  [map %s]   [%d] Name=%r Visible=%s" % (
                    tag, i, l.Name, bool(l.Visible))
                try:
                    a = l.AreaOfInterest
                    s += u" AOI=(%.1f,%.1f)-(%.1f,%.1f)" % (
                        a.XMin, a.YMin, a.XMax, a.YMax)
                except Exception:
                    pass
                try:
                    s += u" MinScale=%s MaxScale=%s" % (
                        l.MinimumScale, l.MaximumScale)
                except Exception:
                    pass
                log(s)
            except Exception as ex:
                log("  [map %s]   [%d] 读取失败 %r" % (tag, i, ex))
    except Exception as e:
        log("  [map %s] 失败 %r" % (tag, e))


def main():
    wait_s = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    watch_s = int(sys.argv[2]) if len(sys.argv) > 2 else 55

    os.environ["TIANDITU_NO_UI"] = "1"

    log("=== 清场 ===")
    for pid in arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=CREATE_NO_WINDOW)
    time.sleep(2)

    log("=== 启动 ArcMap（CREATE_NEW_CONSOLE：给它有效的 CONOUT$）===")
    proc = subprocess.Popen([ARCMAP], creationflags=CREATE_NEW_CONSOLE,
                            close_fds=True)
    log("pid=%d" % proc.pid)

    log("=== 等 ArcMap 真正就绪（启动画面消失、文档加载完成）===")
    ready = False
    for i in range(wait_s):
        time.sleep(1)
        if not alive(proc.pid):
            log("!!! ArcMap 启动后 %ds 就死了" % (i + 1))
            return 1
        ts = titles()
        splash = any(u"ArcMap - 启动" in t for t in ts)
        main = any(u"无标题" in t or u"- ArcMap" in t for t in ts)
        if main and not splash:
            ready = True
            log("  就绪，用了 %ds  窗口=%s" % (i + 1,
                                        [t for t in ts if "Arc" in t][:3]))
            break
        if i % 10 == 9:
            log("  等待 %ds alive=%s splash=%s main=%s"
                % (i + 1, alive(proc.pid), splash, main))
    if not ready:
        log("!!! 等不到就绪状态，继续尝试")
    time.sleep(3)

    import arcobjects
    import layer_manager as lm
    import tile_proxy
    from config import get_key

    key = get_key()
    log("=== 起中转（ArcMap 进程之外的进程里起，先验证跨进程能不能出图）===")
    port = tile_proxy.start(key=key)
    log("port=%s key=%s..." % (port, (key or u"")[:8]))
    if not port:
        return 1

    caps = tile_proxy.capabilities_url("img")
    log("caps=%s" % caps)

    log("=== 探测 IWMTSLayer 回读 ===")
    try:
        info = arcobjects.probe_wmts(caps, "img")
        for k in ("connected", "LayerName", "TileMatrixSet", "Style",
                  "ImageFormat", "Dimensions"):
            log("   %-14s = %r" % (k, info.get(k)))
    except Exception as e:
        log("   probe_wmts 失败 %r" % (e,))

    log("=== A) 直接 AddLayer（跨进程代理）===")
    for mt in ("img", "cia"):
        log("   add_tianditu(%r) -> %s" % (mt, lm.add_tianditu(mt)))
    probe_map(arcobjects, u"A-加完")

    log("--- A 阶段观察 25s（每 10s 主动强制重绘一次）---")
    t0 = time.time()
    while time.time() - t0 < 25:
        time.sleep(5)
        el = int(time.time() - t0)
        st = tile_proxy.stats()
        log("  A t=%3ds alive=%s tiles=%s caps=%s"
            % (el, alive(proc.pid), st["tiles"], st["caps"]))
        if el % 10 < 5:
            try:
                arcobjects.zoom_full_extent()
                log("  A 已强制重绘（zoom_full_extent）")
            except Exception as e:
                log("  A 强制重绘失败 %r" % (e,))
        if not alive(proc.pid):
            break
    a_tiles = tile_proxy.stats()["tiles"]
    shot("A%03d" % 25)
    probe_map(arcobjects, u"A-缩放进度")

    if len(sys.argv) > 3 and sys.argv[3] == "lyr":
        log("=== B) 走 .lyr（让 ArcMap 自己在自己进程里造图层）===")
        lyr_pairs = []
        for mt in ("cia", "img"):
            try:
                p = arcobjects.save_wmts_lyr(
                    tile_proxy.capabilities_url(mt),
                    lm.TIANDITU_MAP_INFO.get(mt, mt), mt)
                lyr_pairs.append(p)
                log("   saved %s" % p)
            except Exception as e:
                log("   save_wmts_lyr(%s) 失败 %r" % (mt, e))
        holders = []
        try:
            log("   add_lyr_bottom -> %s"
                % arcobjects.add_lyr_bottom(lyr_pairs, keep=holders))
            arcobjects.zoom_full_extent()
        except Exception as e:
            log("   add_lyr_bottom 失败 %r" % (e,))
        probe_map(arcobjects, u"B-加完")

        log("--- B 阶段观察 %ds ---" % watch_s)
        t0 = time.time()
        while time.time() - t0 < watch_s:
            time.sleep(5)
            el = int(time.time() - t0)
            st = tile_proxy.stats()
            up = alive(proc.pid)
            log("  B t=%3ds alive=%-5s tiles=%s caps=%s err=%s"
                % (el, up, st["tiles"], st["caps"], st["errors"]))
            if el % 20 < 5:
                shot("B%03d" % el)
            if not up:
                log("!!! ArcMap 已死亡")
                break
        probe_map(arcobjects, u"结束时")

    log("=== 汇总 ===")
    log("   A 阶段 tiles=%s   B 阶段末 tiles=%s"
        % (a_tiles, tile_proxy.stats()["tiles"]))

    log("=== 汇总 ===")
    log("   stats=%s" % json.dumps(tile_proxy.stats()))
    try:
        lp = os.path.join(tile_proxy._LOG_DIR, "tile_proxy.log")
        lines = io.open(lp, "r", encoding="utf-8",
                        errors="replace").readlines()
        log("   tile_proxy.log 末 15 行：")
        for ln in lines[-15:]:
            log("     " + ln.rstrip())
    except Exception as e:
        log("   读日志失败 %r" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
