# -*- coding: utf-8 -*-
"""端到端验证：本机中转 + ArcObjects 加图层，看瓦片到底出不出来。

流程
----
1. 在本进程里起 tile_proxy（守护线程，本进程活着它就活着）；
2. 打印 IWMTSLayer 回读的 LayerName / TileMatrixSet / Style / ImageFormat；
3. 用**正式代码路径**（layer_manager.add_tianditu）加「影像地图」+「影像注记」；
4. 保持存活，期间反复截图，看画布是否出图；
5. 结束时打印代理统计 —— 关键指标是 **tiles > 0**（ArcMap 真的来取瓦片了）。

用法：
    <ArcGIS python.exe> dev_e2e_proxy.py [保持秒数]
"""
from __future__ import print_function

import io
import json
import os
import sys
import time

sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "TiandituTools"))

import arcobjects                     # noqa: E402
import layer_manager as lm            # noqa: E402
import tile_proxy                     # noqa: E402

HOLD = int(sys.argv[1]) if len(sys.argv) > 1 else 90
SHOT = os.path.join(HERE, "_e2e_shot_%d.jpg")


def p(*a):
    """打印并 flush。统一转 unicode —— stdout 被包成 utf-8 文本流，
    直接塞 py2 的 str（bytes）会报 must be unicode, not str。"""
    out = []
    for x in a:
        if isinstance(x, unicode):        # noqa: F821
            out.append(x)
        elif isinstance(x, str):
            try:
                out.append(x.decode("utf-8"))
            except Exception:
                out.append(x.decode("gbk", "replace"))
        else:
            out.append(unicode(x))        # noqa: F821
    print(u" ".join(out))
    sys.stdout.flush()


def shot(tag):
    """PrintWindow 抓 ArcMap 主窗口（不用切前台）"""
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        u32.FindWindowW.restype = wintypes.HWND
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        hwnd = u32.FindWindowW(None, u"\u65e0\u6807\u9898 - ArcMap")
        if not hwnd:
            # 退而求其次：找所有标题含 ArcMap 的窗口
            found = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(h, l):
                buf = ctypes.create_unicode_buffer(512)
                u32.GetWindowTextW(h, buf, 512)
                if "ArcMap" in buf.value:
                    found.append((h, buf.value))
                return True
            u32.EnumWindows(cb, 0)
            if found:
                hwnd = found[0][0]
        if not hwnd:
            p("  [shot %s] 找不到 ArcMap 窗口" % tag)
            return
        rect = wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            p("  [shot %s] 窗口尺寸异常 %sx%s" % (tag, w, h))
            return
        gdi = ctypes.windll.gdi32
        u32.GetWindowDC.restype = ctypes.c_void_p
        gdi.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
        hdc = u32.GetWindowDC(hwnd)
        mdc = gdi.CreateCompatibleDC(hdc)
        bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
        gdi.SelectObject(mdc, bmp)
        u32.PrintWindow(hwnd, mdc, 2)     # PW_RENDERFULLCONTENT
        # 用 GDI+ 存 jpg
        path = SHOT % int(time.time() % 100000)
        _save_jpg(bmp, hdc, w, h, path)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(mdc)
        u32.ReleaseDC(hwnd, hdc)
        p("  [shot %s] %s  (%dx%d)" % (tag, os.path.basename(path), w, h))
    except Exception as e:
        p("  [shot %s] 失败 %r" % (tag, e))


def _save_jpg(hbmp, hdc, w, h, path):
    """借 GDI+ 把位图存成 JPEG（纯 stdlib + ctypes）"""
    import ctypes
    from ctypes import wintypes
    gdiplus = ctypes.windll.gdiplus
    ln = ctypes.c_size_t
    gdiplus.GdiplusStartup.argtypes = [ctypes.POINTER(ln),
                                       ctypes.c_void_p, ctypes.c_void_p]
    tok = ln()
    gdiplus.GdiplusStartup(ctypes.byref(tok), None, None)
    gdiplus.GdipCreateBitmapFromHBITMAP.argtypes = [
        wintypes.HBITMAP, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    bmp = ctypes.c_void_p()
    gdiplus.GdipCreateBitmapFromHBITMAP(hbmp, None, ctypes.byref(bmp))
    clsid = ctypes.c_buffer(16)
    # JPEG encoder CLSID {557CF401-1A04-11D3-9A73-0000F81EF32E}
    raw = (b"\x01\xf4\x7c\x55\x04\x1a\xd3\x11\x9a\x73\x00\x00\xf8\x1e\xf3\x2e")
    ctypes.memmove(clsid, raw, 16)
    gdiplus.GdipSaveImageToFile.argtypes = [ctypes.c_void_p,
                                            ctypes.c_wchar_p,
                                            ctypes.c_void_p,
                                            ctypes.c_void_p]
    gdiplus.GdipSaveImageToFile(bmp, path, clsid, None)
    gdiplus.GdipDisposeImage(bmp)
    gdiplus.GdiplusShutdown(tok)


def main():
    from config import get_key
    key = get_key()

    p("=== 1) 起本机中转 ===")
    port = tile_proxy.start(key=key)
    p("    port = %s   key=%s...   stats = %s"
      % (port, (key or u"")[:8], json.dumps(tile_proxy.stats())))
    if not port:
        return 1

    p("=== 2) 探测 WMTS 子图层回读 ===")
    caps = tile_proxy.capabilities_url("img")
    p("    caps = %s" % caps)
    try:
        info = arcobjects.probe_wmts(caps, "img")
        for k in ("connected", "LayerName", "TileMatrixSet", "Style",
                  "ImageFormat", "Dimensions"):
            p("    %-14s = %r" % (k, info.get(k)))
    except Exception as e:
        p("    probe_wmts 失败 %r" % (e,))

    p("=== 3) 加图层（正式代码路径）===")
    for mt in ("img", "cia"):
        p("    add_tianditu(%r) -> %s" % (mt, lm.add_tianditu(mt)))

    m = arcobjects.current_map()
    p("    LayerCount = %s" % (m.LayerCount if m else None))
    p("    messages = %s" % (lm.get_messages(),))

    p("=== 4) 保持 %ds，观察是否出图 ===" % HOLD)
    for i in range(HOLD):
        time.sleep(1)
        if i % 15 == 0:
            st = tile_proxy.stats()
            p("    t=%3ds  tiles=%s caps=%s errors=%s"
              % (i, st["tiles"], st["caps"], st["errors"]))
            shot(str(i))

    st = tile_proxy.stats()
    p("=== 5) 汇总 ===")
    p("    %s" % json.dumps(st))
    try:
        lp = os.path.join(tile_proxy._LOG_DIR, "tile_proxy.log")
        lines = io.open(lp, "r", encoding="utf-8", errors="replace").readlines()
        p("    tile_proxy.log 末 12 行：")
        for ln in lines[-12:]:
            p("      " + ln.rstrip())
    except Exception as e:
        p("    读日志失败 %r" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
