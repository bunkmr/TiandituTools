# -*- coding: utf-8 -*-
"""ArcObjects 桥 —— 在 ArcMap 进程内直接创建「天地图 WMTS 图层」并加入地图。

为什么必须走 ArcObjects
-----------------------
* arcpy 10.4 **没有** MakeWMTSLayer / MakeWMSLayer；
* `arcpy.mapping.Layer(<URL>)` 实测一律报 “CreateObject Layer 的数据源无效”，
  它只认 .lyr 文件或地图里的图层；
  ⇒ 纯 arcpy **无法凭空造出在线 WMTS 图层**，这正是「不能自动增加图层」的根因。

ArcObjects 里有现成的两件东西：
    esriGISClient.WMTSConnectionName   —— 承载连接参数（IPropertySet 里的 URL）
    esriCarto.WMTSLayer                —— 真正的 WMTS 图层，实现 ILayer
再用 esriFramework.esriAppROT 拿到**正在运行的 ArcMap**：
    IAppROT -> IApplication -> IMxDocument -> FocusMap(IMap) -> AddLayer(ILayer)

为什么必须用 comtypes 而不是 win32com
-------------------------------------
ArcGIS 的接口是非 IDispatch 的纯 vtable 接口（类型库里 1020 个接口只有 3 个
标了 dispatch），win32com 的后期绑定够不到 `IMap.AddLayer` 这类带接口指针的
方法。comtypes 会按类型库生成 vtable 包装，能原样调用。

依赖
----
已装进 ArcGIS 自带的 Python 2.7（`C:\\Python27\\ArcGIS10.4\\Lib\\site-packages`）：
    comtypes 1.1.14（纯 Python，无需编译）
首次使用会为 ArcGIS 类型库生成包装模块到 `comtypes\\gen`（本机已生成好，
之后一直走缓存）。

运行位置（重要）
----------------
* **必须在 ArcMap 进程内跑**（即加载项 onClick 里同步调用）。
  原因：`esriCarto.WMTSLayer` 是 in-proc 组件，在外部进程里 new 出来之后，
  `IMap.AddLayer` 只能把一个**跨进程代理**塞给 ArcMap；外部进程一退出，
  ArcMap 手里的图层就成了断线代理 —— 重绘时轻则画不出来（空白画布），
  重则直接崩掉。实测：加图层的进程被关闭后，ArcMap 在数秒内死亡。
* 因此界面（Tkinter）仍然放在独立进程，但**造图层、加图层这一步回到
  ArcMap 进程内做** —— 见 layer_manager / ui_bridge 顶部说明。

安全约束（沿用项目既有约定）
--------------------------
* 本模块绝不 import Tkinter；
* **绝不 import arcpy**（会把 Geoprocessing/Raster/DFORRT 拉进来）；
* 任何异常都在本层吞掉并记录，绝不把异常抛给调用方的 C 层。
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import os
import traceback

# ---------------------------------------------------------------------------
# 常量与状态
# ---------------------------------------------------------------------------

_FALLBACK_COM_DIR = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"

#: 需要的类型库（顺序即依赖顺序）
_OLBS = (
    "esriSystem.olb",
    "esriGISClient.olb",
    "esriCarto.olb",
    "esriFramework.olb",
    "esriArcMapUI.olb",
)

_TYPES = None            # {"esriSystem": <module>, ...}
_AVAILABLE = None        # 三态：None 未判定 / True / False
_last_error = u""

_LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "TiandituTools")
_MARKER = os.path.join(_LOG_DIR, "ao_types.v104.ok")


def get_last_error():
    """上一条错误描述（给界面提示用）"""
    return _last_error


def _log(text):
    try:
        if not os.path.isdir(_LOG_DIR):
            os.makedirs(_LOG_DIR)
        with open(os.path.join(_LOG_DIR, "arcobjects.log"), "ab") as f:
            f.write((u"%s\n" % text).encode("utf-8", "ignore"))
    except Exception:
        pass


def _set_error(text):
    global _last_error
    _last_error = text
    _log(text)


# ---------------------------------------------------------------------------
# 环境探测
# ---------------------------------------------------------------------------

#: 可接受的 ArcGIS Desktop 版本（用于注册表/默认路径探测）
_VERSIONS = ("10.8", "10.7", "10.6", "10.5", "10.4", "10.3", "10.2", "10.1")


def com_dir():
    """ArcGIS 的 .olb 目录。

    **绝不 import arcpy** —— 这一条很关键：
    在 ArcMap 之外（比如界面子进程）import arcpy 会把 Geoprocessing /
    RasterEngine 一整条栈拉进来（`arcgisscripting.pyd` -> `GeoprocessingLib`
    -> `RasterCoreLib` -> **DFORRT.dll**）。DFORRT 是 Fortran 运行时，它要往
    unit 0 也就是 CONOUT$ 写诊断信息；而界面子进程是用 CREATE_NO_WINDOW 起的
    （没有控制台），这次写会失败，于是弹出模态框
    "Visual Fortran run-time error / forrtl: severe (38): error during write,
     unit 0, file CONOUT$" 并**把该进程永久卡住**。
    这就是"点添加底图后弹窗、ArcMap 跟着崩"的真正来源。

    所以这里只查环境变量和注册表，不碰 arcpy。
    """
    p = os.environ.get("TIANDITU_ARCGIS_COM")
    if p and os.path.isfile(os.path.join(p, "esriCarto.olb")):
        return p

    try:
        import _winreg
        hklm = _winreg.HKEY_LOCAL_MACHINE
        for ver in _VERSIONS:
            for sub in (r"SOFTWARE\ESRI\Desktop" + ver,
                        r"SOFTWARE\WOW6432Node\ESRI\Desktop" + ver):
                try:
                    k = _winreg.OpenKey(hklm, sub)
                except Exception:
                    continue
                for name in ("InstallDir", "PythonDir"):
                    try:
                        v = _winreg.QueryValueEx(k, name)[0]
                    except Exception:
                        continue
                    if not v:
                        continue
                    d = os.path.dirname(v) if name == "PythonDir" else v
                    com = os.path.join(d, "com")
                    if os.path.isfile(os.path.join(com, "esriCarto.olb")):
                        return com
    except Exception:
        pass

    if os.path.isfile(os.path.join(_FALLBACK_COM_DIR, "esriCarto.olb")):
        return _FALLBACK_COM_DIR
    return _FALLBACK_COM_DIR


def is_cached():
    """本机是否已经把 ArcGIS 类型库生成过（生成一次约 1~2 分钟）

    只做文件系统判断，不 import comtypes —— 免得为了打个招呼先把重活干了。
    """
    if os.path.isfile(_MARKER):
        return True
    try:
        import comtypes.gen as _gen
        for d in list(getattr(_gen, "__path__", []) or []):
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                # 生成物形如 _45AC68FF_DEFF_4884_..._0_10_4.py
                if fn.startswith("_") and fn.endswith(".py") and fn.count("_") >= 4:
                    _write_marker()
                    return True
    except Exception:
        pass
    return False


def _write_marker():
    try:
        if not os.path.isdir(_LOG_DIR):
            os.makedirs(_LOG_DIR)
        with open(_MARKER, "w") as f:
            f.write(b"ok\n")
    except Exception:
        pass


def _comtypes_importable():
    try:
        import comtypes.client                              # noqa: F401
        return True
    except Exception as e:
        _set_error(u"comtypes 导入失败：%r" % (e,))
        return False


def available():
    """本机现在能不能用 ArcObjects（comtypes 在 + ArcGIS 类型库在）"""
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    if not _comtypes_importable():
        _AVAILABLE = False
        return False
    d = com_dir()
    if not os.path.isfile(os.path.join(d, "esriCarto.olb")):
        _set_error(u"找不到 ArcGIS 类型库目录：%s" % d)
        _AVAILABLE = False
        return False
    _AVAILABLE = True
    return True


def _init_com():
    """确保当前线程已初始化 COM（ArcMap 主线程本来就是 STA，重复调用返回 S_FALSE 无害）"""
    try:
        import ctypes
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)     # COINIT_APARTMENTTHREADED
        except Exception:
            pass
        return True
    except Exception as e:
        _set_error(u"CoInitializeEx 失败：%r" % (e,))
        return False


# ---------------------------------------------------------------------------
# 类型库
# ---------------------------------------------------------------------------

def ensure_types():
    """加载（必要时生成）ArcGIS 类型库包装模块；失败抛异常。"""
    global _TYPES
    if _TYPES is not None:
        return _TYPES

    if not available():
        raise RuntimeError(_last_error or u"ArcObjects 不可用")

    _init_com()
    import comtypes.client

    d = com_dir()
    mods = {}
    missing = []
    for fn in _OLBS:
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            missing.append(fn)
            continue
        mods[fn.split(".")[0]] = comtypes.client.GetModule(p)
    if missing:
        _log(u"缺少类型库：%s" % u", ".join(missing))

    for need in ("esriSystem", "esriGISClient", "esriCarto", "esriFramework",
                 "esriArcMapUI"):
        if need not in mods:
            raise RuntimeError(u"缺少必需的类型库：%s" % need)

    _write_marker()

    _TYPES = mods
    return _TYPES


def prewarm():
    """提前把类型库生成好（放在独立进程里跑，避免 ArcMap 卡顿）。返回 (ok, msg)"""
    try:
        ensure_types()
        return True, u"类型库已就绪"
    except Exception:
        return False, traceback.format_exc()


# ---------------------------------------------------------------------------
# 取正在运行的 ArcMap / 当前地图
# ---------------------------------------------------------------------------

def application(retries=3, wait=1.0):
    """IApplication（通过 AppROT 拿正在运行的 ArcMap）；没有则返回 None

    AppROT 是本机「正在运行的 ArcGIS 应用表」：实测外部 32 位进程用
    `esriFramework.esriAppROT` 能稳定拿到 ArcMap（Count=1，Caption='… - ArcMap'）。
    ArcMap 刚启动的那几秒里可能还没注册，所以带几次重试。
    """
    mods = ensure_types()
    import comtypes.client

    last = u""
    for i in range(max(1, retries)):
        try:
            rot = comtypes.client.CreateObject(
                "esriFramework.esriAppROT",
                interface=mods["esriFramework"].IAppROT)
            n = rot.Count
            if n > 0:
                return rot.Item(0)
            last = u"AppROT 里没有正在运行的 ArcGIS 应用（Count=0）"
        except Exception as e:
            last = u"AppROT 访问失败：%r" % (e,)
        if i + 1 < retries:
            try:
                import time
                time.sleep(wait)
            except Exception:
                pass
    _set_error(last or u"取不到正在运行的 ArcGIS 应用")
    return None


def document():
    """IMxDocument"""
    mods = ensure_types()
    app = application()
    if app is None:
        return None
    return app.Document.QueryInterface(mods["esriArcMapUI"].IMxDocument)


def current_map():
    """IMap（当前聚焦的地图）；没有地图则返回 None"""
    mx = document()
    if mx is None:
        return None
    try:
        return mx.FocusMap
    except Exception as e:
        _set_error(u"取 FocusMap 失败：%r" % (e,))
        return None


# ---------------------------------------------------------------------------
# 组装 WMTS 图层
# ---------------------------------------------------------------------------

# 天地图 WMTS 的三个固定关键字（capabilities 里就是这三个值）：
#   TileMatrixSet = w          Style = default      Format = tiles
# Connect 之后 ImageFormat 回读是空的，必须显式补上（详见 create_wmts_layer）。
_TILE_MATRIX = "w"
_STYLE = "default"
_FORMAT = "tiles"


def create_wmts_layer(caps_url, display_name=None, layer_id=None):
    """按 WMTS 服务地址造一个 ILayer（真正连上服务才算成功）。

    `layer_id` 是 WMTS 服务里子图层的 Identifier（天地图 = maptype，如 "img"）。
    必须给 —— 只填 URL 时 `IWMTSLayer` 连上了服务却**没选中任何子图层**，
    结果就是「图层在面板里、一发瓦片都不请求」，画布当然空白。
    这个键在 IPropertySet 里叫 ``LAYERNAME``（Esri 官方只认这 7 个键：
    URL / LAYERNAME / USER / HIDEUSERPROPERTY / VERSION / PASSWORD /
    CONNECTIONPATH，没有自定义参数位，所以 tk 只能塞进 URL —— 见 tile_proxy）。
    """
    mods = ensure_types()
    es = mods["esriSystem"]
    gis = mods["esriGISClient"]
    carto = mods["esriCarto"]

    import comtypes.client as cc

    # 1) 连接参数
    props = cc.CreateObject("esriSystem.PropertySet", interface=es.IPropertySet)
    props.SetProperty("URL", caps_url)
    try:
        props.SetProperty("VERSION", "1.0.0")
    except Exception:
        pass
    if layer_id:
        props.SetProperty("LAYERNAME", layer_id)

    # 2) WMTSConnectionName —— 它本身就是可传给 Connect 的 IName
    raw_name = cc.CreateObject("esriGISClient.WMTSConnectionName")
    raw_name.QueryInterface(gis.IWMTSConnectionName).ConnectionProperties = props
    conn_name = raw_name.QueryInterface(es.IName)

    # 3) WMTSLayer
    raw_layer = cc.CreateObject("esriCarto.WMTSLayer")
    wmts = raw_layer.QueryInterface(carto.IWMTSLayer)
    ok = wmts.Connect(conn_name)
    if not ok:
        raise RuntimeError(u"WMTS 服务连接失败：%s" % caps_url)

    # 4) 三个关键字**每次都显式落一遍**。
    #
    # 为什么不能只靠 Connect 自动填：实测 Connect 之后回读
    #   LayerName='img' ✓  TileMatrixSet='w' ✓  Style='default' ✓
    #   **ImageFormat='' ✗**
    # 天地图 capabilities 里的 Format 是 `tiles`。ImageFormat 空着，ArcMap
    # 就拼不出带 FORMAT=... 的 GetTile 请求 —— 现象正是
    # 「服务连上了、capabilities 也取了、可**一个瓦片都不请求**、画布空白」。
    # 这三个属性在 IWMTSLayer 上都是可写的，所以直接补上。
    for key, val in (("TileMatrixSet", _TILE_MATRIX), ("Style", _STYLE),
                     ("ImageFormat", _FORMAT)):
        if not val:
            continue
        try:
            setattr(wmts, key, val)
        except Exception as e:
            _log(u"设 %s=%r 失败：%r" % (key, val, e))

    picked = _read_wmts(wmts)
    _log(u"create_wmts_layer: 请求 layer_id=%r -> 回读 %s" % (layer_id, picked))

    ilayer = raw_layer.QueryInterface(carto.ILayer)
    if display_name:
        try:
            ilayer.Name = display_name
        except Exception:
            pass
    _log(u"create_wmts_layer OK: %s" % display_name)
    return ilayer


def _read_wmts(wmts):
    """把 IWMTSLayer 上几个关键属性读成一段可打印的文本（排查用）"""
    parts = []
    for k in ("LayerName", "TileMatrixSet", "Style", "ImageFormat"):
        try:
            parts.append(u"%s=%r" % (k, wmts.__getattribute__(k)))
        except Exception as e:
            parts.append(u"%s=<%r>" % (k, e))
    return u" ".join(parts)


def probe_wmts(caps_url, layer_id=None):
    """连一次并把 IWMTSLayer 上的关键属性读出来（排查用，不返回 ILayer）"""
    mods = ensure_types()
    es = mods["esriSystem"]
    gis = mods["esriGISClient"]
    carto = mods["esriCarto"]
    import comtypes.client as cc

    props = cc.CreateObject("esriSystem.PropertySet", interface=es.IPropertySet)
    props.SetProperty("URL", caps_url)
    if layer_id:
        props.SetProperty("LAYERNAME", layer_id)
    raw_name = cc.CreateObject("esriGISClient.WMTSConnectionName")
    raw_name.QueryInterface(gis.IWMTSConnectionName).ConnectionProperties = props
    conn_name = raw_name.QueryInterface(es.IName)

    raw_layer = cc.CreateObject("esriCarto.WMTSLayer")
    wmts = raw_layer.QueryInterface(carto.IWMTSLayer)
    ok = wmts.Connect(conn_name)

    info = {"connected": bool(ok)}
    for key, val in (("TileMatrixSet", _TILE_MATRIX), ("Style", _STYLE),
                     ("ImageFormat", _FORMAT)):
        try:
            setattr(wmts, key, val)
        except Exception as e:
            info["set_" + key] = u"<%r>" % (e,)
    for k in ("LayerName", "TileMatrixSet", "Style", "ImageFormat"):
        try:
            info[k] = wmts.__getattribute__(k)
        except Exception as e:
            info[k] = u"<%r>" % (e,)
    try:
        d = wmts.Dimensions
        info["Dimensions"] = d.Count if d is not None else None
    except Exception as e:
        info["Dimensions"] = u"<%r>" % (e,)
    return info


def add_layers_bottom(ilayers):
    """把一组图层加进当前地图并整体沉到最底部。

    ilayers 按 **显示顺序（上 -> 下）** 给出，例如 [注记, 底图]。
    """
    if not ilayers:
        return False
    m = current_map()
    if m is None:
        raise RuntimeError(u"取不到当前地图（ArcMap 里可能还没打开地图）")

    # 先按「反过来」逐个 AddLayer：AddLayer 每次插到最上面，
    # 所以最后加进去的正好是最上面那一个。
    for lyr in reversed(list(ilayers)):
        m.AddLayer(lyr)

    n = m.LayerCount
    target = n - 1
    for lyr in reversed(list(ilayers)):
        try:
            m.MoveLayer(lyr, target)
        except Exception as e:
            _log(u"MoveLayer 失败（忽略）：%r" % (e,))
        target -= 1
    return True


# ---------------------------------------------------------------------------
# .lyr 路线 —— 让 ArcMap 自己、在它自己进程里把图层对象造出来
# ---------------------------------------------------------------------------

#: 一个 WMTS 图层的完整定义只需要这几样东西
def save_wmts_lyr(caps_url, display_name=None, layer_id=None, lyr_path=None):
    """把「WMTS 图层定义」存成一个 .lyr 文件，返回文件路径。

    为什么绕这一圈
    --------------
    `esriCarto.WMTSLayer` 是 in-proc 组件：谁 CreateObject 它就活在谁的进程里。
    外部进程造出来再 `IMap.AddLayer` 塞给 ArcMap，ArcMap 手里只有一个
    **跨进程代理** —— 面板里有图层、范围也对，但一次 Draw 都不会发生，
    于是**一个瓦片都不请求**（实测 tiles=0，而 capabilities 正常取到）。
    `.lyr` 存的是「图层定义」而不是活对象；ArcMap 打开 .lyr 时会**在它自己的
    进程里**按定义重新实例化 WMTSLayer，这样拿到的就是货真价实的本地对象。
    """
    mods = ensure_types()
    carto = mods["esriCarto"]
    import comtypes.client as cc

    layer = create_wmts_layer(caps_url, display_name, layer_id)

    if not lyr_path:
        lyr_path = os.path.join(_temp_dir(), u"tianditu_%s.lyr"
                                % (layer_id or u"layer"))
    try:
        if os.path.isfile(lyr_path):
            os.remove(lyr_path)
    except Exception:
        pass

    lf = cc.CreateObject("esriCarto.LayerFile",
                         interface=carto.ILayerFile)
    lf.New(lyr_path)
    lf.ReplaceContents(layer)
    lf.Save()
    try:
        lf.Close()
    except Exception:
        pass
    _log(u"save_wmts_lyr OK: %s" % lyr_path)
    return lyr_path


def _temp_dir():
    d = os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"),
                     "TiandituTools")
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
    except Exception:
        pass
    return d


def load_lyr(lyr_path):
    """打开 .lyr，返回 (ILayerFile, ILayer)。ILayerFile 必须保持引用别释放。"""
    mods = ensure_types()
    carto = mods["esriCarto"]
    import comtypes.client as cc

    lf = cc.CreateObject("esriCarto.LayerFile", interface=carto.ILayerFile)
    lf.Open(lyr_path)
    if not lf.IsLayerFile:
        raise RuntimeError(u"不是有效的图层文件：%s" % lyr_path)
    layer = lf.Layer
    if layer is None:
        raise RuntimeError(u"图层文件里没有图层：%s" % lyr_path)
    return lf, layer


def add_lyr_bottom(lyr_paths, keep=None):
    """把若干 .lyr 的图层加进当前地图并沉到底部。

    lyr_paths 按 **显示顺序（上 -> 下）** 给出。
    keep: 可选 list，用来接住 ILayerFile 引用，避免被 GC 提前释放。
    """
    paths = list(lyr_paths or [])
    if not paths:
        return False
    m = current_map()
    if m is None:
        raise RuntimeError(u"取不到当前地图（ArcMap 里可能还没打开地图）")

    holders = keep if keep is not None else []
    layers = []
    for p in paths:
        lf, layer = load_lyr(p)
        holders.append(lf)
        layers.append(layer)

    for layer in reversed(layers):
        m.AddLayer(layer)

    n = m.LayerCount
    target = n - 1
    for layer in reversed(layers):
        try:
            m.MoveLayer(layer, target)
        except Exception as e:
            _log(u"MoveLayer 失败（忽略）：%r" % (e,))
        target -= 1
    return True


def refresh():
    """重绘地图并刷新内容列表"""
    try:
        mx = document()
        if mx is None:
            return False
        try:
            mx.ActiveView.Refresh()
        except Exception:
            pass
        try:
            mx.UpdateContents()
        except Exception:
            pass
        return True
    except Exception as e:
        _log(u"refresh 失败：%r" % (e,))
        return False


def _set_extent(av, env):
    """把视图范围设成 env。

    `IActiveView.Extent` 在类型库里是 propputref，comtypes 有时不给 setter，
    所以退一步：拿到当前 Extent 对象就地 PutCoords。
    """
    try:
        av.Extent = env
        return True
    except Exception as e:
        _log(u"av.Extent = env 失败（改走 PutCoords）：%r" % (e,))
    try:
        cur = av.Extent
        cur.PutCoords(env.XMin, env.YMin, env.XMax, env.YMax)
        return True
    except Exception as e:
        _log(u"设置 Extent 失败：%r" % (e,))
        return False


def adopt_spatial_reference():
    """数据框还没有空间参考时，用地图里第一个图层的空间参考填上。

    新建的空地图数据框 SR 是“未知”，此时在线栅格底图同样画不出来。
    """
    try:
        mx = document()
        if mx is None:
            return False
        m = mx.FocusMap
        try:
            if m.SpatialReference is not None:
                return True
        except Exception:
            return False
        for i in range(m.LayerCount):
            try:
                sr = m.Layer[i].SpatialReference
            except Exception:
                sr = None
            if sr is None:
                continue
            try:
                m.SpatialReference = sr
                _log(u"已用图层 SR 填充数据框")
            except Exception as e:
                _log(u"设置地图 SR 失败（忽略）：%r" % (e,))
            return True
    except Exception as e:
        _log(u"adopt_spatial_reference 失败：%r" % (e,))
    return False


def zoom_full_extent():
    """缩放到全图，让刚加进去的在线底图**真正显示出来**。

    为什么必须有这一步
    ------------------
    用 `IMap.AddLayer` 加图层，ArcMap **不会**像「添加数据」对话框那样自动
    把视图缩放到图层范围。新建的空地图范围是 (0,0)-(0,0)，于是图层面板里
    明明有两个图层，画布却一片空白 —— 用户看到的就是「加了但不显示」。

    接口归属（comtypes 生成的名称，别写错）：
        IMap        -> RecalcFullExtent()   （**不是** RecalculateFullExtent）
        IActiveView -> FullExtent / Extent / Refresh
    """
    try:
        mx = document()
        if mx is None:
            return False
        m = mx.FocusMap
        av = mx.ActiveView

        adopt_spatial_reference()

        try:
            m.RecalcFullExtent()
        except Exception as e:
            _log(u"RecalcFullExtent 失败（忽略）：%r" % (e,))

        env = None
        try:
            env = av.FullExtent
        except Exception as e:
            _log(u"取 FullExtent 失败：%r" % (e,))

        if env is not None:
            empty = False
            try:
                empty = bool(env.IsEmpty)
            except Exception:
                pass
            if not empty:
                _set_extent(av, env)

        try:
            av.Refresh()
        except Exception:
            pass
        try:
            mx.UpdateContents()
        except Exception:
            pass
        return True
    except Exception as e:
        _log(u"zoom_full_extent 失败：%r" % (e,))
        return False


# ---------------------------------------------------------------------------
# 一次性组合入口
# ---------------------------------------------------------------------------

def add_wmts(caps_url, display_name=None, extra=None, layer_id=None):
    """建图层 + 加进地图 + 刷新。失败抛异常。

    extra: 要一起加的其它 WMTS 地址 [(caps_url, name, layer_id), ...]，
           会加在同一组里并按「先给出的画在上面」排序。
    """
    top = [(caps_url, display_name, layer_id)] if caps_url else []
    layers = []
    for item in list(top) + list(extra or []):
        url, name, lid = (list(item) + [None, None, None])[:3]
        layers.append(create_wmts_layer(url, name, lid))
    add_layers_bottom(layers)
    zoom_full_extent()
    return True
