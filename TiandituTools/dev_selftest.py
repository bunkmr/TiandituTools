# -*- coding: utf-8 -*-
"""仅调试用：在 **ArcMap 自己的进程 / 自己的主线程** 上观察「加底图之后到底画没画」。

为什么必须是主线程
------------------
`esriCarto.WMTSLayer` 是 in-proc 组件，谁 CreateObject 它就活在谁的进程里。
外部进程造出来再 `IMap.AddLayer` 塞给 ArcMap，ArcMap 手里只是**跨进程代理**
—— 面板里有图层、范围也对，但**一个瓦片都不请求**（实测多次 tiles=0）。
开一个新线程也不行：那是另一个 STA 公寓，跨公寓同样拿到的是代理。
所以验证「in-proc 造图层到底能不能出图」只能落在 ArcMap 的主线程上。

怎么拿到主线程
--------------
加载项模块（TiandituTools_addin.py）是 ArcMap 在**主线程**上 import 的，
所以在这里 `SetTimer(NULL, 0, ms, cb)`，回调就由主线程的消息循环派发 ——
正好是我们要的线程，而且不用改 config.xml 加 Extension。

自检步骤
--------
  0  等就绪，打印启动时的图层清单与地图状态
  1  多等几拍（ArcMap 刚起来数据框还没激活）
  2  自检**自己**在 ArcMap 进程内把图层加上（不依赖界面弹窗被人点）+ 起本机中转。
      注意 phase 不能断档：历史上 phase==2 被删掉后自检从这一步起空转，
      现象是「日志停住 / ArcMap 像卡死」，其实是假象。
  3~8  逐级换范围 + Refresh，每档连看 4 拍瓦片统计。
      **从最深的一档开始**：街道 1:3万 -> 北京 1:23万 -> 1:50万
      -> 华北 1:200万 -> 中国 1:2900万 -> 全图
  9  收尾，打印累计瓦片数 / 缓存命中 / 平均耗时

判定标准只有一条：设范围 + Refresh 之后，**中转日志里有没有新的瓦片请求**。
（`IActiveView.Draw(memdc)` 对 WMTS 图层不取瓦片，不能用它判断渲染。）

已踩过的坑（别再犯）
--------------------
* `IActiveView` **没有 Scale** 属性，比例尺在 `IMap.MapScale` 上；
* `ILayer.SpatialReference` 在类型库里只有 **propputref、不能读**，
  要判断空间参考就读 `ILayer.AreaOfInterest`；
* `IMap.DeleteLayer` + `IMap.Layer[0].Name` 在 ArcMap 10.4 里会**挂死 100 秒**
  最后抛 MemoryError，自检里千万别清图层。

开关
----
环境变量 `TIANDITU_SELFTEST=img,cia`（逗号分隔的 maptype，仅用于日志说明）。
结果写到 `%APPDATA%\\TiandituTools\\selftest.log`。
"""

from __future__ import print_function

import ctypes
import os
import time
import traceback
from ctypes import wintypes

_LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "TiandituTools")

_TICKS = {"n": 0, "timer": 0, "phase": 0, "maptypes": [], "errors": 0,
          "settle": 0, "wait": 0, "round": 0, "last_t": 0.0, "t0": 0}
_CB = None


def _log(text):
    try:
        if not os.path.isdir(_LOG_DIR):
            os.makedirs(_LOG_DIR)
        with open(os.path.join(_LOG_DIR, "selftest.log"), "ab") as f:
            f.write((u"[%s] %s\n" % (_now(), text)).encode("utf-8", "ignore"))
    except Exception:
        pass


def _now():
    try:
        import time
        return time.strftime("%H:%M:%S")
    except Exception:
        return u"??"


def _kill():
    try:
        if _TICKS["timer"]:
            ctypes.windll.user32.KillTimer(None, _TICKS["timer"])
    except Exception:
        pass
    _TICKS["timer"] = 0


def arm(maptypes=None, delay_ms=2500):
    """挂上定时器；返回是否挂上"""
    global _CB
    _TICKS["maptypes"] = list(maptypes or ["img", "cia"])
    u32 = ctypes.windll.user32
    if _CB is None:
        _CB = ctypes.WINFUNCTYPE(None, wintypes.HWND, wintypes.UINT,
                                 ctypes.c_void_p, wintypes.DWORD)(_tick)
    _TICKS["timer"] = u32.SetTimer(None, 0, delay_ms, _CB)
    _log(u"armed timer=%s maptypes=%s" % (_TICKS["timer"], _TICKS["maptypes"]))
    return bool(_TICKS["timer"])


def _titles():
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
            out.append(buf.value.strip())
        return True
    u32.EnumWindows(CB(cb), 0)
    return out


# ---------------------------------------------------------------------------
# 诊断工具
# ---------------------------------------------------------------------------

def _fmt_env(e):
    try:
        if e is None:
            return u"None"
        if e.IsEmpty:
            return u"EMPTY"
        return u"(%.0f,%.0f)-(%.0f,%.0f)" % (e.XMin, e.YMin, e.XMax, e.YMax)
    except Exception as ex:
        return u"<%r>" % (ex,)


#: 绘制阶段位（ILayer.SupportedDrawPhases）
_DP = {1: u"地理", 2: u"注记", 4: u"选择"}


def _dump_map(tag):
    import arcobjects
    try:
        mx = arcobjects.document()
        m = mx.FocusMap
        av = mx.ActiveView
        extra = []
        for attr in ("IsMapActivated", "IsActive"):
            try:
                extra.append(u"%s=%s" % (attr, av.__getattribute__(attr)))
            except Exception as ex:
                extra.append(u"%s=<%r>" % (attr, ex))
        try:
            extra.append(u"MapScale=1:%.0f" % m.MapScale)
        except Exception as ex:
            extra.append(u"MapScale=<%r>" % (ex,))
        try:
            extra.append(u"MapUnits=%s" % m.MapUnits)
        except Exception:
            pass
        _log(u"%s: LayerCount=%s Extent=%s %s"
             % (tag, m.LayerCount, _fmt_env(av.Extent), u" ".join(extra)))
        for i in range(m.LayerCount):
            l = m.Layer[i]
            parts = [u"[%d] %r" % (i, l.Name)]
            for attr in ("Visible", "Valid", "MinimumScale", "MaximumScale"):
                try:
                    parts.append(u"%s=%s" % (attr, l.__getattribute__(attr)))
                except Exception as ex:
                    parts.append(u"%s=<%r>" % (attr, ex))
            try:
                v = int(l.SupportedDrawPhases)
                parts.append(u"DrawPhases=%s" % u"+".join(
                    t for b, t in sorted(_DP.items()) if v & b))
            except Exception as ex:
                parts.append(u"DrawPhases=<%r>" % (ex,))
            parts.append(u"AOI=%s" % _fmt_env(l.AreaOfInterest))
            parts.append(_dump_wmts(l))
            _log(u"    " + u"  ".join(parts))
    except Exception:
        _log(u"%s 失败:\n%s" % (tag, traceback.format_exc()))


def _dump_wmts(l):
    """如果这个图层是 WMTS 图层，从**地图里那个对象**把四个关键属性读出来"""
    try:
        import arcobjects
        mods = arcobjects.ensure_types()
        w = l.QueryInterface(mods["esriCarto"].IWMTSLayer)
    except Exception as ex:
        return u"wmts=<非 IWMTSLayer：%r>" % (ex,)
    return u"wmts{" + arcobjects._read_wmts(w) + u"}"


def _dump_tiles(tag):
    try:
        import tile_proxy
        st = tile_proxy.live_stats()
        _log(u"%s: tiles=%s caps=%s err=%s port=%s"
             % (tag, st["tiles"], st["caps"], st["errors"], st["port"]))
    except Exception as ex:
        _log(u"%s 读统计失败 %r" % (tag, ex))


def _set_box(av, lon1, lat1, lon2, lat2):
    """把视图范围设成经纬度框（Web Mercator）"""
    import math
    R = 6378137.0
    x1 = R * math.radians(lon1)
    y1 = R * math.log(math.tan(math.radians(45.0 + lat1 / 2.0)))
    x2 = R * math.radians(lon2)
    y2 = R * math.log(math.tan(math.radians(45.0 + lat2 / 2.0)))

    import comtypes.client as cc
    import arcobjects
    geo = cc.GetModule(os.path.join(arcobjects.com_dir(), "esriGeometry.olb"))
    env = cc.CreateObject("esriGeometry.Envelope", interface=geo.IEnvelope)
    env.PutCoords(x1, y1, x2, y2)
    try:
        av.Extent = env
        return True
    except Exception as ex:
        _log(u"  av.Extent = env 失败（改走 PutCoords）：%r" % (ex,))
    try:
        cur = av.Extent
        cur.PutCoords(x1, y1, x2, y2)
        av.Extent = cur
        return True
    except Exception as ex:
        _log(u"  设范围失败：%r" % (ex,))
        return False


def _set_china(av):
    """把视图范围设成「中国」——Web Mercator 下的 73~135E / 18~54N"""
    return _set_box(av, 73.0, 18.0, 135.0, 54.0)


def _scale():
    """当前地图比例尺（字符串），拿不到就返回 ?"""
    try:
        import arcobjects
        return u"1:%.0f" % arcobjects.document().FocusMap.MapScale
    except Exception:
        return u"?"


# ---------------------------------------------------------------------------
# 真·绘制探针：强制同步重绘 + 窗口截图
# ---------------------------------------------------------------------------

def _arcmap_frame():
    """找到 ArcMap 主窗口句柄（标题以 " - ArcMap" 结尾且可见）"""
    u32 = ctypes.windll.user32
    found = []

    def cb(h, l):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                if buf.value.endswith(u"- ArcMap"):
                    found.append(h)
        return True

    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u32.EnumWindows(CB(cb), 0)
    return found[0] if found else None


def _repaint_now(tag):
    """强制 ArcMap **同步**把窗口（含地图子窗口）重绘一遍。

    为什么非这样不可：实测 `av.Extent = ...; av.Refresh()` 只改范围，
    **根本不产生 WM_PAINT**（自检里每一档都是「新增 0 张瓦片」），
    用它判断「放大后画不画得出来」只会得到假结论。
    RedrawWindow + RDW_UPDATENOW 是同步语义：这个调用返回时地图已经画完，
    瓦片也取完了 —— 这才是能测出真相的探针。
    """
    u32 = ctypes.windll.user32
    h = _arcmap_frame()
    if not h:
        _log(u"  强制重绘：找不到 ArcMap 窗口")
        return 0.0
    RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_UPDATENOW = 0x1, 0x4, 0x80, 0x100
    t0 = time.time()
    try:
        u32.RedrawWindow(h, None, None,
                         RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW)
    except Exception as ex:
        _log(u"  强制重绘失败 %r" % (ex,))
    dt = time.time() - t0
    _log(u"  强制重绘 %s 完成，耗时 %.1f s" % (tag, dt))
    return dt


def _shot_bmp(tag):
    """PrintWindow 抓 ArcMap 主窗口 -> BMP，并统计非白占比。

    PrintWindow 会**逼**窗口把自己画出来（跨进程也一样），所以它同时是
    「能不能渲染」的最硬证据。注意它很慢（要等地图把瓦片取完）。
    """
    u32 = ctypes.windll.user32
    gdi = ctypes.windll.gdi32
    h = _arcmap_frame()
    if not h:
        _log(u"  截图[%s]：找不到 ArcMap 窗口" % tag)
        return None
    rc = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(rc))
    w, hh = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or hh <= 0 or w * hh > 40 * 1000 * 1000:
        _log(u"  截图[%s]：尺寸异常 %sx%s" % (tag, w, hh))
        return None

    u32.GetWindowDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
    hdc = u32.GetWindowDC(h)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, hh)
    gdi.SelectObject(mem, bmp)
    t0 = time.time()
    u32.PrintWindow(h, mem, 2)                 # PW_RENDERFULLCONTENT
    dt = time.time() - t0

    bi = _BMI()
    bi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -hh                # 负 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * hh * 4)
    gdi.GetDIBits(mem, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    u32.ReleaseDC(h, hdc)

    out = os.path.join(os.environ.get("TEMP") or ".", "TiandituTools")
    try:
        if not os.path.isdir(out):
            os.makedirs(out)
    except Exception:
        pass
    path = os.path.join(out, u"shot_%s.bmp" % tag)
    try:
        _write_bmp(path, w, hh, buf.raw)
    except Exception as ex:
        _log(u"  截图[%s] 写 BMP 失败 %r" % (tag, ex))
        return None

    data = buf.raw
    nonwhite = total = 0
    for i in range(0, w * hh * 4, 4 * 7):
        total += 1
        if data[i] < 240 or data[i + 1] < 240 or data[i + 2] < 240:
            nonwhite += 1
    pct = 100.0 * nonwhite / total if total else 0.0
    _log(u"  截图[%s] PrintWindow %.1f s 非白占比=%.1f%% -> %s" % (tag, dt, pct, path))
    return path


def _refresh(tag):
    import arcobjects
    try:
        mx = arcobjects.document()
        mx.ActiveView.Refresh()
        _log(u"  %s：Refresh 已调用" % tag)
    except Exception as ex:
        _log(u"  %s：Refresh 失败 %r" % (tag, ex))


# ---------------------------------------------------------------------------
# 强制渲染到位图（绕过窗口 WM_PAINT）
# ---------------------------------------------------------------------------

class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wintypes.DWORD * 3)]


def _write_bmp(path, w, h, bgra_topdown):
    """写 24 位 BMP（BMP 的行序是自下而上，所以这里倒着写）

    注意：py2.7 **没有** `int.to_bytes`，只能用 struct.pack。
    """
    import struct

    row_raw = w * 4
    row_out = (w * 3 + 3) & ~3
    pad = b"\x00" * (row_out - w * 3)
    px = bytearray()
    for y in range(h - 1, -1, -1):
        base = y * row_raw
        line = bytearray()
        for x in range(w):
            o = base + x * 4
            line += bgra_topdown[o + 2:o + 3]      # B
            line += bgra_topdown[o + 1:o + 2]      # G
            line += bgra_topdown[o + 0:o + 1]      # R
        px += bytes(line) + pad

    hdr = b"BM" + struct.pack("<IHHI", 14 + 40 + len(px), 0, 0, 14 + 40)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(px), 2835, 2835, 0, 0)
    with open(path, "wb") as f:
        f.write(hdr + dib + bytes(px))


def _draw_to_bmp(tag, w=1400, h=900):
    """用 `IActiveView.Draw(hDC)` 把当前视图画到内存 DC 再存成 BMP。

    **重要（已实测）：这条路径对 WMTS 图层不触发取瓦片。**
    每一档都是 0 张瓦片、非白占比 0.0%，所以它**不能**用来判断「底图渲染出来没有」，
    只能用来确认绘图调用本身没抛异常。判断渲染是否发生，请看中转日志里
    有没有新的瓦片请求（或者真窗口截图）。
    """
    import ctypes
    import arcobjects
    gdi = ctypes.windll.gdi32
    user = ctypes.windll.user32
    out = os.path.join(os.environ.get("TEMP") or ".", "TiandituTools")
    try:
        if not os.path.isdir(out):
            os.makedirs(out)
    except Exception:
        pass
    path = os.path.join(out, "draw_%s.bmp" % tag)

    hdc_screen = user.GetDC(0)
    memdc = gdi.CreateCompatibleDC(hdc_screen)
    bmp = gdi.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi.SelectObject(memdc, bmp)
    gdi.PatBlt(memdc, 0, 0, w, h, 0x00FF0062)          # WHITENESS

    ok, err = False, u""
    try:
        av = arcobjects.document().ActiveView
        av.Draw(memdc, None)
        ok = True
    except Exception as ex:
        err = u"%r" % (ex,)

    bi = _BMI()
    bi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h                          # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi.DeleteObject(bmp)
    gdi.DeleteDC(memdc)
    user.ReleaseDC(0, hdc_screen)

    try:
        _write_bmp(path, w, h, buf.raw)
    except Exception as ex:
        _log(u"  写 BMP 失败 %r" % (ex,))
        return None

    # 顺手统计一下「非白像素占比」，判断到底画出来没有
    data = buf.raw
    nonwhite = 0
    step = 4 * 7
    total = 0
    for i in range(0, w * h * 4, step):
        total += 1
        if data[i] < 240 or data[i + 1] < 240 or data[i + 2] < 240:
            nonwhite += 1
    pct = (100.0 * nonwhite / total) if total else 0.0
    _log(u"  渲染[%s] Draw=%s%s 非白占比=%.1f%% -> %s"
         % (tag, ok, (u" err=%s" % err) if err else u"", pct, path))
    return path


# ---------------------------------------------------------------------------
# 一拍一步
# ---------------------------------------------------------------------------

def _tick(hwnd, msg, tid, tc):
    _TICKS["n"] += 1
    # 定时器间隔是 2500ms。如果两拍之间隔了几十秒，说明**主线程被别的东西占住了**
    # ——这正是用户看到的「点了放大没反应」。把这件事记下来，别再靠猜。
    now = time.time()
    dt = now - _TICKS.get("last_t", now)
    _TICKS["last_t"] = now
    if dt > 4.0:
        _log(u"!! 主线程被占用 %.1f s（上一拍 -> 本拍，正常应约 2.5s）" % dt)
    try:
        _work()
    except Exception:
        _TICKS["errors"] += 1
        _log(u"tick 异常:\n%s" % traceback.format_exc())
        if _TICKS["errors"] > 5:
            _kill()
            _log(u"异常过多，停止")


def _work():
    ph = _TICKS["phase"]

    # --- 0: 等就绪 -------------------------------------------------------
    if ph == 0:
        ts = _titles()
        if any(u"启动" in t for t in ts):
            return
        if not any(t.endswith(u" - ArcMap") for t in ts):
            if _TICKS["n"] < 60:
                return
            _log(u"等不到 ArcMap 主窗口，放弃；当前窗口=%s" % (ts[:6],))
            _kill()
            return
        import arcobjects
        mx = arcobjects.document()
        if mx is None:
            if _TICKS["n"] < 60:
                return
            _log(u"取不到 IMxDocument，放弃")
            _kill()
            return
        _log(u"就绪：Maps.Count=%s FocusMap=%r 窗口=%s"
             % (mx.Maps.Count, mx.FocusMap.Name,
                [t for t in ts if "ArcMap" in t][:3]))
        _dump_map(u"启动状态")
        _dump_tiles(u"启动状态")
        _TICKS["settle"] = 3
        _TICKS["phase"] = 1
        return

    # --- 1: 多等几拍（数据框激活） ---------------------------------------
    if ph == 1:
        if _TICKS["settle"] > 0:
            _TICKS["settle"] -= 1
            return
        _dump_map(u"激活后")
        _dump_tiles(u"激活后")
        _TICKS["phase"] = 3
        return

    # --- 2: 自检自己把图层加上 + 起中转（不依赖界面弹窗被人点） -------------
    if ph == 2:
        import layer_manager
        import arcobjects
        try:
            import tile_proxy
            # 必须和正式路径一致：用**独立进程**中转。
            # 这里以前写的是 tile_proxy.start()（进程内起服务器），
            # 那正是会把 ArcMap 冻住的那条路，自检就测不到真东西了。
            _log(u"中转端口=%s" % tile_proxy.ensure_external())
        except Exception:
            _log(u"起中转失败:\n%s" % traceback.format_exc())
        for mt in (_TICKS["maptypes"] or [u"img", u"cia"]):
            try:
                ok = layer_manager.add_tianditu(mt)
                _log(u"  自检加图层 %s -> %s" % (mt, ok))
            except Exception:
                _log(u"  自检加图层 %s 失败:\n%s" % (mt, traceback.format_exc()))
        try:
            m = arcobjects.current_map()
            _log(u"  加完 LayerCount=%s" % (m.LayerCount if m else u"?"))
        except Exception:
            pass
        _TICKS["phase"] = 3
        return

    # --- 3~8: 逐级【从最深开始】放大/缩小，每档只看「真窗口绘制取了多少瓦片」 ----
    #
    # 安静模式（TIANDITU_SELFTEST_QUIET=1）：自检只负责在进程内把图层加上，
    # 缩放交给外部驱动一步步做。为什么要这样：自检自己连续快速改范围时，
    # 几次绘制会互相覆盖，「到底哪一档画了」根本说不清（实测被这个坑过）。
    if os.environ.get("TIANDITU_SELFTEST_QUIET"):
        if ph == 3:
            # 发出「加完 LayerCount=...」这一步就绪信号：外部驱动
            # （dev_zoom_live.py）靠这行判断可以开始逐档缩放了。
            try:
                import arcobjects
                m = arcobjects.current_map()
                _log(u"  加完 LayerCount=%s（安静模式，缩放交给外部驱动）"
                     % (m.LayerCount if m else u"?"))
            except Exception:
                _log(u"  加完 LayerCount=?（安静模式，缩放交给外部驱动）")
            _TICKS["phase"] = 99
        return
    #
    # 为什么要从最深开始：用户的问题是「能加载、不能放大」，那就先把最深那一档
    # 单独拎出来看 —— 如果深放大取得到瓦片，问题就不在取瓦片这条链上。
    #
    # 另外，**别再用 _draw_to_bmp 判断画没画**：实测 `IActiveView.Draw(memdc)`
    # 对 WMTS 图层**完全不触发取瓦片**（每一档都是 0 张 / 非白 0.0%），
    # 它只能证明「绘图调用没报错」，证明不了渲染。判定标准只有一条：
    # 设范围 + Refresh 之后，中转日志里有没有新的瓦片请求。
    _STEPS = [
        (u"深放大-街道 1:3万",  (116.38, 39.89, 116.42, 39.93)),
        (u"北京 1:23万",        (116.33, 39.86, 116.46, 39.95)),
        (u"北京 1:50万",        (116.20, 39.75, 116.60, 40.05)),
        (u"华北 1:200万",       (112.0, 34.0, 122.0, 43.0)),
        (u"中国 1:2900万",      (73.0, 18.0, 135.0, 54.0)),
        (u"全图",               None),
    ]
    #: 这些档要截图（PrintWindow 很慢，别每档都截）
    _SHOT_AT = (0, 4)
    if 3 <= ph <= 8:
        idx = ph - 3
        tag, box = _STEPS[idx]
        w = _TICKS["wait"]
        if w == 0:
            import arcobjects
            import tile_proxy
            _TICKS["t0"] = tile_proxy.live_stats()["tiles"]
            _log(u"---- %s ---- 设范围前 %s  tiles=%s"
                 % (tag, _scale(), _TICKS["t0"]))
            try:
                mx = arcobjects.document()
                if box:
                    _set_box(mx.ActiveView, *box)
                else:
                    arcobjects.zoom_full_extent()
            except Exception:
                _log(u"  设范围失败:\n%s" % traceback.format_exc())
            _log(u"  设范围后 %s" % _scale())
            _refresh(tag)
            _TICKS["wait"] = 1
            return
        if w == 1:
            # 关键一步：强制真绘制，看放大之后到底取不取瓦片
            _repaint_now(tag)
            try:
                import arcobjects
                _log(u"  重绘后 %s" % _scale())
            except Exception:
                pass
        if w == 2 and idx in _SHOT_AT:
            _shot_bmp(tag.replace(u" ", u"_"))
        try:
            import tile_proxy
            st = tile_proxy.live_stats()
            _log(u"  %s 第%d拍 tiles=%d（本档新增 %d，缓存命中 %d）"
                 % (tag, w, st["tiles"], st["tiles"] - _TICKS["t0"], st["cached"]))
        except Exception:
            pass
        _TICKS["wait"] = w + 1
        if _TICKS["wait"] > 3:
            _TICKS["wait"] = 0
            _TICKS["phase"] = ph + 1
        return

    # --- 9: 收尾 ---------------------------------------------------------
    if ph == 9:
        _dump_tiles(u"结束")
        _dump_map(u"最终状态")
        try:
            import tile_proxy
            st = tile_proxy.live_stats()
            _log(u"结束：tiles=%s 缓存=%s 命中=%s 错误=%s 平均 %d ms/张"
                 % (st["tiles"], st["cache_size"], st["cached"], st["errors"],
                    st["avg_ms"]))
        except Exception:
            pass
        _log(u"结束：tiles=%s" % __import__("tile_proxy").live_stats()["tiles"])
        _kill()
        return
