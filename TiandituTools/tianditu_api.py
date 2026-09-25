# -*- coding: utf-8 -*-

"""天地图 URL 构造与 Web API（Python 2.7）"""

from __future__ import print_function

import os as _os, sys as _sys
_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import json
import urllib
import urllib2

from config import get_key, get_subdomain

TIANDITU_HOME = u"https://www.tianditu.gov.cn/"
HEADERS = {
    "User-Agent": u"Mozilla/5.0 TiandituTools/1.0 ArcMap/10.2",
    "Referer": u"https://www.tianditu.gov.cn/",
}

TIANDITU_MAP_INFO = {
    "vec": u"天地图-矢量地图",
    "cva": u"天地图-矢量注记",
    "img": u"天地图-影像地图",
    "cia": u"天地图-影像注记",
    "ter": u"天地图-地形晕染",
    "cta": u"天地图-地形注记",
    "ibo": u"天地图-全球境界",
    "terrain": u"天地图-山体阴影",
}

TIANDITU_MAP_GROUPS = [
    (u"vec+cva", u"天地图-矢量地图(含注记)", ["cva", "vec"]),
    (u"img+cia", u"天地图-影像地图(含注记)", ["cia", "img"]),
    (u"ter+cta", u"天地图-地形晕染(含注记)", ["cta", "ter"]),
]


def _to_unicode(s):
    if s is None:
        return u""
    if isinstance(s, unicode):  # noqa: F821 — py2
        return s
    if isinstance(s, str):
        try:
            return s.decode("utf-8")
        except UnicodeDecodeError:
            return s.decode("gbk", "ignore")
    return unicode(s)  # noqa: F821


#: ArcGIS 专用路径段。天地图为 ArcGIS 单独开了一个端点：
#:     http://t0.tianditu.gov.cn/img_w/esri/wmts      <- ArcMap 必须用这个
#:     http://t0.tianditu.gov.cn/img_w/wmts           <- 通用 WMTS，ArcMap 用它会全白
#:
#: 两个端点返回的 capabilities **不一样**，差别正是「画不出来」的根因：
#:
#:   * TopLeftCorner 的 X/Y 顺序
#:       /wmts       -> "20037508.3427892 -20037508.3427892"（其实是右下角，标成了左上角）
#:       /esri/wmts  -> "-20037508.3427892 20037508.3427892"（正确的左上角）
#:     ArcMap 按 TopLeftCorner 反算瓦片的行列号，X/Y 一反算，行列全错 -> 空白。
#:
#:   * ScaleDenominator 是否对齐 ArcGIS 自己的 Web Mercator 分级
#:       /wmts       第 1 级 = 2.958293554545656E8（天地图自己的分级）
#:       /esri/wmts  第 1 级 = 2.795411320143237E8
#:                    = 559082264.0287178 / 2 = ArcGIS 第 1 级，逐级都对得上
#:
#: 注意：`/esri/wmts` **只服务 GetCapabilities** —— 用同样的路径去要瓦片，
#: 它会把 capabilities 文档原样再吐一遍（实测 11619 字节 = caps 大小）。
#: 瓦片仍走 `/wmts`，capabilities 里的 GetTile href 也正是指向 `/wmts`。
#: 所以：**capabilities 用 /esri/wmts，瓦片用 /wmts**，两边分工不能搞反。
ARCGIS_SEGMENT = u"esri"


def wmts_capabilities_url(maptype, key=None, subdomain=None, arcgis=True):
    """天地图 WMTS GetCapabilities 地址。

    `arcgis=True`（默认）走 ArcGIS 专用端点 `/{maptype}_w/esri/wmts` ——
    **ArcMap 必须用这个**，原因见 ARCGIS_SEGMENT 上面那段。
    """
    if key is None:
        key = get_key()
    if subdomain is None:
        subdomain = get_subdomain()
    domain = u"https://%s.tianditu.gov.cn" % _to_unicode(subdomain)
    seg = ARCGIS_SEGMENT + u"/" if arcgis else u""
    url = u"%s/%s_w/%swmts?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s"
    return url % (domain, _to_unicode(maptype), seg, _to_unicode(key))


def as_arcgis_caps(url):
    """把任意天地图 WMTS 服务器地址规整成 ArcMap 该用的 `/esri/wmts` 形式。

    只改路径，不动查询串里的 tk；已经是 /esri/wmts 的原样返回。
    """
    u = _to_unicode(url)
    if u"/esri/wmts" in u:
        return u
    return u.replace(u"_w/wmts", u"_w/esri/wmts").replace(u"_c/wmts", u"_c/esri/wmts")


def wmts_gettile_url(maptype, key=None, subdomain=None):
    """瓦片模板（备用 / 校验）"""
    if key is None:
        key = get_key()
    if subdomain is None:
        subdomain = get_subdomain()
    domain = u"https://%s.tianditu.gov.cn" % _to_unicode(subdomain)
    url = (
        u"%s/%s_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        u"&LAYER=%s&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
        u"&TileCol={x}&TileRow={y}&TileMatrix={z}&tk=%s"
    )
    mt = _to_unicode(maptype)
    return url % (domain, mt, mt, _to_unicode(key))


def http_get_json(url, params=None, timeout=12):
    """GET 请求并解析 JSON；失败返回 None"""
    if params:
        if isinstance(params, dict):
            q = urllib.urlencode(params)
        else:
            q = params
        url = u"%s?%s" % (_to_unicode(url), _to_unicode(q))
    req = urllib2.Request(url.encode("utf-8") if isinstance(url, unicode) else url)
    for k, v in HEADERS.items():
        req.add_header(
            k.encode("ascii"),
            v.encode("utf-8") if isinstance(v, unicode) else str(v),
        )
    try:
        resp = urllib2.urlopen(req, timeout=timeout)
        raw = resp.read()
        resp.close()
    except Exception:
        return None
    if not raw:
        return None
    try:
        if isinstance(raw, str):
            raw = raw.decode("utf-8", "ignore")
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None


def http_get_bytes(url, timeout=10):
    req = urllib2.Request(url.encode("utf-8") if isinstance(url, unicode) else url)
    for k, v in HEADERS.items():
        req.add_header(
            k.encode("ascii"),
            v.encode("utf-8") if isinstance(v, unicode) else str(v),
        )
    try:
        resp = urllib2.urlopen(req, timeout=timeout)
        data = resp.read()
        resp.close()
        return data
    except Exception:
        return None


def check_key(key):
    """用 0/0/0 矢量瓦片校验 Key；返回 (ok, message)"""
    key = _to_unicode(key).strip()
    if len(key) != 32:
        return False, u"无效key: 格式错误(长度应为32)"
    if not key.isalnum():
        return False, u"无效key: 含非常规字符"
    url = wmts_gettile_url("vec", key=key, subdomain=u"t0")
    url = url.format(x=0, y=0, z=0)
    data = http_get_bytes(url, timeout=8)
    if data is None:
        return False, u"网络错误或无法访问天地图服务"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return True, u"保存成功"
    if data[:3] in (b"\xff\xd8\xff",):
        return True, u"保存成功"
    # 服务端可能返回 JSON 错误
    try:
        txt = data.decode("utf-8", "ignore")
        obj = json.loads(txt)
        if isinstance(obj, dict):
            msg = obj.get("msg") or obj.get("message") or u""
            resolve = obj.get("resolve") or u""
            return False, u"错误: %s %s" % (_to_unicode(msg), _to_unicode(resolve))
    except (ValueError, AttributeError):
        pass
    if len(data) < 50:
        return False, u"Key 校验失败: 响应异常"
    return True, u"保存成功"


def search_poi(keyword, key=None, count=10, admin_code=None):
    """地名搜索 V2；返回 dict 或 None"""
    if key is None:
        key = get_key()
    data = {
        "keyWord": _to_unicode(keyword),
        "mapBound": u"-180,-90,180,90",
        "level": 18,
        "queryType": 1,
        "start": 0,
        "count": count,
        "show": 1,
    }
    if admin_code:
        data["specify"] = admin_code
    # API 期望 postStr 为 JSON 文本
    payload = {
        "postStr": json.dumps(data, ensure_ascii=False),
        "type": "query",
        "tk": _to_unicode(key),
    }
    return http_get_json(u"https://api.tianditu.gov.cn/v2/search", payload)


def geocode(address, key=None):
    """地理编码：地址 → 坐标"""
    if key is None:
        key = get_key()
    ds = json.dumps({"keyWord": _to_unicode(address)}, ensure_ascii=False)
    payload = {"ds": ds, "tk": _to_unicode(key)}
    return http_get_json(u"https://api.tianditu.gov.cn/geocoder", payload)


def regeocode(lon, lat, key=None):
    """逆地理编码：坐标 → 地址"""
    if key is None:
        key = get_key()
    post = json.dumps(
        {"lon": float(lon), "lat": float(lat), "ver": 1},
        ensure_ascii=False,
    )
    payload = {
        "postStr": post,
        "type": "geocode",
        "tk": _to_unicode(key),
    }
    return http_get_json(u"https://api.tianditu.gov.cn/geocoder", payload)


def load_map_json(filename):
    import io
    import os

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), u"maps")
    path = os.path.join(base, filename)
    if not os.path.isfile(path):
        return {}
    with io.open(path, "r", encoding="utf-8") as f:
        return json.load(f)
