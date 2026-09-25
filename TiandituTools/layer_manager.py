# -*- coding: utf-8 -*-
"""在线图层与搜索点结果添加。

设计要点（为什么是现在这样）
============================

**一、底图一律走 ArcObjects，不碰 arcpy**
  ArcMap 10.4 的 arcpy 既没有 MakeWMTSLayer，`arcpy.mapping.Layer(<URL>)` 也读不了
  在线服务，纯 arcpy 造不出在线图层。所以造 WMTS 图层只能用
  `esriGISClient.WMTSConnectionName` + `esriCarto.WMTSLayer`，
  再用 `esriFramework.esriAppROT` 找到**正在运行的 ArcMap**，
  `IApplication -> IMxDocument -> FocusMap(IMap) -> AddLayer(ILayer)`。

**二、造图层必须回到 ArcMap 进程内（这是踩出来的坑）**
  曾经为了「ArcMap 主线程完全不阻塞」，让界面子进程自己用 AppROT 把图层加进去。
  结果是致命的：`esriCarto.WMTSLayer` 是 in-proc 组件，在外部进程里 new 出来、
  再 `IMap.AddLayer` 传进 ArcMap，ArcMap 拿到的只是**跨进程代理**。
    * 代理在 → 图层在面板里，但画布空白（跨进程对象画不出来）；
    * 造它的进程一退出 → ArcMap 手里只剩断线代理，**数秒内直接崩**。
  所以现在的分工是：
    * 界面（Tkinter）→ 独立进程，ArcMap 进程里绝不碰 Tkinter；
    * 造图层 / 加图层 / 缩放 → **ArcMap 进程内**同步做完（本模块 + arcobjects）；
    * 主线程等待界面时**只等、不抽消息**（PumpWaitingMessages 会重入 ArcGIS
      消息循环，实测让 ArcMap 弹「遇到严重的应用程序错误」并被 CRT 中止）。

**三、绝不 import Tkinter 于 ArcMap 进程**
  提示在 ArcMap 进程内一律走官方 `pythonaddins.MessageBox`；
  在独立进程里才回退 Tkinter 对话框。剪贴板走系统 `clip.exe`。

**四、绝不 import arcpy 于 ArcMap 之外**
  外部进程 import arcpy 会拉进 arcgisscripting -> Geoprocessing ->
  RasterCore/RasterEngine -> **DFORRT.dll**（Fortran 运行时）。这些进程没有
  控制台，DFORRT 往 CONOUT$ 写诊断会失败，弹
  「Visual Fortran run-time error / forrtl: severe (38)」模态框并**永久卡死**。
  外部进程一律只写日志。

**五、底图必须经本机中转（tile_proxy），且 capabilities 必须取 `/esri/wmts` 那一份**
  天地图对瓦片有两条硬校验：URL 必须带 `tk`（缺了返回 **418**），请求头必须
  有非空 `User-Agent`（缺了返回 **403「Key权限类型为:浏览器端」**）。
  而天地图 capabilities 里 GetTile 端点写的是
  `http://t0.tianditu.gov.cn/img_w/wmts?` —— **不含 tk**，也没有 `<ResourceURL>`
  瓦片模板，ArcMap 只能照着这个 href 自己拼，于是必然丢掉 tk。
  这两条在 ArcMap 里都改不了，只能在中间加一层把 tk 和 UA 补齐。
  详见 tile_proxy 模块顶部说明。

  另外还有一条更隐蔽的：天地图为 ArcGIS 单开了端点
  `/{maptype}_w/esri/wmts`，它的 capabilities 里 TopLeftCorner 的 X/Y 顺序正确、
  ScaleDenominator 也跟 ArcGIS 自己的 Web Mercator 分级逐级对齐；用普通
  `/wmts` 那份 capabilities，ArcMap 算出来的瓦片行列全错，画布就是全白。
  所以 capabilities 一律走 `/esri/wmts`，瓦片仍走 `/wmts`。详见 tile_proxy 顶部「六」。
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import os
import re
import subprocess
import traceback

import arcobjects
import tile_proxy
from config import get_key
from tianditu_api import (TIANDITU_MAP_INFO, TIANDITU_MAP_GROUPS,
                          wmts_capabilities_url, as_arcgis_caps, _to_unicode)

try:
    import xyz_sources
except Exception:                       # 缺文件时只是没有 XYZ 功能，不影响天地图
    xyz_sources = None

# ---------------------------------------------------------------------------
# 消息：ArcMap 进程内用官方 MessageBox；独立进程才允许 Tkinter
# ---------------------------------------------------------------------------

_last_messages = []


def _tb():
    """traceback 是 bytes，直接塞进 u"..." % 会 UnicodeDecodeError —— 统一转好。"""
    return _to_unicode(traceback.format_exc())


def _in_arcmap():
    """当前是否运行在 ArcMap 进程内（有 pythonaddins 就是）"""
    try:
        import pythonaddins                            # noqa: F401
        return True
    except Exception:
        return False


def _log_file(text):
    """把提示同时落一份到文件 —— 否则出问题时只能去 ArcMap 结果窗口里翻，
    自动化排查根本看不到（_push 在 ArcMap 进程内是走 arcpy.AddMessage 的）。"""
    try:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                         "TiandituTools")
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(os.path.join(d, "layer_manager.log"), "ab") as f:
            f.write((text + u"\n").encode("utf-8", "ignore"))
    except Exception:
        pass


def _push(title, message, level="info"):
    """把提示挂到 ArcMap 的结果窗口，**并且**始终落一份日志文件。

    **只在 ArcMap 进程内**才 import arcpy：在 ArcMap 之外 import arcpy 会把
    Geoprocessing / RasterEngine / DFORRT（Fortran 运行时）整条栈拉进那个进程，
    而外部辅助进程没有控制台，DFORRT 写 CONOUT$ 会失败并弹模态框卡死进程。
    """
    text = u"[%s] %s: %s" % (level, _to_unicode(title), _to_unicode(message))
    _last_messages.append(text)
    _log_file(text)
    if not _in_arcmap():
        return
    try:
        import arcpy

        if level == "error":
            arcpy.AddError(text)
        else:
            arcpy.AddMessage(text)
    except Exception:
        pass


def get_messages():
    return list(_last_messages)


def _msgbox(text, kind="info"):
    """ArcMap 进程内用官方 MessageBox；独立进程用 Tkinter。"""
    text = _to_unicode(text)

    # 自动化测试/无声环境下不弹窗（否则会阻塞脚本）
    if os.environ.get("TIANDITU_NO_UI"):
        _push(u"天地图 Tools", text, kind if kind in ("error", "warning") else "info")
        return None

    try:
        import pythonaddins
        flags = {"error": 16, "warning": 48}.get(kind, 64)
        return pythonaddins.MessageBox(text, u"天地图 Tools", flags)
    except Exception:
        pass
    try:
        import tkMessageBox
        fn = {"error": tkMessageBox.showerror,
              "warning": tkMessageBox.showwarning}.get(kind, tkMessageBox.showinfo)
        return fn(u"天地图 Tools", text)
    except Exception:
        _push(u"天地图 Tools", text, "error")
        return None


def _copy_to_clipboard(text):
    """用系统自带 clip.exe —— 不依赖 Tkinter/win32clipboard"""
    try:
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
        p.communicate(_to_unicode(text).encode("mbcs", "ignore"))
        return p.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 当前地图里的图层名单（优先 ArcObjects，arcpy 仅作补充）
# ---------------------------------------------------------------------------

def _toc_names():
    """当前地图顶层图层名列表；失败返回 []"""
    names = []
    try:
        m = arcobjects.current_map()
        if m is not None:
            for i in range(m.LayerCount):
                try:
                    names.append(_to_unicode(m.Layer[i].Name))
                except Exception:
                    pass
            return names
    except Exception:
        pass
    # ArcMap 进程内且 ArcObjects 不可用时，才用 arcpy 兜底
    if not _in_arcmap():
        return names
    try:
        import arcpy
        mxd = arcpy.mapping.MapDocument("CURRENT")
        for lyr in arcpy.mapping.ListLayers(mxd) or []:
            try:
                names.append(_to_unicode(lyr.name))
            except Exception:
                pass
    except Exception:
        pass
    return names


def _toc_has_layer(name):
    want = _to_unicode(name).strip()
    return any(n.strip() == want for n in _toc_names())


def _refresh_fallback():
    """重绘。ArcObjects 优先；只有 ArcMap 进程内才退回 arcpy。"""
    if arcobjects.zoom_full_extent():
        return
    if not _in_arcmap():
        return
    try:
        import arcpy
        arcpy.RefreshActiveView()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ArcObjects 通道
# ---------------------------------------------------------------------------

_cold_warned = {"done": False}


def _warn_cold_types():
    """首次要生成 ArcGIS 类型库（一次 1~2 分钟），提前打招呼"""
    if _cold_warned["done"]:
        return
    _cold_warned["done"] = True
    _msgbox(
        u"首次自动添加在线底图需要初始化 ArcGIS 类型库（约 1~2 分钟），\n"
        u"这期间窗口可能短暂无响应。\n\n"
        u"点「确定」后请耐心等待，只此一次，之后就是秒开。",
        "info",
    )


def ao_ready():
    """现在能不能走 ArcObjects 通道"""
    if not arcobjects.available():
        return False
    if not arcobjects.is_cached():
        _warn_cold_types()
    return True


# ---------------------------------------------------------------------------
# 本机中转（tile_proxy）—— 天地图瓦片的 tk / UA 两条校验靠它补齐
# ---------------------------------------------------------------------------

def ensure_tile_proxy(key=None):
    """确保**独立进程**的中转服务在跑，返回端口；失败返回 0。幂等。

    服务器**绝不跑在 ArcMap 进程里**。实测：进程内起 HTTP 服务器时，画了
    几张瓦片之后它的 accept 循环就不再接受连接（端口还在 LISTENING，但
    连接队列满了、新 SYN 被内核丢弃），ArcMap 的瓦片请求全卡在 SYN_SENT，
    绘制线程假死、主线程跟着假死 —— 用户看到的就是「能加载、不能放大」。
    改到独立进程后 ArcMap 里不再有服务器线程，且端口固定，
    重启 ArcMap 后旧文档里的图层也照样能出图。详见 tile_server.py。
    """
    key = key or get_key()
    try:
        p = tile_proxy.ensure_external()
    except Exception:
        p = 0
    if not p and os.environ.get("TIANDITU_ALLOW_INPROC_RELAY") == "1":
        # 兜底（**默认关闭**）。进程内中转会卡死 ArcMap，这是能把整个
        # ArcMap 冻住的路径，所以只在显式设了环境变量时才允许 ——
        # 「起不来就报错」远好过「起得来但把 ArcMap 冻死」。
        try:
            p = tile_proxy.start(key=key)
            if p:
                _push(u"底图", u"已按 TIANDITU_ALLOW_INPROC_RELAY 退回进程内中转"
                                u"（有卡死风险）", "warning")
        except Exception:
            p = 0
    if not p:
        _push(u"底图", u"本机中转服务启动失败，底图无法加载（请查看 "
                        u"%s\\tile_proxy.log）" % _log_dir_hint(), "error")
        return 0
    return p


def _log_dir_hint():
    """日志目录，报错时告诉用户去哪儿看"""
    return os.path.join(os.environ.get("APPDATA") or u"", "TiandituTools")


def local_caps_url(maptype, key=None):
    """天地图某个底图的**本机** GetCapabilities 地址（ArcMap 用这个连）。

    直接用天地图原始地址是不行的：它的 GetTile 端点不带 tk，ArcMap 拼出来的
    瓦片请求会被 CloudWAF 拦（418）；就算带上 tk，ArcMap 请求头里没有
    User-Agent 时也还是 403。中转服务把这两样补齐，ArcMap 才画得出来。
    """
    key = key or get_key()
    p = ensure_tile_proxy(key)
    if not p:
        return None
    return tile_proxy.capabilities_url(maptype, key=key, host_port=p)


# ---------------------------------------------------------------------------
# ArcObjects 通道
# ---------------------------------------------------------------------------

_cold_warned = {"done": False}


def _ao_add_group(pairs):
    """pairs = [(caps_url, display_name, layer_id), ...]，**按显示顺序上 -> 下** 给出。

    `layer_id` 是 WMTS 子图层 Identifier（天地图 = maptype）。必须传，
    否则 ArcMap 连上服务却选不中子图层，一发瓦片都不请求。
    """
    if not pairs:
        return False
    norm = [(t[0], t[1], (t[2] if len(t) > 2 else None)) for t in pairs]
    try:
        ilayers = [arcobjects.create_wmts_layer(url, name, lid)
                   for url, name, lid in norm]
        arcobjects.add_layers_bottom(ilayers)
        # 关键：AddLayer 不会自动缩放，新建的空地图范围是 (0,0)-(0,0)，
        # 不缩放到全图就会「图层在、画布空白」。
        arcobjects.zoom_full_extent()
        _push(u"底图", u"已自动添加: %s" % u", ".join(n for _, n, _ in norm))
        return True
    except Exception:
        _push(u"底图", u"ArcObjects 添加失败:\n%s" % _tb(), "warning")
        _refresh_fallback()
        return False


# ---------------------------------------------------------------------------
# 图层添加入口
# ---------------------------------------------------------------------------

_WMTS_STEPS = (
    u"自动添加在线底图失败（ArcObjects 不可用）。\n\n"
    u"服务地址已复制到剪贴板，手工添加只需一次：\n"
    u"  1. 菜单：文件 → 添加数据 → 添加数据(Add Data)\n"
    u"  2. 双击 «GIS 服务器» → «添加 WMTS 服务器»\n"
    u"  3. 在 «URL» 里 Ctrl+V 粘贴 → 确定\n"
    u"  4. 展开刚连上的服务，选中图层「%s」→ 添加"
)


def _wmts_manual_hint(caps_url, display_name):
    caps_url = _to_unicode(caps_url)
    display_name = _to_unicode(display_name)
    copied = _copy_to_clipboard(caps_url)
    msg = _WMTS_STEPS % display_name
    if not copied:
        msg += u"\n\n（自动复制失败，请手动复制：\n%s）" % caps_url
    _msgbox(msg, "info")
    return False


def add_wmts_layer(caps_url, display_name, layer_id=None):
    """添加单个 WMTS 图层：ArcObjects → 失败给手工指引

    `layer_id` = WMTS 子图层 Identifier；不传的话 ArcMap 连得上服务却
    选不中子图层，一发瓦片都不请求（画布空白）。
    """
    caps_url = _to_unicode(caps_url)
    display_name = _to_unicode(display_name)
    if not caps_url:
        _push(u"底图", u"WMTS 地址为空", "error")
        return False

    if _toc_has_layer(display_name):
        _push(u"底图", u"图层已存在: %s" % display_name)
        return True

    if ao_ready() and _ao_add_group([(caps_url, display_name, layer_id)]):
        return True

    return _wmts_manual_hint(caps_url, display_name)


def add_tianditu(maptype):
    """添加单个天地图 WMTS 图层（经本机中转，见模块顶部「五」）"""
    key = get_key()
    if not key:
        _show_need_key()
        return False
    name = TIANDITU_MAP_INFO.get(maptype, maptype)
    caps = local_caps_url(maptype, key) or wmts_capabilities_url(maptype, key=key)
    return add_wmts_layer(caps, name, layer_id=maptype)


def add_tianditu_group(group_key, layers, group_name):
    """添加含注记图层组。

    `layers` 的顺序就是显示顺序（**上 -> 下**），例如 ["cva", "vec"]：
    注记在上、底图在下，ArcMap 里这样叠才对。
    """
    key = get_key()
    if not key:
        _show_need_key()
        return False

    pairs = []
    for mt in layers:
        caps = local_caps_url(mt, key) or wmts_capabilities_url(mt, key=key)
        pairs.append((caps, TIANDITU_MAP_INFO.get(mt, mt), mt))

    if all(_toc_has_layer(n) for _, n, _ in pairs):
        _push(u"底图", u"图层组已存在: %s" % _to_unicode(group_name))
        return True

    if ao_ready() and _ao_add_group(pairs):
        _push(u"底图", u"图层组: %s" % _to_unicode(group_name))
        return True

    ok_any = False
    for mt in reversed(list(layers)):
        caps = local_caps_url(mt, key) or wmts_capabilities_url(mt, key=key)
        name = TIANDITU_MAP_INFO.get(mt, mt)
        if add_wmts_layer(caps, name, layer_id=mt):
            ok_any = True
    if ok_any:
        _push(u"底图", u"图层组: %s" % _to_unicode(group_name))
    return ok_any


def add_tianditu_from_group_def(group_key):
    for key, name, layers in TIANDITU_MAP_GROUPS:
        if key == group_key:
            return add_tianditu_group(key, layers, name)
    return add_tianditu(group_key)


def _guess_layer_id(url):
    """从 URL 里猜 WMTS 子图层 Identifier（天地图形如 /img_w/wmts -> img）

    注意要跳过 `esri`：ArcGIS 专用端点形如 `/img_w/esri/wmts`，
    倒着扫的时候会先撞上 `esri`，不跳过就会返回 `esri` 这个根本不存在的图层名。
    """
    try:
        u = _to_unicode(url)
        seg = u.split(u"?")[0].rstrip(u"/").split(u"/")
        for s in reversed(seg):
            if s.endswith(u"_w"):
                return s[:-2]
            if s and s not in (u"wmts", u"wms", u"esri"):
                return s
    except Exception:
        pass
    return None


def add_map_from_catalog_entry(entry):
    """按 xyz.json / extra.json / province.json 的条目添加。

    判定顺序很重要：**先看它是不是 XYZ 模板**。以前这里只有最后一句
    `_xyz_not_supported`，于是 extra.json 里那一整批 XYZ 图源
    （Google / Esri / 高德 / OpenRailwayMap）点一下只弹一句"不支持"。
    现在它们全部走 add_xyz_layer。
    """
    if not entry:
        return False
    name = _to_unicode(entry.get("name") or u"在线地图")
    layer = _to_unicode(entry.get("layer") or u"") or None
    url = _to_unicode(entry.get("url") or u"")

    # ① XYZ 模板（含 {z}/{x}/{y} 之类占位符）—— 本模块的翻译通道
    if xyz_sources is not None and re.search(r"\{(x|y|z|-y|q)\}", url, re.I):
        return add_xyz_layer(entry)

    if entry.get("capabilities"):
        caps = _to_unicode(entry["capabilities"])
        return add_wmts_layer(caps, name, layer or _guess_layer_id(caps))

    if entry.get("uri"):
        caps = _qgis_wmts_uri_to_capabilities(_to_unicode(entry["uri"]))
        if caps:
            return add_wmts_layer(caps, name, layer or _guess_layer_id(caps))
        _push(u"底图", u"无法解析 uri: %s" % name, "error")
        return False

    if not url:
        return False

    if u"REQUEST=GetCapabilities" in url.upper():
        return add_wmts_layer(url, name, layer or _guess_layer_id(url))

    if u"/wmts" in url and u"tk=" in url:
        caps = _tile_template_to_capabilities(url)
        if caps:
            return add_wmts_layer(caps, name, layer or _guess_layer_id(caps))

    if u"MapServer" in url or u"ImageServer" in url:
        return _wmts_manual_hint(url, name)

    _copy_to_clipboard(url)
    _msgbox(
        u"这个地址既不是 WMTS、也不是 XYZ 瓦片模板，插件无法直接添加。\n\n"
        u"图层：%s\n\n地址已复制到剪贴板：\n%s\n\n"
        u"XYZ 模板需要形如 https://host/path/{z}/{x}/{y}.png"
        % (name, url),
        "info",
    )
    return False


def _tile_template_to_capabilities(url):
    base = as_arcgis_caps(url.split("?")[0])
    tk = u""
    if u"tk=" in url:
        tk = url.split(u"tk=", 1)[1].split(u"&", 1)[0]
    caps = u"%s?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0" % base
    if tk:
        caps += u"&tk=%s" % tk
    return caps


def _qgis_wmts_uri_to_capabilities(uri):
    parts = {}
    for seg in uri.split("&"):
        if u"=" in seg:
            k, v = seg.split(u"=", 1)
            parts[k] = v
    base = parts.get(u"url")
    if not base:
        return None
    if u"?" in base:
        return as_arcgis_caps(base)
    return u"%s?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0" % as_arcgis_caps(base)


def _xyz_not_supported(name, url):
    """历史遗留：ArcMap 10.4 确实没有"XYZ 图层"这种类型。

    但**不等于不能用 XYZ 图源** —— 插件把 XYZ 模板翻译成本机 WMTS
    （见 xyz_sources 顶部），所以正常路径根本不会走到这里。
    保留它只是给"地址连模板都不是"的情况一句明确的话。
    """
    _copy_to_clipboard(url)
    _msgbox(
        u"这个地址不是瓦片模板，插件无法转换。\n\n"
        u"图层：%s\n\n地址已复制到剪贴板：\n%s"
        % (_to_unicode(name), _to_unicode(url)),
        "info",
    )
    return False


# ---------------------------------------------------------------------------
# XYZ 图源（翻译成本机 WMTS 再走同一条 ArcObjects 通道）
# ---------------------------------------------------------------------------

_gcj_warned = {"done": False}


def add_xyz_layer(entry):
    """添加一个 XYZ 瓦片图源。

    链路：XYZ 模板 ->（xyz_sources 合成 capabilities）-> 本机中转
          ->（ArcMap 当普通 WMTS 连）-> ArcObjects 造图层

    所以这里做的事只有两件：确保中转在跑、把本机 caps 地址交给
    add_wmts_layer —— 与天地图那条路**完全共用**后续代码，不引入新分支。
    """
    if xyz_sources is None:
        _push(u"底图", u"缺少 xyz_sources.py，无法添加 XYZ 图源", "error")
        return False

    # 带 id 的说明已经在 xyz_sources.sources() 里规整过了，直接用；
    # 只有用户手填的原始记录才需要 normalize 一遍。
    it = dict(entry) if entry.get("id") else xyz_sources.normalize(entry)
    if not it:
        _push(u"底图", u"XYZ 图源地址不合法（需要形如 …/{z}/{x}/{y}.png 的模板）",
              "error")
        return False
    it = dict(it)
    it.setdefault("zmin", xyz_sources.DEFAULT_ZMIN)
    it.setdefault("zmax", xyz_sources.DEFAULT_ZMAX)
    it.setdefault("subdomains", [])
    it.setdefault("referer", u"")
    it.setdefault("datum", u"wgs84")
    url_tmpl = _to_unicode(it.get("url") or u"")
    name = _to_unicode(it.get("name") or u"XYZ 图源")

    if not url_tmpl:
        _push(u"底图", u"XYZ 图源缺少 url", "error")
        return False

    key = get_key()
    if u"{tk}" in url_tmpl.lower() and not key:
        _show_need_key()
        return False

    # XYZ 也要中转：ArcMap 得连一个 WMTS，而"把 XYZ 翻译成 WMTS"这件事
    # 只有在我们的中转进程里才做得了（见 xyz_sources 顶部）。
    p = ensure_tile_proxy(key)
    if not p:
        return False

    caps = xyz_sources.capabilities_url(it["id"], p)
    if _toc_has_layer(name):
        _push(u"底图", u"图层已存在: %s" % name)
        return True

    if not (ao_ready() and _ao_add_group([(caps, name, it["id"])])):
        return _wmts_manual_hint(caps, name)

    if it.get("datum") == u"gcj02" and not _gcj_warned["done"]:
        # 只提醒一次。栅格瓦片没法在不重采样的前提下纠偏，这属于数据本身的
        # 属性（GCJ-02 火星坐标），不说明白用户会以为插件算错了。
        _gcj_warned["done"] = True
        _msgbox(
            u"「%s」是 GCJ-02（火星坐标）底图。\n\n"
            u"它在 Web Mercator 下的投影是正确的，但图上的地物位置本身\n"
            u"就比 WGS84/GPS 偏了约 300~600 米。\n"
            u"叠加你自己的 WGS84 数据时会出现整体错位 —— 这是数据源的属性，"
            u"不是插件的问题，也无法通过设置消除。\n\n"
            u"需要严格套合的场合，请改用天地图或 Esri 这类 WGS84 底图。" % name,
            "info",
        )
    return True


def _show_need_key():
    _msgbox(
        u"天地图 Key 未设置或无效。\n\n"
        u"请点击工具栏「设置」填写天地图 Key（浏览器端类型，32 位）。\n"
        u"申请地址：https://console.tianditu.gov.cn/api/key",
        "warning",
    )


# ---------------------------------------------------------------------------
# 应用到地图的总入口（界面子进程与 ArcMap 进程都可调用）
# ---------------------------------------------------------------------------

def apply_basemap(payload):
    """按 payload 添加底图；返回是否成功。**不依赖 arcpy**，可在任意进程调用。"""
    kind = (payload or {}).get("kind")
    try:
        if kind == "maptype":
            return add_tianditu(payload.get("maptype"))
        if kind == "group":
            return add_tianditu_from_group_def(payload.get("key"))
        if kind == "catalog":
            return add_map_from_catalog_entry(payload.get("entry") or {})
        if kind == "xyz":
            # 界面子进程回传时 payload 已经 JSON 化，entry 是纯 dict，
            # add_xyz_layer 只认字段，不认 Python 对象，所以没问题。
            return add_xyz_layer(payload.get("entry") or {})
    except Exception:
        _push(u"底图", u"应用底图失败:\n%s" % _tb(), "error")
        return False
    _push(u"底图", u"未知的底图类型: %r" % (kind,), "error")
    return False


# ---------------------------------------------------------------------------
# 搜索结果点图层（纯 arcpy，**仅限 ArcMap 进程内**）
# ---------------------------------------------------------------------------

def add_point_result(name, lon, lat, zoom=True):
    """创建点要素并加入地图、缩放"""
    import arcpy

    name = _to_unicode(name)
    lon = float(lon)
    lat = float(lat)

    mxd = arcpy.mapping.MapDocument("CURRENT")
    df = arcpy.mapping.ListDataFrames(mxd)[0]

    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="tdt_")
    csv_path = os.path.join(tmp_dir, "result.csv")
    with open(csv_path, "wb") as f:
        f.write(b"Name,Lon,Lat\n")
        f.write((u'%s,%f,%f\n' % (name.replace(u'"', u""), lon, lat)).encode("utf-8"))

    xy_layer = "tdt_xy_temp"
    if arcpy.Exists(xy_layer):
        try:
            arcpy.Delete_management(xy_layer)
        except Exception:
            pass

    arcpy.MakeXYEventLayer_management(
        csv_path, "Lon", "Lat", xy_layer, "GCS_WGS_1984", "", "GCS_WGS_1984",
    )

    layer_name = name[:40] or u"搜索结果"
    try:
        arcpy.management.MakeFeatureLayer(xy_layer, layer_name)
        lyr = arcpy.mapping.Layer(xy_layer)
        try:
            lyr.name = layer_name
        except Exception:
            pass
        arcpy.mapping.AddLayer(df, lyr, "TOP")

        if zoom:
            try:
                from arcpy import Extent
                ext = lyr.extent
                cx = (ext.XMin + ext.XMax) / 2.0
                cy = (ext.YMin + ext.YMax) / 2.0
                pad = 0.002
                df.extent = Extent(cx - pad, cy - pad, cx + pad, cy + pad)
            except Exception:
                try:
                    df.extent = lyr.extent
                except Exception:
                    pass
            _refresh_fallback()
        _push(u"搜索", u"已添加点: %s" % layer_name)
        return True
    except Exception:
        tb = _tb()
        _push(u"搜索", tb, "error")
        _msgbox(
            u"添加点失败：\n%s\n\n点: %s (%.6f, %.6f)"
            % (tb[-400:], name, lon, lat),
            "error",
        )
        return False
