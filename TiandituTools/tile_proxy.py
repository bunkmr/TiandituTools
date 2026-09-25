# -*- coding: utf-8 -*-
"""本机 WMTS 中转服务 —— 让 ArcMap 能把天地图底图**真正画出来**。

为什么非它不可（两条硬约束，实测）
==================================

天地图对瓦片请求有两条硬性校验，两条都过不了，画布就是一片空白：

1. **URL 里必须有 tk**
   缺 tk 直接 **HTTP 418**（CloudWAF「访问被拦截！」）。
   —— 但天地图的 GetCapabilities 里 GetTile 端点写的是
      `<ows:Get xlink:href="http://t0.tianditu.gov.cn/img_w/wmts?">`，
      **没有 tk**；文档里也没有 `<ResourceURL>` 瓦片模板。
      ArcMap 只能拿这个 href 自己拼 GetTile，于是拼出来的 URL 不带 tk
      -> 418 -> 画不出来。这是「图层在面板里、画布空白」的**第一病因**。

2. **请求头里必须有非空 User-Agent**
   带 tk 但没有 UA（或 UA 为空）时返回 **HTTP 403**：
   `{"code":301012,"msg":"权限类型错误","resolve":"Key权限类型为:浏览器端，请使用浏览器访问！"}`
   ArcMap 自己的 HTTP 栈不保证发 UA，这一条我们**在 ArcMap 里改不了**
   —— 只能在中间加一层，由我们代发请求。

结论：必须在 127.0.0.1 起一个极小的中转服务，它的职责只有两件事：

  * 把 GetCapabilities 的 XML 里所有指向 `t?.tianditu.gov.cn` 的
    `xlink:href` **改写到本机**，并补上 `tk=KEY`；
  * 收到瓦片请求时代发一次，**带上 UA 和 tk**，把字节原样回给 ArcMap。

这样 ArcMap 眼里只是一个普通 WMTS 服务，实际由我们补齐了它补不上的两样东西。


六、能力文档必须取 `/esri/wmts` 那一份（第三病因，也是最隐蔽的一条）
====================================================================

天地图为 ArcGIS **单独开了一个端点**：

    http://t0.tianditu.gov.cn/img_w/esri/wmts     <- ArcMap 必须用这个
    http://t0.tianditu.gov.cn/img_w/wmts          <- 通用 WMTS，ArcMap 用它会全白

两份 capabilities 的差别，正好是「图层在面板里、画布全白」的根因：

  * **TopLeftCorner 的 X/Y 顺序相反**

        /wmts       -> 20037508.3427892 -20037508.3427892   （标着「左上角」，
                                                             给的其实是右下角）
        /esri/wmts  -> -20037508.3427892 20037508.3427892   （正确的左上角）

    ArcMap 是拿 TopLeftCorner 反算瓦片行列号的。X/Y 一反，行列号全算错，
    要到的瓦片自然对不上（网上那句「vec_w 看到的是西半球」就是这个现象）。

  * **ScaleDenominator 是否跟 ArcGIS 自己的 Web Mercator 分级对齐**

        /wmts       第 1 级 = 2.958293554545656E8   （天地图自己的分级）
        /esri/wmts  第 1 级 = 2.795411320143237E8
                     = 559082264.0287178 / 2 = ArcGIS 第 1 级，逐级都对得上

  另外还有一个坑：`/esri/wmts` **只服务 GetCapabilities**。拿同一个路径去要
  瓦片，它会把 capabilities 文档原样再吐一遍（实测 11619 字节 = caps 大小，
  且与内容无关、永远是同一份）。瓦片只能走普通 `/wmts` —— capabilities 里的
  GetTile href 也正是指向普通 `/wmts`，天地图本来就是这么分工的。

  所以本模块取 capabilities 时**必须**走 `/esri/wmts`，而改写 href 时
  **必须**把 `/esri/` 去掉（见 rewrite_capabilities / capabilities_url）。

这个发现同时解释了「网上说 ArcMap 10.4 加天地图 WMTS 全白、10.5 以后才好使」：
不是版本差异，是地址区别。


七、上游必须用 IP 直连（第四病因，也是「能放大」的最后一关）
==========================================================

前面三条解决的是「画不出来」。画出来之后，用户看到的是**能加载、不能放大**：
初始全球视图那几张瓦片能出来，一放大就卡死。

日志给出了病因：同样的瓦片请求

    直连天地图        110 ms
    经本机中转        124656 ms / 127155 ms / 132164 ms

中转本身并不慢（用 keep-alive 单连接连打 12 张，平均 97 ms）。慢的是
**DNS**：Python 2 的 socket 超时管不到 `getaddrinfo`，它是系统解析，阻塞
多久都算数；这台机器上常驻 dev-sidecar，会插一脚 DNS。一旦解析卡住，
单次代发就能耗掉两分钟。

ArcMap 是**同步绘制**：放大一次要几十上百张瓦片，每张都卡两分钟，
画布永远刷不出来，主线程跟着假死 —— 看起来就是"放大不了"。

所以本模块启动时解析一次全部上游主机，缓存在 `_DNS_CACHE`，之后用
**IP + Host 头** 直连（_resolve / _fetch）。热路径上不再出现域名。

另外两处配套加固：

  * **端口独占**：Windows 的 SO_REUSEADDR 语义与 Unix 相反，允许第二个
    进程绑到别人正在 LISTENING 的端口上，于是"端口被占用"不会报错，
    同一端口上会挂两个实例抢连接（日志里 10592 与 24708 同时监听 17817）。
    已改为禁 SO_REUSEADDR + SO_EXCLUSIVEADDRUSE，独占绑定。
  * **半死实例清理**：端口文件里记着的进程还活着但 /ping 不应答时，
    直接 taskkill 掉再重建（只杀 python 系进程，避免误杀回收的 PID）。


架构约束（与 layer_manager 一致）
--------------------------------
* 纯标准库（BaseHTTPServer / httplib / socket / re），**不 import arcpy、
  不 import Tkinter**；
* 跑在 **独立进程** 里（tile_server.py），不在 ArcMap 进程内起服务器线程：
  进程内起过，画几张瓦片后 accept 循环就停了，ArcMap 卡死在 SYN_SENT；
* 端口固定（17817 起顺延），**独占绑定**（禁 SO_REUSEADDR +
  SO_EXCLUSIVEADDRUSE），不给"两个实例抢同一个端口"留机会；
* 上游主机名**只解析一次**（_resolve），之后一律 IP + Host 头直连，
  热路径上不再有 getaddrinfo —— 它不受 socket 超时约束，抽风时能阻塞
  一百多秒，是「能加载、不能放大」的最后一个病因；
* 每线程一条到上游的 keep-alive 连接，省掉每张瓦片的 TCP 握手；
* 全部异常在 Handler 内部吞掉并记日志，绝不往上报。
"""

from __future__ import print_function

import httplib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

try:
    import ssl
except ImportError:                     # 理论上不会（2.7.9+ 都有）
    ssl = None

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn

#: XYZ 图源（自定义 {z}/{x}/{y} 瓦片源）。放在本进程里被引用是**有意的**：
#: 中转进程是唯一真正去取瓦片的地方，翻译必须在这里做（见 _handle 里
#: 的 XYZ 分支，以及 xyz_sources 顶部那段"为什么不是给 ArcMap 加 XYZ 图层"）。
try:
    import xyz_sources
except Exception:                       # 缺文件时不能让整个中转起不来
    xyz_sources = None

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 天地图接入子域（t0~t7 内容一样，任一都行）
_DEFAULT_HOST = "t0.tianditu.gov.cn"

#: 上游协议（实测 http / https 都能通）
_SCHEME = "http"

#: 上游端口
_PORT = 80

#: 必须带的请求头 —— 天地图拿这个判定「是不是浏览器端 Key」
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TiandituTools/0.7"
_REFERER = "https://www.tianditu.gov.cn/"

#: xlink:href 里指向天地图接入子域的地址
_HOST_RE = re.compile(r"https?://t(\d)\.tianditu\.gov\.cn", re.IGNORECASE)

#: 只改 XML 里的 xlink:href（不碰其它文本，避免误伤）
_HREF_RE = re.compile(r'xlink:href\s*=\s*"([^"]*)"', re.IGNORECASE)

#: ArcGIS 专用路径段。天地图为 ArcGIS 单开了一个端点 `/xxx_w/esri/wmts`，
#: 它的 capabilities 才是 ArcMap 能对得上的那份（TopLeftCorner 顺序正确、
#: ScaleDenominator 与 ArcGIS 自己的 Web Mercator 分级逐级对齐）。
#: 普通 `/xxx_w/wmts` 的 capabilities 会让 ArcMap 全白 —— 这曾经是最大的一口坑。
#: 但注意 `/esri/wmts` **只服务 GetCapabilities**：拿它要瓦片只会拿回 caps 文档，
#: 所以瓦片地址里的 `/esri/` 必须去掉。详见 capabilities_url / rewrite_capabilities。
_ESRI_SEG = u"esri/"

#: 超时
_TIMEOUT = 30

_LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "TiandituTools")

# ---------------------------------------------------------------------------
# 运行状态
# ---------------------------------------------------------------------------

#: 单例状态；由 start() 填
_state = {
    "server": None,     # HTTPServer
    "thread": None,     # Thread
    "port": 0,
    "key": u"",
    "upstream": _DEFAULT_HOST,
    "send_ua": True,    # 代发时是否补 UA（留开关方便定位问题）
    "hits": 0,          # 瓦片命中数
    "caps_hits": 0,
    "errors": 0,
    "caps_cache": {},   # 原始 caps 文本 -> 渲染后的 unicode
    "tile_cache": {},   # 规整后的查询串 -> (ctype, bytes)
    "tile_order": [],   # 配合 tile_cache 做 FIFO 淘汰
    "cache_hits": 0,    # 命中内存缓存的次数
    "last_ms": 0,
    "last_detail": u"",  # 最近一次代发的细节（IP / 第几次尝试 / 错误）
    "fail_streak": 0,   # 连续失败次数（到 5 就清 DNS 缓存重解析）
    "total_ms": 0,
    "xyz_tiles": 0,     # XYZ 图源瓦片命中数
    "xyz_caps": 0,      # XYZ 图源 capabilities 次数
}

#: 瓦片缓存上限（张）。一张约 10~30 KB，2000 张 ≈ 40 MB，够一次会话用。
_TILE_CACHE_MAX = 2000

_lock = threading.Lock()


def log(text):
    try:
        if not os.path.isdir(_LOG_DIR):
            os.makedirs(_LOG_DIR)
        with open(os.path.join(_LOG_DIR, "tile_proxy.log"), "ab") as f:
            f.write((u"%s %s\n" % (time.strftime("%H:%M:%S"), text))
                    .encode("utf-8", "ignore"))
    except Exception:
        pass


def stats():
    """给界面/日志看的运行统计"""
    return {"port": _state["port"],
            "tiles": _state["hits"],
            "caps": _state["caps_hits"],
            "xyz_tiles": _state["xyz_tiles"],
            "xyz_caps": _state["xyz_caps"],
            "errors": _state["errors"],
            "cached": _state["cache_hits"],
            "cache_size": len(_state["tile_cache"]),
            "avg_ms": int(_state["total_ms"] / _state["hits"]) if _state["hits"] else 0,
            "last_ms": _state["last_ms"],
            "last_detail": _state["last_detail"],
            "dns": dict(_DNS_CACHE),
            "running": _state["server"] is not None}


def external_stats(p=None, timeout=2.0):
    """问**独立中转进程**要统计，返回 dict（取不到返回 {}）。

    为什么需要它：正式路径下中转跑在别的进程里，ArcMap 进程内的 `_state`
    永远是空的（port=0 / tiles=0）。自检日志以前老显示 `tiles=0`，
    就是这个原因 —— 数字本身没错，只是问错了对象。
    """
    p = p or _ext_port or read_port_file()[0]
    if not p:
        return {}
    try:
        st, body = _local_get(p, "/stats", timeout=timeout)
        if st == 200:
            return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        pass
    return {}


def live_stats():
    """真实运行统计：优先独立中转的，取不到才退回进程内。"""
    d = external_stats()
    return d if d else stats()


def _cache_put(key, val):
    """放一张瓦片进内存缓存（FIFO 淘汰），带锁防并发写坏 list。"""
    with _lock:
        cache = _state["tile_cache"]
        order = _state["tile_order"]
        if key not in cache:
            order.append(key)
        cache[key] = val
        while len(order) > _TILE_CACHE_MAX:
            old = order.pop(0)
            cache.pop(old, None)


def port():
    """当前应当使用的端口：优先独立中转进程的端口。"""
    return _ext_port or _state["port"]


# ---------------------------------------------------------------------------
# 独立进程模式（正式路径）
# ---------------------------------------------------------------------------

#: 独立中转进程的端口（0 = 还没起）
_ext_port = 0

#: 本会话内是否已经确认过（避免每次都去 ping）
_ext_ok = False

#: 端口文件：由 tile_server.py 写，内容是 "<port> <pid>"
_PORT_FILE = os.path.join(_LOG_DIR, "tile_proxy.port")

#: 候选解释器（优先用当前进程的解释器，其次 ArcGIS 各版本）
_PY_CANDIDATES = [
    "pythonw.exe", "python.exe",
    r"C:\Python27\ArcGIS10.4\pythonw.exe",
    r"C:\Python27\ArcGIS10.4\python.exe",
    r"C:\Python27\ArcGIS10.3\pythonw.exe",
    r"C:\Python27\ArcGIS10.2\pythonw.exe",
    r"C:\Python27\ArcGIS10.1\pythonw.exe",
    r"C:\Python27\pythonw.exe",
    r"C:\Python27\python.exe",
]

_CREATE_NO_WINDOW = 0x08000000


def read_port_file():
    """读端口文件，返回 (port, pid)；没有/坏了返回 (0, 0)"""
    try:
        with open(_PORT_FILE) as f:
            parts = f.read().split()
        port = int(parts[0])
        pid = int(parts[1]) if len(parts) > 1 else 0
        return port, pid
    except Exception:
        return 0, 0


def _local_get(p, path, timeout=1.5):
    """向本机中转发一个极简 GET。用 httplib 而不是 urllib2 ——
    httplib **永远不走代理**，而 urllib2 会读系统/环境代理设置，
    127.0.0.1 也可能被拐去代理，探测就假阴性了。"""
    c = None
    try:
        c = httplib.HTTPConnection("127.0.0.1", p, timeout=timeout)
        c.request("GET", path, headers={"Host": "127.0.0.1",
                                       "Connection": "close"})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


def ping(p=None, timeout=1.5):
    """探测端口上是不是我们的中转服务（活的、能应答）"""
    p = p or _ext_port or read_port_file()[0]
    if not p:
        return False
    try:
        st, body = _local_get(p, "/ping", timeout)
        return st == 200 and body.strip() == b"OK"
    except Exception:
        return False


def _find_pythonw():
    try:
        exe = getattr(sys, "executable", "") or ""
        if exe:
            d = os.path.dirname(exe)
            for name in ("pythonw.exe", "python.exe"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    return p
    except Exception:
        pass
    for p in _PY_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _pid_looks_like_python(pid):
    """这个 PID 现在活着吗？而且确实是 Python 系进程吗？

    加"是不是 python"这道判断，是为了**避免误杀**：端口文件里的 pid
    理论上可能已经被系统回收给别的程序了，那种情况绝不能 taskkill。
    """
    if not pid:
        return False
    try:
        p = subprocess.Popen(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             creationflags=_CREATE_NO_WINDOW)
        out = p.communicate()[0] or b""
        if isinstance(out, bytes):
            out = out.decode("mbcs", "ignore")
        return "python" in out.lower()
    except Exception:
        return False


def _kill_pid(pid):
    """杀掉我们自己记录的、已经不应答的中转进程（只杀 python 系）。"""
    try:
        subprocess.Popen(["taskkill", "/F", "/PID", str(pid)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=_CREATE_NO_WINDOW).communicate()
        log(u"已清理不应答的中转进程 pid=%s" % pid)
    except Exception as e:
        log(u"清理 pid=%s 失败 %r" % (pid, e))


def ensure_external(start_port=17817, wait=8.0):
    """确保有一个**独立进程**的中转在跑；返回端口，失败返回 0。

    为什么不复用进程内线程：实测进程内服务器会在画了几张瓦片之后停止 accept，
    ArcMap 的请求卡在 SYN_SENT，主线程假死（详见 tile_server.py 顶部说明）。
    """
    global _ext_port, _ext_ok
    if _ext_ok and _ext_port and ping(_ext_port):
        return _ext_port

    p, pid = read_port_file()
    if p and ping(p):
        _ext_port = p
        _ext_ok = True
        return p

    # 端口文件里记着一个**还活着但不应答**的实例 —— 典型的"半死"状态：
    # socket 还在，服务循环已经不干活了。这种实例最坑：新连接会被
    # 路由到它，然后永远等不到应答。直接清掉，让新实例能干净地重绑 17817。
    if pid and _pid_looks_like_python(pid):
        log(u"端口 %s 上的中转实例 pid=%s 不应答，判定为半死，清掉重建" % (p, pid))
        _kill_pid(pid)
        time.sleep(0.6)

    exe = _find_pythonw()
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tile_server.py")
    if not exe or not os.path.isfile(script):
        log(u"独立中转无法启动：exe=%r script=%s" % (exe, os.path.isfile(script)))
        return 0

    try:
        # 必须把三个标准句柄都指向 devnull 再起：
        # 否则子进程会继承调用方的管道/控制台句柄 —— 父进程（ArcMap）退出后
        # 句柄还挂在服务器进程上，会连带出一堆麻烦（脚本里表现为命令不返回）。
        dn = open(os.devnull, "rb")
        do = open(os.devnull, "wb")
        subprocess.Popen([exe, script, str(start_port)],
                         cwd=os.path.dirname(script),
                         stdin=dn, stdout=do, stderr=do,
                         creationflags=_CREATE_NO_WINDOW | 0x00000008)  # DETACHED
    except Exception as e:
        log(u"独立中转进程启动失败：%r" % (e,))
        return 0

    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.3)
        p2, pid2 = read_port_file()
        if p2 and ping(p2):
            _ext_port = p2
            _ext_ok = True
            log(u"=== 独立中转已就绪 127.0.0.1:%d pid=%s" % (p2, pid2))
            return p2
    log(u"独立中转启动超时（%.1fs）" % wait)
    return 0


def capabilities_url(maptype, key=None, host_port=None):
    """本机服务的 GetCapabilities 地址（可直接交给 ArcMap 的 WMTS 连接）。

    路径里带 `/esri/wmts` —— 这是天地图给 ArcGIS 的专用端点，**不能省**。
    省了（用普通 `/wmts`）ArcMap 也能连上、也取得到 capabilities，
    但那份 capabilities 的 TopLeftCorner 是 X/Y 反的、分级也没跟 ArcGIS 对齐，
    于是 ArcMap 算出来的瓦片行列全错，表现就是「图层在、画布全白」。
    详见 tile_proxy 顶部「六」。
    """
    p = host_port or port()
    k = key if key is not None else _state["key"]
    u = (u"http://127.0.0.1:%d/%s_w/%swmts"
         u"?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
         % (p, maptype, _ESRI_SEG))
    if k:
        u += u"&tk=%s" % k
    return u


# ---------------------------------------------------------------------------
# capabilities 改写
# ---------------------------------------------------------------------------

def rewrite_capabilities(xml, self_base, key):
    """把 XML 里所有指向天地图接入子域的 xlink:href 改成走本机，并补 tk。

    两种写法都覆盖：
        http://t0.tianditu.gov.cn/img_w/wmts?      -> 本机 + tk
        http://t0.tianditu.gov.cn/vec_w/wmts?      -> 本机 + tk
    子域编号保留成路径前缀（/t0/...），代发时再还原成真实主机，
    这样多个服务子域混用时也不会串。

    `self_base` 形如 ``http://127.0.0.1:51234``。
    """
    if not xml:
        return xml
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8", "replace")

    def fix(match):
        url = match.group(1)
        if not _HOST_RE.search(url):
            return match.group(0)                      # 非接入子域地址，原样保留
        url = _HOST_RE.sub(lambda m: u"%s/t%s" % (self_base, m.group(1)), url)
        # capabilities 是用 /esri/wmts 取的，里面的 GetTile href 却是普通 /wmts
        # （天地图就是这么写的）。万一它哪天改成带 /esri 的，这里兜一下：
        # /esri/ 端点的 GetTile 只会把 capabilities 文档再吐一遍，必须去掉。
        if u"/esri/" in url:
            url = url.replace(u"/esri/", u"/")
        if key and "tk=" not in url:
            sep = u"" if url.endswith(u"?") or url.endswith(u"&") else (
                u"&" if u"?" in url else u"?")
            url += sep + u"tk=%s" % key
        # 注意：**不要**在结尾补 `&`。ArcMap 拼 GetTile 时确实不加分隔符，
        # 但实测 href 以 `?tk=KEY&` 结尾时，`IWMTSLayer.Connect` 会直接
        # E_FAIL（COMError -2147467259）—— 连服务都连不上了。
        # 粘连问题改由 _normalize_tile_query 在转发前修掉，两全。
        return u'xlink:href="%s"' % url

    return _HREF_RE.sub(fix, xml)


# ---------------------------------------------------------------------------
# 上游取数
# ---------------------------------------------------------------------------

def _split_host(path):
    """把 /t0/img_w/wmts 拆成 ('t0.tianditu.gov.cn', '/img_w/wmts')"""
    if path.startswith("/t") and len(path) > 2 and path[2].isdigit():
        rest = path[3:]
        if not rest.startswith("/"):
            rest = "/" + rest
        return u"t%s.%s" % (path[2], _DEFAULT_HOST.split(".", 1)[1]), rest
    return _state["upstream"], path


# ---------------------------------------------------------------------------
# 关键：DNS 只解析一次，之后一律用 IP 直连
# ---------------------------------------------------------------------------
#
# 为什么必须这么做（这是「能加载、不能放大」的最后一个病因）
# --------------------------------------------------------
# 原先每次代发都走 `urllib2` + 域名。Python 2 的 socket 超时**管不到 DNS**：
# `socket.create_connection` 里的 `getaddrinfo` 是系统解析，阻塞多久都算数。
# 解析器一旦抽风（这台机器上常驻 dev-sidecar，会动 DNS），
# 一次 `getaddrinfo` 能阻塞一百多秒 —— 日志里那些
#
#     [tile] ... -> image/jpg 8329 字节 124656 ms
#
# 就是这么来的（同样的请求直连只要 110 ms）。ArcMap 是**同步绘制**：
# 它一次要几十张瓦片，每张都卡一百多秒，画布自然永远刷不出来。
#
# 所以：进程启动时解析一次，结果缓存在 `_DNS_CACHE`，之后所有请求都用
# **IP + Host 头** 直连。热路径上不再有任何 DNS 调用。
# 解析失败才退回域名（并记日志，事后可查）。

_DNS_CACHE = {}
_DNS_LOCK = threading.Lock()


def _resolve(host):
    """把主机名解析成 IP，只做一次。失败返回原主机名（退回老路）。"""
    ip = _DNS_CACHE.get(host)
    if ip:
        return ip
    with _DNS_LOCK:
        ip = _DNS_CACHE.get(host)          # 双检：可能别的线程刚填过
        if ip:
            return ip
        try:
            t0 = time.time()
            ip = socket.gethostbyname(host)
            log(u"[dns] %s -> %s  (%d ms)" % (host, ip,
                                              int((time.time() - t0) * 1000)))
        except Exception as e:
            log(u"[dns] %s 解析失败 %r —— 退回按域名直连" % (host, e))
            ip = host
        _DNS_CACHE[host] = ip
        return ip


#: 每线程一条到上游的 keep-alive 连接（避免每张瓦片都重做 TCP 握手）
_tls = threading.local()


def _thread_conns():
    d = getattr(_tls, "conns", None)
    if d is None:
        d = {}
        _tls.conns = d
    return d


def _drop_conn(key):
    d = _thread_conns()
    c = d.pop(key, None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def _fetch(path, query, send_ua=None):
    """代发一次请求。返回 (ctype, body)；失败抛异常。

    走 IP + keep-alive。失败就丢连接重试一次（网络偶尔抽风的场景）。
    """
    host, p = _split_host(path)
    qs = query or u""
    if _state["key"] and u"tk=" not in qs:
        qs += (u"&" if qs else u"") + u"tk=%s" % _state["key"]
    target = p if not qs else (u"%s?%s" % (p, qs))

    headers = {"Host": host,
               "Referer": _REFERER,
               "Accept": "*/*",
               "Connection": "keep-alive"}
    if (_state["send_ua"] if send_ua is None else send_ua):
        headers["User-Agent"] = _USER_AGENT

    ip = _resolve(host)
    key = (ip, host)
    last_err = None

    for attempt in (0, 1):
        t0 = time.time()
        try:
            d = _thread_conns()
            c = d.get(key)
            if c is None:
                c = httplib.HTTPConnection(ip, _PORT, timeout=_TIMEOUT)
                d[key] = c
            c.request("GET", target.encode("utf-8"), headers=headers)
            r = c.getresponse()
            body = r.read()
            _state["last_ms"] = int((time.time() - t0) * 1000)
            _state["total_ms"] = _state.get("total_ms", 0) + _state["last_ms"]
            _state["last_detail"] = (u"ip=%s try=%d" % (ip, attempt))
            if r.status >= 400:
                raise RuntimeError(u"HTTP %d %s" % (r.status, r.reason))
            # 空 body 基本只有一个来源：keep-alive 连接被上游悄悄关了，
            # 复用它拿到的其实是个"假 200"。这不算成功，重来一次。
            if not body and attempt == 0:
                raise RuntimeError(u"空响应（疑似 keep-alive 连接已失效）")
            _state["fail_streak"] = 0
            return (r.getheader("Content-Type") or "application/octet-stream",
                    body)
        except Exception as e:
            last_err = e
            _state["last_ms"] = int((time.time() - t0) * 1000)
            _state["last_detail"] = (u"ip=%s try=%d 失败 %r" % (ip, attempt, e))
            # 连接可能已经脏了（keep-alive 复用踩坑的经典症状），直接丢掉
            _drop_conn(key)
            _state["fail_streak"] = _state.get("fail_streak", 0) + 1
            if attempt == 0:
                continue
    # 一连串都失败，很可能是缓存的 IP 已经失效（CDN 换机）。
    # 把 DNS 缓存清掉，下一次请求重新解析 —— 总比一直撞一个死 IP 好。
    if _state.get("fail_streak", 0) >= 5:
        log(u"[dns] 连续 %d 次失败，清空缓存下次重解析" % _state["fail_streak"])
        _DNS_CACHE.clear()
        _state["fail_streak"] = 0
    raise last_err


# ---------------------------------------------------------------------------
# XYZ 图源通道：把 ArcMap 发来的 WMTS 请求翻译回 XYZ 去取瓦片
# ---------------------------------------------------------------------------
#
# 为什么不给 ArcMap 造一个"XYZ 图层"：它根本没有这个类型（详见
# xyz_sources 顶部）。可行的办法是把 XYZ 模板**翻译成一份 WMTS
# capabilities**，ArcMap 照常按 WMTS 请求，这里再翻回去。
#
# 与天地图那条路的区别：天地图是"取上游的 capabilities 再改写 href"，
# XYZ 是"capabilities 由我们凭空合成"（格网参数见 xyz_sources）。所以
# 这一支**完全不访问上游**，只做本地计算 —— 快，且不受网络影响。

#: /xyz/<sid>/wmts  或  /xyz/<sid>/esri/wmts
#: 路径末段不写死：ArcMap 做 REST 探测时会往后硬接
#: `/1.0.0/WMTSCapabilities.xml`（实测天地图那条路上就这么干过），
#: 所以只认前缀，靠 _is_caps 判断到底要 capabilities 还是瓦片。
_XYZ_PATH_RE = re.compile(u"^/xyz/([A-Za-z0-9_\\-]+)(?:/.*)?$", re.IGNORECASE)

#: 从查询串里抠 KVP。**第一次出现的优先**：ArcMap 把它的参数粘到
#: href 后面时会产生重复键（`?a=1&b=2a=1&b=2` 这种脏串），
#: 先出现的才是它真正要的值。
_KVP_RE = re.compile(u"([A-Za-z0-9_]+)=([^&]*)")


def xyz_entry_from_path(path):
    """路径 -> XYZ 源 id；不是 XYZ 路径返回 None"""
    if xyz_sources is None or not path:
        return None
    m = _XYZ_PATH_RE.match(path)
    return m.group(1) if m else None


def kvp(query):
    d = {}
    for k, v in _KVP_RE.findall(query or u""):
        d.setdefault(k.lower(), v)
    return d


def _int_param(p, name):
    """取数值参数，**容忍粘在值后面的垃圾**。

    ArcMap 把它的 KVP 不带分隔符地粘到 href 末尾，于是最后一个参数的
    值会变成 `421SERVICE=WMTS` 这种。直接 int() 会失败，一旦失败就会
    退化成 0 —— 表现为"整片画布全白但没有任何报错"，很难查。
    所以这里只取前导整数部分。
    """
    v = p.get(name)
    if v is None:
        return None
    m = re.match(r"\s*(-?\d+)", v)
    return int(m.group(1)) if m else None


class _HTTPSConn(httplib.HTTPSConnection):
    """HTTPS 连 IP、但 TLS 的 SNI 用真实域名。

    Python 2.7.9+ 的 `HTTPSConnection.connect()` 拿 `self.host` 当
    `server_hostname`。我们为了绕开 DNS（见 _resolve 那段）连的是 IP，
    直接用它做 SNI 就成了"向 CDN 出示一个 IP 的证书域名"，很多站点会拒。
    所以自己接管 connect：TCP 连 IP，TLS 报真实域名。
    """

    def __init__(self, ip, port, sni, timeout, context):
        httplib.HTTPSConnection.__init__(self, ip, port, timeout=timeout,
                                         context=context)
        self._sni = sni

    def connect(self):
        httplib.HTTPConnection.connect(self)      # 内含 CONNECT 隧道（用代理时）
        self.sock = self._context.wrap_socket(self.sock,
                                              server_hostname=self._sni)


_ssl_ctx_singleton = [None]


def _ssl_context():
    """不校验证书的 SSLContext。

    我们是瓦片中转，不是安全通道：**校验证书只有坏处没有好处** ——
    国内不少图源用的是自签/域名不匹配的证书，校验只会多出一堆失败；
    而被中间人换掉一张公开底图瓦片，也不构成安全事件。
    """
    if _ssl_ctx_singleton[0] is not None:
        return _ssl_ctx_singleton[0]
    ctx = None
    if ssl is not None:
        try:
            ctx = ssl.create_default_context()
            # 顺序不能反：check_hostname 为 True 时不允许设 CERT_NONE
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        except Exception:
            try:
                ctx = ssl._create_unverified_context()
            except Exception:
                ctx = None
    _ssl_ctx_singleton[0] = ctx
    return ctx


def _split_abs(url):
    """绝对 URL -> (scheme, host, port, path, query)"""
    u = url if isinstance(url, unicode) else url.decode("utf-8", "replace")  # noqa: F821
    m = re.match(r"(?i)^(https?)://([^/:?#]+)(?::(\d+))?([^?#]*)(?:\?(.*))?$", u)
    if not m:
        raise ValueError(u"不是合法的绝对 URL: %s" % u)
    scheme = m.group(1).lower()
    host = m.group(2)
    port = int(m.group(3)) if m.group(3) else (443 if scheme == "https" else 80)
    path = m.group(4) or u"/"
    return scheme, host, port, path, (m.group(5) or u"")


def _parse_hostport(raw):
    """'http://127.0.0.1:56991' / '127.0.0.1:56991' -> ('127.0.0.1', 56991)"""
    s = (raw or u"").strip()
    if not s:
        return None
    m = re.match(r"(?i)^(?:https?://)?([^/:]+):(\d+)/?$", s)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _ie_proxy():
    """读 IE/系统代理设置（dev-sidecar 这类工具往往只写注册表）。

    只在 "auto" 模式下用；读不到就返回 None，当没配。
    """
    try:
        import _winreg
    except ImportError:
        return None
    try:
        k = _winreg.OpenKey(
            _winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enabled = _winreg.QueryValueEx(k, "ProxyEnable")[0]
        finally:
            _winreg.CloseKey(k)
        if not enabled:
            return None
        val = _winreg.QueryValueEx(k, "ProxyServer")[0]
        if not val:
            return None
        # 可能是 "host:port" 或 "http=host:port;https=host:port"
        for part in str(val).split(";"):
            if "=" in part:
                scheme, _, hp = part.partition("=")
                if scheme.strip().lower() in ("http", "https"):
                    got = _parse_hostport(hp)
                    if got:
                        return got
            else:
                got = _parse_hostport(part)
                if got:
                    return got
    except Exception:
        return None
    return None


def _xyz_config():
    """中转进程自己读 config.json（不依赖 ArcMap 传参）。

    带 5 秒 TTL：用户在设置里改完代理，几乎立刻生效，又不必每张瓦片
    都去读一次文件（一次放大可能几百张瓦片）。
    """
    now = time.time()
    if now - _xyz_config.cache[0] < 5.0:
        return _xyz_config.cache[1]
    data = {}
    try:
        with open(os.path.join(_LOG_DIR, "config.json")) as f:
            data = json.loads(f.read())
    except Exception:
        data = {}
    _xyz_config.cache = (now, data)
    return data


_xyz_config.cache = (0.0, {})


def proxy_for(entry):
    """这条 XYZ 源要不要走代理？返回 (host, port) 或 None。

    三态：条目 `proxy` 显式为 True/False 时优先；否则看全局 `xyzProxy`。
    默认全局为空 = 直连 —— 天地图/高德/Esri 这些本来就不该绕代理，
    绕了反而变慢甚至失败（这台机器上系统代理曾让本机中转慢到 124 秒）。
    """
    flag = (entry or {}).get("proxy")
    if flag is False:
        return None
    raw = _state.get("xyz_proxy") or u""
    if not raw:
        raw = _xyz_config().get("xyzProxy") or u""
    if flag is not True and not raw:
        return None
    if raw.lower() in (u"auto", u"env"):
        for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            got = _parse_hostport(os.environ.get(k) or u"")
            if got:
                return got
        return _ie_proxy()
    return _parse_hostport(raw)


def _fetch_abs(url, referer=u"", extra=None, proxy=None, timeout=None):
    """取一个**绝对 URL**（XYZ 上游）。返回 (ctype, body)。

    与 _fetch 同源：DNS 只解析一次、IP + Host 直连、每线程 keep-alive、
    失败丢连接重试一次。多出来的两件事：https、以及可选的 HTTP 代理。
    """
    scheme, host, port, path, query = _split_abs(url)
    headers = {"Host": host if port in (80, 443) else u"%s:%d" % (host, port),
               "Accept": "*/*",
               "Accept-Encoding": "identity",
               "Connection": "keep-alive",
               "User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    for k, v in (extra or {}).items():
        headers[str(k)] = _u2(v)
    to = timeout or _TIMEOUT

    last_err = None
    for attempt in (0, 1):
        t0 = time.time()
        c = None
        ckey = None
        try:
            d = _thread_conns()
            if proxy:
                phost, pport = proxy
                ckey = (u"proxy", phost, pport, scheme, host, port)
                c = d.get(ckey)
                if c is None:
                    if scheme == "https":
                        c = _HTTPSConn(phost, pport, host, to, _ssl_context())
                        c.set_tunnel(host, port)
                    else:
                        c = httplib.HTTPConnection(phost, pport, timeout=to)
                    d[ckey] = c
                # 走代理时 HTTP 要用绝对 URI；HTTPS 由 CONNECT 隧道带过去，
                # 隧道里仍然是普通 origin-form 路径。
                if scheme == "https":
                    target = path + (u"?" + query if query else u"")
                else:
                    target = u"%s://%s%s%s" % (scheme, headers["Host"], path,
                                               (u"?" + query if query else u""))
            else:
                ip = _resolve(host)
                ckey = (scheme, ip, port, host)
                c = d.get(ckey)
                if c is None:
                    if scheme == "https":
                        c = _HTTPSConn(ip, port, host, to, _ssl_context())
                    else:
                        c = httplib.HTTPConnection(ip, port, timeout=to)
                    d[ckey] = c
                target = path + (u"?" + query if query else u"")

            c.request("GET", target.encode("utf-8", "ignore"), headers=headers)
            r = c.getresponse()
            body = r.read()
            _state["last_ms"] = int((time.time() - t0) * 1000)
            _state["last_detail"] = u"xyz %s://%s try=%d%s" % (
                scheme, host, attempt, u" via代理" if proxy else u"")
            if r.status >= 400:
                raise RuntimeError(u"HTTP %d %s" % (r.status, r.reason))
            if not body and attempt == 0:
                raise RuntimeError(u"空响应（疑似 keep-alive 连接已失效）")
            _state["fail_streak"] = 0
            return (r.getheader("Content-Type") or "application/octet-stream",
                    body)
        except Exception as e:
            last_err = e
            if ckey:
                _drop_conn(ckey)               # 连接可能已经脏了
            _state["fail_streak"] = _state.get("fail_streak", 0) + 1
            if attempt == 0:
                continue
    raise last_err


def _u2(v):
    if isinstance(v, bytes):
        return v
    if isinstance(v, unicode):                  # noqa: F821
        return v.encode("utf-8")
    return str(v)


def handle_xyz(path, query, send):
    """处理一条 XYZ 路径的请求。`send(body, ctype, code=200)` 由调用方给。

    返回 True 表示已处理（无论成功失败），不再往下走天地图那条路。
    """
    sid = xyz_entry_from_path(path)
    if not sid:
        return False
    entry = xyz_sources.find(sid)
    if entry is None:
        entry = xyz_sources.find(sid, reload=True)   # 用户刚加的源，刷新一次
    if entry is None:
        _state["errors"] += 1
        log(u"[xyz] 未知图源 id=%s  %s" % (sid, path))
        send(u"<error>unknown xyz source: %s</error>" % sid,
             "text/xml; charset=UTF-8", 404)
        return True

    if _is_caps(path, query):
        _state["xyz_caps"] += 1
        try:
            xml = xyz_sources.capabilities_xml(entry, _state["port"])
        except Exception as e:
            _state["errors"] += 1
            log(u"[xyz] 生成 capabilities 失败 %r  %s" % (e, sid))
            send(u"<error>%r</error>" % (e,), "text/xml; charset=UTF-8", 500)
            return True
        log(u"[xyz] caps %s (%s) -> %d 字节"
            % (sid, entry.get("name"), len(xml)))
        send(xml, "text/xml; charset=UTF-8")
        return True

    # ---- 瓦片 ----
    _state["xyz_tiles"] += 1
    p = kvp(query)
    tm = _int_param(p, "tilematrix")
    row = _int_param(p, "tilerow")
    col = _int_param(p, "tilecol")
    if tm is None or row is None or col is None:
        # 既不是 capabilities 也不像 GetTile —— 说明 ArcMap 拼错了地址。
        # 回一句人能看懂的话，好过悄悄返回空图让人对着白画布猜。
        _state["errors"] += 1
        log(u"[xyz] 参数不全  %s?%s" % (path, query))
        send(u"<error>需要 TILEMATRIX / TILEROW / TILECOL</error>",
             "text/xml; charset=UTF-8", 400)
        return True

    t0 = time.time()

    def _url_for(seq):
        return xyz_sources.tile_url(entry, tm, col, row, seq=seq,
                                    key=_state["key"])

    try:
        # **seq 固定为 0**：子域由 (x+y) 决定，同一张瓦片永远得到同一个
        # 上游地址，缓存才真的命中。seq 只留作"换个子域重试"的偏移。
        url = _url_for(0)
    except Exception as e:
        _state["errors"] += 1
        log(u"[xyz] 拼地址失败 %r  %s" % (e, sid))
        send(b"", "image/png", 500)
        return True

    cache_key = u"xyz|" + url
    hit = _state["tile_cache"].get(cache_key)
    if hit is not None:
        _state["cache_hits"] += 1
        send(hit[1], hit[0])
        return True

    proxy = proxy_for(entry)
    ctype, body = None, None
    for seq in (0, 1):
        try:
            if seq:
                url = _url_for(seq)
            ctype, body = _fetch_abs(url,
                                     referer=entry.get("referer") or u"",
                                     extra=entry.get("headers"),
                                     proxy=proxy)
            break
        except Exception as e:
            if seq == 0:
                # 有些源的部分子域会抽风（解析到坏节点/被限流）。
                # 换一个子域再要一次，比直接给用户一张空白瓦片强。
                log(u"[xyz] 第 1 次失败 %r，换子域重试  %s" % (e, url))
                continue
            _state["errors"] += 1
            log(u"[xyz] 取瓦片失败 %r  %s" % (e, url))
            # 回一张 1x1 透明 PNG：ArcMap 会把这格当"没有数据"继续画别的，
            # 比返回 HTML 错误页（它可能当成图片去解码）安全得多。
            send(_BLANK_PNG, "image/png", 200)
            return True

    if body and len(body) > 500:
        _cache_put(cache_key, (ctype, body))
    log(u"[xyz] %s z=%s r=%s c=%s -> %s %d 字节 %d ms%s"
        % (sid, tm, row, col, ctype, len(body or b""),
           int((time.time() - t0) * 1000),
           u" 直连" if not proxy else u" 代理"))
    send(body, ctype)
    return True


#: 1x1 全透明 PNG（取瓦片失败时的占位）
_BLANK_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ---------------------------------------------------------------------------
# HTTP 处理
# ---------------------------------------------------------------------------

def _normalize_tile_query(query, key):
    """把 ArcMap 拼出来的 GetTile 查询串，规整成天地图认的样子。

    实测 ArcMap 发出来的是（注意 format 是空的、tk 后面没有 &）::

        ?tk=KEYservice=WMTS&request=GetTile&version=1.0.0&layer=cva
         &style=default&format=&TileMatrixSet=w&TileMatrix=1&TileRow=0&TileCol=0

    两个坑，都在这里补掉：

    1. **`tk=KEY` 和 `service=WMTS` 粘在一起了**
       ArcMap 不自己加 `&`，所以 capabilities 里 href 结尾必须是 `&`
       （见 rewrite_capabilities）。但这里仍做一次兜底修复，双保险。

    2. **`format=` 是空的**
       天地图 capabilities 里 `<Format>tiles</Format>`，ArcMap **不认**这个值
       （它期望 image/jpeg 之类的 MIME），于是留空。而天地图 GetTile 恰恰
       就要求 `FORMAT=tiles` —— 我们把 `<Format>` 改写成 MIME 也没用，
       因为还得改回来。所以最省事、最可靠的做法是：**无论 ArcMap 发什么，
       转发前统一强制成 `FORMAT=tiles`**。
    """
    q = query or u""

    # 1) 修复 tk 与后续 KVP 粘连
    if key:
        marker = u"tk=" + key
        i = q.lower().find(marker.lower())
        if i >= 0:
            end = i + len(marker)
            if q[end:end + 1] not in (u"", u"&"):
                q = q[:end] + u"&" + q[end:]

    segs = [s for s in q.split(u"&") if s]
    keep = []
    have_tk = False
    for s in segs:
        k = s.split(u"=", 1)[0].strip().lower()
        if k == u"format":
            continue                       # 下面统一补
        if k == u"tk":
            if key:
                keep.append(u"tk=" + key)
                have_tk = True
            continue
        keep.append(s)

    if key and not have_tk:
        keep.append(u"tk=" + key)
    keep.append(u"FORMAT=tiles")
    return u"&".join(keep)


def _is_caps(path, query):
    """判断这次请求是不是要 capabilities。

    ArcMap 有两种要法，都要认：
      * KVP：``?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0``
      * REST 探测：在连接串后面硬接 ``/1.0.0/WMTSCapabilities.xml``
        （实测它会把这段直接拼在查询串尾巴上，非常脏）
    """
    low = (path + u"?" + query).lower()
    return (u"request=getcapabilities" in low
            or u"getcapabilities" in low
            or u"capabilities.xml" in low)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # 关掉 stderr 噪音（ArcMap 没有控制台，写 stderr 没意义还可能出事）
    def log_message(self, fmt, *args):
        pass

    def _send(self, body, ctype, code=200):
        if body is None:
            body = b""
        if isinstance(body, unicode):        # noqa: F821  (py2)
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
        except Exception:
            pass

    def _handle(self):
        raw = self.path
        try:
            raw = raw.decode("utf-8", "replace")
        except Exception:
            raw = u"%s" % (self.path,)

        if u"?" in raw:
            path, query = raw.split(u"?", 1)
        else:
            path, query = raw, u""

        self_base = u"http://127.0.0.1:%d" % _state["port"]

        if raw.startswith(u"/ping"):
            self._send(b"OK", "text/plain")
            return

        if raw.startswith(u"/stats"):
            self._send(json.dumps(stats()), "application/json")
            return

        # XYZ 图源：capabilities 由本地合成、瓦片靠模板去取，全程不碰天地图。
        # 必须在天地图那条路之前拦下 —— 否则 _fetch 会拿 /xyz/... 去
        # 天地图服务器上找，必然是 404。
        if xyz_entry_from_path(path):
            if handle_xyz(path, query, self._send):
                return

        if _is_caps(path, query):
            _state["caps_hits"] += 1
            # 用干净的 KVP 去上游取，丢掉 ArcMap 拼接时带进来的脏尾巴
            caps_q = u"SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
            try:
                ctype, body = _fetch(path, caps_q, send_ua=True)
                fixed = rewrite_capabilities(body, self_base, _state["key"])
                log(u"[caps] %s?%s -> %d 字节 -> 改写完成" % (path, query, len(body)))
                self._send(fixed, "text/xml; charset=UTF-8")
                return
            except Exception as e:
                _state["errors"] += 1
                log(u"[caps] 失败 %r  %s?%s" % (e, path, query))
                self._send(u"<error>%r</error>" % (e,), "text/xml; charset=UTF-8", 502)
                return

        _state["hits"] += 1
        t_h = time.time()
        try:
            q = _normalize_tile_query(query, _state["key"])
            cache_key = q.lower().replace(_state["key"].lower(), u"KEY") if _state["key"] else q.lower()
            hit = _state["tile_cache"].get(cache_key)
            if hit is not None:
                _state["cache_hits"] += 1
                self._send(hit[1], hit[0])
                return
            ctype, body = _fetch(path, q)
            # 只缓存像样的瓦片（几百字节的空白图/错误页不占地方也无所谓，
            # 但错误响应一律不缓存，免得把偶发失败固化下来）
            if body and len(body) > 500:
                _cache_put(cache_key, (ctype, body))
            if self.command != "HEAD":
                log(u"[tile] %s -> %s %d 字节 %d ms [%s] 处理共 %d ms"
                    % (q, ctype, len(body), _state["last_ms"],
                       _state.get("last_detail", u""),
                       int((time.time() - t_h) * 1000)))
            self._send(body, ctype)
        except Exception as e:
            _state["errors"] += 1
            try:
                code = getattr(e, "code", None) or 502
            except Exception:
                code = 502
            log(u"[tile] 失败 %r  %s?%s [%s]" % (e, path, query,
                                                _state.get("last_detail", u"")))
            self._send(b"", "image/jpeg", code if isinstance(code, int) else 502)

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_POST(self):
        self._handle()


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    #: **绝对不能开 SO_REUSEADDR**。
    #: Windows 上它的语义跟 Unix 相反：允许第二个进程绑到别人正在
    #: LISTENING 的同一个端口上，"地址已占用"这个错误压根不会报出来。
    #: 于是同一个 17817 上会挂着两个中转进程互相抢连接，请求落到哪个
    #: 全看运气 —— 日志里 pid=10592（15:37:06）和 pid=24708（15:40:19）
    #: 同时监听 17817，就是这么来的。万一撞上那个半死的实例，
    #: ArcMap 的绘制线程就永远等不到应答（表现：能加载、不能放大）。
    allow_reuse_address = False

    def server_bind(self):
        # 再加一道独占锁：Windows 专用，占住了谁都抢不走。
        # 抢不走的好处是"端口被占用"会**如实报错**，于是能干净地
        # 顺延到 17818，而不是两个进程骑在同一个端口上。
        opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if opt is not None:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, opt, 1)
            except Exception:
                pass
        HTTPServer.server_bind(self)


# ---------------------------------------------------------------------------
# 启停
# ---------------------------------------------------------------------------

def start(key=u"", upstream=_DEFAULT_HOST, prefer_port=0, send_ua=True):
    """起服务（幂等）。返回实际端口；失败返回 0。"""
    with _lock:
        if _state["server"] is not None:
            if key:
                _state["key"] = key
            return _state["port"]

        _state["key"] = key or u""
        _state["upstream"] = upstream or _DEFAULT_HOST
        _state["send_ua"] = send_ua

        for p in ([prefer_port] if prefer_port else []) + [0]:
            try:
                srv = _Server(("127.0.0.1", p), _Handler)
                _state["server"] = srv
                _state["port"] = srv.server_address[1]
                break
            except Exception as e:
                log(u"监听失败 port=%s: %r" % (p, e))
        if _state["server"] is None:
            return 0

        th = threading.Thread(target=_serve_forever, name="TiandituTileProxy")
        th.daemon = True
        th.start()
        _state["thread"] = th
        log(u"=== 中转服务已启动 127.0.0.1:%d -> %s://%s   UA=%s"
            % (_state["port"], _SCHEME, _state["upstream"],
               u"补" if _state["send_ua"] else u"不补"))
        return _state["port"]


def _serve_forever():
    srv = _state["server"]
    try:
        srv.serve_forever(poll_interval=0.3)
    except Exception as e:
        log(u"serve_forever 退出：%r" % (e,))


def stop():
    with _lock:
        srv = _state["server"]
        _state["server"] = None
        _state["port"] = 0
    if srv is not None:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass


def _selftest(key, maptype="img", port=18099, send_ua=True, seconds=6):
    """独立跑一遍：验证「改写后的 capabilities」+「代发瓦片」都通。"""
    p = start(key=key, prefer_port=port, send_ua=send_ua)
    print(u"服务端口 = %s" % p)
    if not p:
        return 1
    try:
        import json
        caps = capabilities_url(maptype, key=key, host_port=p)
        print(u"caps = %s" % caps)
        ctype, body = _fetch("/%s_w/%swmts" % (maptype, _ESRI_SEG),
                             u"SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0")
        fixed = rewrite_capabilities(body, u"http://127.0.0.1:%d" % p, key)
        hrefs = _HREF_RE.findall(fixed)
        print(u"改写后的 xlink:href（去重）：")
        for h in sorted(set(hrefs)):
            print(u"   %s" % h)
        # 直接打一发瓦片，确认 200 + image
        tile = (u"/%s_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                u"&LAYER=%s&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
                u"&TILEMATRIX=1&TILEROW=0&TILECOL=1" % (maptype, maptype))
        try:
            ct, tb = _fetch(tile, u"")
            print(u"瓦片: %s %d 字节" % (ct, len(tb)))
        except Exception as e:
            print(u"瓦片失败 %r" % (e,))
        print(u"统计: %s" % json.dumps(stats()))
        time.sleep(seconds)
    finally:
        stop()
    return 0


if __name__ == "__main__":
    import io
    sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)
    _k = sys.argv[1] if len(sys.argv) > 1 else u""
    _sendua = (sys.argv[2] if len(sys.argv) > 2 else "1") != "0"
    sys.exit(_selftest(_k, send_ua=_sendua))
