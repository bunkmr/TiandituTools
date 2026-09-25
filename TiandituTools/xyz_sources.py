# -*- coding: utf-8 -*-
"""XYZ 瓦片图源 —— 把任意 {z}/{x}/{y} 模板翻译成 ArcMap 能吃的 WMTS。

为什么这么做（而不是"想办法给 ArcMap 加个 XYZ 图层"）
=====================================================

ArcMap 10.4 **没有** XYZ 瓦片这种图层类型：
  * arcpy 到 10.4 都没有 `MakeWMTSLayer`，更别提 XYZ；
  * `arcpy.mapping.Layer(<URL>)` 读不了在线服务；
  * ArcGIS 官方直到 Pro 才有"栅格切片底图图层"这回事。

但它有 WMTS。而 XYZ 与 WMTS 的差别**只在寻址方式**，服务本身、瓦片本身
是同一批字节：

    XYZ    https://host/path/{z}/{x}/{y}.png           （REST 模板）
    WMTS   同一服务，改按 KVP 问：TILEMATRIX=z&TILEROW=y&TILECOL=x

所以不必"发明图层"，只要把 XYZ 模板**翻译成一份 WMTS capabilities**，
再让本机中转（tile_proxy）在收到 WMTS 请求时反着翻译回 XYZ 去取瓦片。
ArcMap 那边看到的仍然是一个标准 WMTS 服务，走的还是已经调通的
`esriCarto.WMTSLayer` 通道（见 layer_manager 顶部「一」），零新增风险。

    ┌── ArcMap ──┐  WMTS(KVP)   ┌─ tile_proxy ─┐   XYZ(模板)  ┌─ 图源 ─┐
    │ WMTSLayer  │ ───────────> │ 翻译 + 代发  │ ──────────> │ XYZ 源 │
    └────────────┘              └──────────────┘             └────────┘

格网（TileMatrixSet）
=====================

统一用 Web Mercator（EPSG:3857）标准格网，参数与天地图 `/esri/wmts`
那份**逐位对齐** —— 那份已被实测证明 ArcMap 能正确算出瓦片行列并出图：

    TopLeftCorner      -20037508.3427892  20037508.3427892   <- 必须是左上角
    TileWidth/Height   256
    MatrixWidth = MatrixHeight = 2^z
    ScaleDenominator(z)          = 559082264.0287178 / 2^z

最后一行的来历：WMTS 规范里 ScaleDenominator = 分辨率 / 0.00028，而
Web Mercator 分辨率 res(z) = 156543.03392804097 / 2^z（256px 瓦片），
一除就是 559082264.0287178 / 2^z。z=1 得 279541132.014，
**正是天地图 `/esri/wmts` 第 1 级的数值** —— 对齐得刚刚好，不是巧合，
两边本来就是同一套 Web Mercator。

坐标系偏移（必须说清楚，别偷偷"修正"）
======================================

高德、腾讯这类国内源的瓦片是 **GCJ-02（火星坐标）**：投影仍是 Web
Mercator，但图上的地物位置整体偏移数百米。栅格瓦片**没法在不重采样的
前提下纠正**，所以在条目里记一个 `"datum": "gcj02"`，由 UI 明示用户 ——
叠加 WGS84 数据时会错位几百米，这是数据本身的属性，不是插件的问题。

百度是 BD-09，且自带一套非标准墨卡托变体（格网与 Web Mercator 对不上），
硬套只会满屏错位，故不支持。

依赖约束
========
纯标准库；**不 import arcpy、不 import Tkinter**。
既被 tile_server（独立进程）引用，也被 ui_menus / ui_xyz（界面进程）引用，
还被 layer_manager（ArcMap 进程）引用 —— 任何一边都不能拉重依赖进来。
"""

from __future__ import print_function

import hashlib
import io
import json
import os
import re
import sys
import time

#: py2 的 unicode 就是 py3 的 str。本模块既要被 ArcMap（py2.7）引用，
#: 也要能被项目里的 py3 开发脚本直接 import 做测试，所以两边的写法都留着。
try:
    text_type = unicode            # noqa: F821  (py2)
except NameError:                      # py3
    text_type = str

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# Web Mercator 格网常量（与天地图 /esri/wmts 对齐，改动前先读模块头）
# ---------------------------------------------------------------------------

HALF_WORLD = 20037508.3427892      # Web Mercator 半周长（米）
TILE_SIZE = 256
SCALE_Z0 = 559082264.0287178       # z=0 的比例尺分母

DEFAULT_ZMIN = 0
DEFAULT_ZMAX = 18

#: 本机中转上 XYZ 服务的路径前缀。与分析普通天地图服务的 `/{maptype}_w/`
#: 完全分开，一眼可辨，也不会跟某天新加的天地图服务名撞车。
PATH_PREFIX = u"/xyz/"

#: 可用的占位符（{x} {y} {z} {-y} {s} {tk} {token} ...）
_PLACEHOLDER_RE = re.compile(r"\{(-?[a-zA-Z][a-zA-Z0-9_]{0,7})\}")

#: 用户自定义源存在 config.json 的哪个键下
CONFIG_KEY = "xyzSources"


def _u(s):
    if s is None:
        return u""
    if isinstance(s, text_type):
        return s
    if isinstance(s, str):
        try:
            return s.decode("utf-8")
        except UnicodeDecodeError:
            return s.decode("gbk", "ignore")
    return text_type(s)


# ---------------------------------------------------------------------------
# 条目规整
# ---------------------------------------------------------------------------

def slug(text, fallback=u"src"):
    """把名字变成可安全放进 URL 路径的短 id"""
    t = _u(text).strip().lower()
    t = re.sub(r"[^a-z0-9]+", u"-", t).strip(u"-")
    return t[:24] or fallback


def id_from_url(url):
    """URL -> 稳定 id。

    用 md5 而不是自增序号：**id 必须能在两个进程里各算一遍还一致**
    （界面进程把它写进 config、中转进程按它查表），自增序号做不到。
    """
    h = hashlib.md5(_u(url).strip().encode("utf-8", "ignore")).hexdigest()
    return u"x" + h[:10]


def _norm_datum(v):
    d = _u(v).strip().lower()
    return d if d in (u"wgs84", u"gcj02", u"bd09") else u"wgs84"


def _norm_int(v, default):
    try:
        return int(v)
    except Exception:
        return default


def normalize(raw, group=u""):
    """把一条原始记录规整成内部统一形态；不是 XYZ 模板则返回 None。"""
    if not isinstance(raw, dict):
        return None
    url = _u(raw.get("url") or u"").strip()
    if not url or u"{" not in url:
        return None
    # 必须至少含一种行列占位符，否则不是瓦片模板
    if not re.search(r"\{(x|y|z|-y|q)\}", url, re.I):
        return None

    zmin = _norm_int(raw.get("zmin"), DEFAULT_ZMIN)
    zmax = _norm_int(raw.get("zmax"), DEFAULT_ZMAX)
    if zmax < zmin:
        zmin, zmax = zmax, zmin
    zmin = max(0, min(22, zmin))
    zmax = max(zmin, min(22, zmax))

    subs = raw.get("subdomains") or raw.get("subdomains_list") or []
    if isinstance(subs, (str, text_type)):
        subs = [s for s in _u(subs).split(u",") if s.strip()]
    subs = [_u(s).strip() for s in subs if _u(s).strip()]

    name = _u(raw.get("name") or u"").strip() or url
    sid = _u(raw.get("id") or u"").strip() or id_from_url(url)
    sid = slug(sid, u"x0") if not re.match(r"^[A-Za-z0-9_\-]+$", sid) else sid

    return {
        "id": sid,
        "name": name,
        "group": _u(raw.get("group") or group).strip(),
        "url": url,
        "zmin": zmin,
        "zmax": zmax,
        "subdomains": subs,
        "referer": _u(raw.get("referer") or u"").strip(),
        "headers": raw.get("headers") if isinstance(raw.get("headers"), dict) else {},
        "datum": _norm_datum(raw.get("datum")),
        # 三态：True 强制走代理 / False 强制直连 / None 跟随全局设置
        "proxy": raw.get("proxy") if isinstance(raw.get("proxy"), bool) else None,
        "note": _u(raw.get("note") or u"").strip(),
        "builtin": bool(raw.get("builtin")),
    }


# ---------------------------------------------------------------------------
# 装载：内置 maps/xyz.json + maps/extra.json 里的 XYZ 条目 + 用户 config
# ---------------------------------------------------------------------------

_cache = {"sig": None, "items": [], "by_id": {}}


def _config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, u"TiandituTools")


def _maps_dir():
    return os.path.join(_HERE, u"maps")


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0


def _read_json(path):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _signature():
    return (_mtime(os.path.join(_maps_dir(), u"xyz.json")),
            _mtime(os.path.join(_maps_dir(), u"extra.json")),
            _mtime(os.path.join(_config_dir(), u"config.json")))


def sources(reload=False):
    """全部可用 XYZ 源（内置 + 用户自定义），按组 -> 名字排序。

    带 mtime 签名缓存：中转进程里新加一个源不用重启服务，
    下次请求就生效（这一点很重要——用户不会为了加个图源去杀进程）。
    """
    sig = _signature()
    if not reload and _cache["sig"] == sig:
        return _cache["items"]

    items = []
    seen = set()

    # 1) 内置清单
    data = _read_json(os.path.join(_maps_dir(), u"xyz.json"))
    if isinstance(data, dict):
        for group in sorted(data.keys()):
            for raw in data[group] or []:
                if not isinstance(raw, dict):
                    continue
                raw = dict(raw)
                raw["builtin"] = True
                it = normalize(raw, group)
                if it and it["id"] not in seen:
                    seen.add(it["id"])
                    items.append(it)

    # 2) extra.json（"其他地图"）里本来就是 XYZ 模板的那些 —— 以前它们
    #    走到 add_map_from_catalog_entry 只会弹一句"不支持"，现在能直接用了。
    data = _read_json(os.path.join(_maps_dir(), u"extra.json"))
    if isinstance(data, dict):
        for group in sorted(data.keys()):
            for raw in data[group] or []:
                if not isinstance(raw, dict):
                    continue
                it = normalize(dict(raw, builtin=True), group)
                if it and it["id"] not in seen:
                    seen.add(it["id"])
                    items.append(it)

    # 3) 用户自定义
    conf = _read_json(os.path.join(_config_dir(), u"config.json")) or {}
    for raw in (conf.get(CONFIG_KEY) or []):
        it = normalize(raw, u"我的图源")
        if it and it["id"] not in seen:
            seen.add(it["id"])
            items.append(it)

    _cache["sig"] = sig
    _cache["items"] = items
    _cache["by_id"] = dict((i["id"], i) for i in items)
    return items


def find(sid, reload=False):
    """按 id 找源；找不到返回 None"""
    sources(reload)
    return _cache["by_id"].get(_u(sid).strip())


def groups():
    """[(组名, [源, ...]), ...]，保持稳定顺序"""
    out = []
    index = {}
    for it in sources():
        g = it.get("group") or u"其他"
        if g not in index:
            index[g] = []
            out.append((g, index[g]))
        index[g].append(it)
    return out


def user_sources():
    """只取用户自定义的（用于管理界面；内置的只读）"""
    conf = _read_json(os.path.join(_config_dir(), u"config.json")) or {}
    return [_u(r.get("name") or r.get("url") or u"") for r in (conf.get(CONFIG_KEY) or [])
            if isinstance(r, dict)]


def save_user_sources(items):
    """把用户自定义源写回 config.json。items 是 normalize() 形态的 dict 列表。"""
    import config as _config
    clean = []
    for it in items or []:
        clean.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "group": it.get("group") or u"我的图源",
            "url": it.get("url"),
            "zmin": it.get("zmin"),
            "zmax": it.get("zmax"),
            "subdomains": it.get("subdomains") or [],
            "referer": it.get("referer") or u"",
            "datum": it.get("datum") or u"wgs84",
            # 三态必须落盘：True/False/None，None 表示"跟随全局设置"。
            # （早先漏了这个键，用户在界面上选的"强制走代理"一保存就丢。）
            "proxy": it.get("proxy") if isinstance(it.get("proxy"), bool) else None,
            "note": it.get("note") or u"",
        })
    _config.save_config({CONFIG_KEY: clean})
    sources(reload=True)
    return clean


# ---------------------------------------------------------------------------
# capabilities / 瓦片地址
# ---------------------------------------------------------------------------

def _esc(s):
    return (_u(s).replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def scale_denominator(z):
    return SCALE_Z0 / float(1 << int(z))


def matrix_span(z):
    return 1 << int(z)


def tile_matrix_xml(entry):
    """按条目的 zmin..zmax 生成 <TileMatrix> 段"""
    zmin = int(entry.get("zmin") or 0)
    zmax = int(entry.get("zmax") or DEFAULT_ZMAX)
    out = []
    for z in range(zmin, zmax + 1):
        n = matrix_span(z)
        out.append(
            u"      <TileMatrix>\n"
            u"        <ows:Identifier>%d</ows:Identifier>\n"
            u"        <ScaleDenominator>%.9f</ScaleDenominator>\n"
            u"        <TopLeftCorner>-%s %s</TopLeftCorner>\n"
            u"        <TileWidth>%d</TileWidth>\n"
            u"        <TileHeight>%d</TileHeight>\n"
            u"        <MatrixWidth>%d</MatrixWidth>\n"
            u"        <MatrixHeight>%d</MatrixHeight>\n"
            u"      </TileMatrix>" % (z, scale_denominator(z), HALF_WORLD, HALF_WORLD,
                                      TILE_SIZE, TILE_SIZE, n, n))
    return u"\n".join(out)


def capabilities_url(sid, host_port, extra=u""):
    """本机 XYZ 服务的 GetCapabilities 地址（交给 ArcMap 的连接串）。

    路径带 `/esri/` 是与天地图那条已跑通的链路**保持一致**（见
    tile_proxy 顶部「六」）：虽然这份 capabilities 是我们自己合成的、
    不存在"两个端点"的问题，但让 ArcMap 面对同一种形状总归更稳。
    """
    u = (u"http://127.0.0.1:%d%s%s/esri/wmts"
         u"?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
         % (int(host_port), PATH_PREFIX, _u(sid)))
    if extra:
        u += u"&" + _u(extra)
    return u


def capabilities_xml(entry, host_port):
    """合成一份 ArcMap 能连、能算对行列的 WMTS capabilities。

    结构照抄天地图 `/esri/wmts` 那份（去掉它的 ows:Keywords 等装饰），
    只把 Contents 换成我们自己的图层与格网。
    """
    sid = _u(entry.get("id"))
    name = _u(entry.get("name")) or sid
    base = u"http://127.0.0.1:%d" % int(host_port)
    tile_path = u"%s%s%s/wmts" % (base, PATH_PREFIX, sid)
    caps_path = u"%s%s%s/esri/wmts" % (base, PATH_PREFIX, sid)

    # ArcMap 会把它的 KVP **无分隔符**地粘到 href 末尾（实测 tianditu 那条路上
    # 拼出来的是 `?tk=KEYservice=WMTS&request=GetTile...`）。所以模板里的参数
    # **顺序有讲究**：把 `FORMAT`（字符串型、且中转侧完全忽略）放在最后当"牺牲位"，
    # 粘上来的尾巴就落在它身上（`FORMAT=tilesSERVICE=WMTS`），
    # 不会污染 TILECOL 这种数值参数。数值参数另有一道"取前导整数"的兜底，
    # 见 tile_proxy 的 _int_param。
    tile_tmpl = (u"%s?SERVICE=WMTS&amp;REQUEST=GetTile&amp;VERSION=1.0.0"
                 u"&amp;LAYER=%s&amp;STYLE=default&amp;TILEMATRIXSET=w"
                 u"&amp;TILEMATRIX={TileMatrix}"
                 u"&amp;TILEROW={TileRow}"
                 u"&amp;TILECOL={TileCol}"
                 u"&amp;FORMAT=tiles" % (tile_path, _esc(sid)))

    return u"""<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="http://www.opengis.net/wmts/1.0"
    xmlns:ows="http://www.opengis.net/ows/1.1"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/wmts/1.0 http://schemas.opengis.net/wmts/1.0.0/wmtsGetCapabilities_response.xsd"
    version="1.0.0">
  <ows:ServiceIdentification>
    <ows:Title>%(name)s</ows:Title>
    <ows:Abstract>%(abstract)s</ows:Abstract>
    <ows:Keywords>
      <ows:Keyword>XYZ</ows:Keyword>
      <ows:Keyword>Web Mercator</ows:Keyword>
    </ows:Keywords>
    <ows:ServiceType codeSpace="wmts">OGC WMTS</ows:ServiceType>
    <ows:ServiceTypeVersion>1.0.0</ows:ServiceTypeVersion>
    <ows:Fees>none</ows:Fees>
    <ows:AccessConstraints>none</ows:AccessConstraints>
  </ows:ServiceIdentification>
  <ows:ServiceProvider>
    <ows:ProviderName>TiandituTools</ows:ProviderName>
    <ows:ProviderSite xlink:href="%(base)s"/>
    <ows:ServiceContact/>
  </ows:ServiceProvider>
  <ows:OperationsMetadata>
    <ows:Operation name="GetCapabilities">
      <ows:DCP><ows:HTTP><ows:Get xlink:href="%(caps)s?"/></ows:HTTP></ows:DCP>
    </ows:Operation>
    <ows:Operation name="GetTile">
      <ows:DCP><ows:HTTP><ows:Get xlink:href="%(tile)s?"/></ows:HTTP></ows:DCP>
    </ows:Operation>
  </ows:OperationsMetadata>
  <Contents>
    <Layer>
      <ows:Title>%(name)s</ows:Title>
      <ows:Identifier>%(sid)s</ows:Identifier>
      <ows:WGS84BoundingBox>
        <ows:LowerCorner>-180.0 -85.05112878</ows:LowerCorner>
        <ows:UpperCorner>180.0 85.05112878</ows:UpperCorner>
      </ows:WGS84BoundingBox>
      <Style isDefault="true">
        <ows:Identifier>default</ows:Identifier>
      </Style>
      <Format>image/png</Format>
      <Format>image/jpeg</Format>
      <TileMatrixSetLink>
        <TileMatrixSet>w</TileMatrixSet>
      </TileMatrixSetLink>
      <ResourceURL format="image/png" resourceType="tile" template="%(tile_tmpl)s"/>
    </Layer>
    <TileMatrixSet>
      <ows:Identifier>w</ows:Identifier>
      <ows:SupportedCRS>urn:ogc:def:crs:EPSG::3857</ows:SupportedCRS>
%(matrices)s
    </TileMatrixSet>
  </Contents>
  <ServiceMetadataURL xlink:href="%(caps)s"/>
</Capabilities>
""" % {
        "name": _esc(name),
        "abstract": _esc(u"由 TiandituTools 从 XYZ 瓦片模板转换：%s" % _u(entry.get("url"))),
        "base": _esc(base),
        "caps": _esc(caps_path),
        "tile": _esc(tile_path),
        "sid": _esc(sid),
        "tile_tmpl": tile_tmpl,
        "matrices": tile_matrix_xml(entry),
    }


def tile_url(entry, z, x, y, seq=0, key=u""):
    """按 XYZ 模板拼真实瓦片地址（含越界处理）。

    越界处理是必需的，不是保险丝：ArcMap 在边界和缩放过渡时会请求
    超出矩阵范围的行列（比如 z 比 zmin 还小、TileCol=-1）。直接透传
    会拿到 404 白图，画布上就是一块块空洞。
      * z  ->  夹到 [zmin, zmax]，并把 x/y 一起换算到该级
      * x  ->  按 2^z 取模（东西向环绕，跨 180° 经线才对）
      * y  ->  夹到 [0, 2^z-1]（南北向不环绕，多出来的是极区）

    支持的占位符：{x} {y} {z} {-y}(TMS 南起) {s}(子域) {tk}(天地图 Key)
    """
    tmpl = _u(entry.get("url"))
    zmin = int(entry.get("zmin") or 0)
    zmax = int(entry.get("zmax") or DEFAULT_ZMAX)

    try:
        zi = int(z)
    except Exception:
        zi = zmin
    zz = max(zmin, min(zmax, zi))

    try:
        x = int(x)
        y = int(y)
    except Exception:
        x = y = 0

    # 把请求级 (z) 的行列换算到实际使用的级 (zz)
    shift = zz - zi
    if shift > 0:
        x <<= shift
        y <<= shift
    elif shift < 0:
        x >>= -shift
        y >>= -shift

    n = matrix_span(zz)
    x = ((x % n) + n) % n
    y = max(0, min(n - 1, y))

    lower = tmpl.lower()
    subs = entry.get("subdomains") or []
    if u"{s}" in lower:
        if subs:
            sv = _u(subs[(x + y + int(seq)) % len(subs)])
        else:
            # 没给子域列表时的通行约定就是 0..3（高德 wprd01~04 那一路）
            sv = u"%d" % ((x + y) % 4)
    else:
        sv = u""

    # {-y} 必须在 {y} 之前替换 —— 否则先替掉 {y}，剩下的 -y} 就残缺了
    out = tmpl.replace(u"{-y}", u"\x00Y\x00").replace(u"{-Y}", u"\x00Y\x00")
    repl = {u"x": u"%d" % x, u"y": u"%d" % y, u"z": u"%d" % zz,
            u"s": sv, u"r": u"", u"tk": _u(key), u"token": _u(key)}
    out = _PLACEHOLDER_RE.sub(lambda m: repl.get(m.group(1).lower(), m.group(0)), out)
    out = out.replace(u"\x00Y\x00", u"%d" % (n - 1 - y))
    return out


# ---------------------------------------------------------------------------
# 连通性自检（给管理界面"测试"按钮用）
# ---------------------------------------------------------------------------

def lonlat_to_tile(lon, lat, z):
    """经纬度 -> 该级 XYZ 瓦片行列（Web Mercator 标准公式）"""
    import math
    n = 1 << int(z)
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = int((float(lon) + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


#: 自检取样点 —— **不能用世界中心**。经纬度 (0,0) 在几内亚湾，是纯海洋，
#: 任何矢量底图在那儿都是一张全透明的空白瓦片，测出来必然"失败"。
#: 取北京城区：国内源、国际源在该点都有要素，判断才有意义。
PROBE_LONLAT = (116.391, 39.907)


def _img_kind(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return u"PNG"
    if data[:3] == b"\xff\xd8\xff":
        return u"JPEG"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return u"GIF"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return u"WebP"
    return None


def probe(entry, timeout=8, key=None, lonlat=PROBE_LONLAT):
    """单独拉一张瓦片，返回 (ok, 说明文字)。

    默认取北京城区、zmin 与 zmax 的中间级那一张。

    判定口径：**只要能拿回一张真正的图片就算通**。空白瓦片（几百字节的
    透明 PNG）不算失败 —— 那说明服务是好的，只是该点没有要素；
    把这种情况说成"失败"会误导人（第一版自检就是这么误报的）。
    """
    try:
        import urllib2
    except ImportError:
        import urllib.request as urllib2     # py3

    if key is None and u"{tk}" in _u(entry.get("url")).lower():
        # 模板里要 Key 的（天地图 DataServer 那几条），自己去配置里取
        try:
            import config as _config
            key = _config.get_key()
        except Exception:
            key = u""

    z = int((int(entry.get("zmin") or 0) + int(entry.get("zmax") or 18)) / 2)
    x, y = lonlat_to_tile(lonlat[0], lonlat[1], z)
    url = tile_url(entry, z, x, y, key=key or u"")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if entry.get("referer"):
        headers["Referer"] = entry["referer"]
    headers.update(entry.get("headers") or {})

    try:
        req = urllib2.Request(url, headers=headers)
        # 绕开系统/环境代理：本机常驻 dev-sidecar 这类代理会把请求
        # 拐走（甚至只对某些域名生效），自检结果就不可信了。
        opener = urllib2.build_opener(urllib2.ProxyHandler({}))
        t0 = time.time()
        r = opener.open(req, timeout=timeout)
        data = r.read()
        ms = int((time.time() - t0) * 1000)
        ct = r.headers.get("Content-Type") or u"?"
    except Exception as e:
        return False, u"请求失败：%r\n%s" % (e, url)

    if not data:
        return False, u"返回空内容（%s）\n%s" % (ct, url)

    kind = _img_kind(data)
    if kind is None:
        head = data.lstrip()[:1]
        if head in (b"<", b"{"):
            return False, (u"返回的是文本，不是图片 —— 多半被拦截或模板不对。\n"
                           u"前 160 字节：%s" % data[:160])
        if data[:5] == b"<?xml" or data[:1] == b"<":
            return False, u"返回 XML，不是图片：%s" % data[:160]
        return False, (u"不是已知图片格式（Content-Type=%s，前 16 字节=%r）\n%s"
                       % (ct, data[:16], url))

    if len(data) < 400:
        return True, (u"服务可用：返回 %d 字节的空白/透明瓦片（该点无要素，"
                      u"属正常），%d ms（z=%d）" % (len(data), ms, z))
    return True, u"服务可用：%s，%d 字节，%d ms（z=%d）\n%s" % (kind, len(data), ms, z, url)
