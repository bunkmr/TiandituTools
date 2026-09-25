# -*- coding: utf-8 -*-
"""第七条线索：AppROT -> IApplication -> IMxDocument -> IMap -> AddLayer

先验证「拿到正在运行的 ArcMap 的地图」，再验证「把关 WMTS 图层直接加进 TOC」。
"""
from __future__ import print_function

import os
import sys
import traceback

GISCOM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"
TK = "215a6b9d9f7cba63e8e128dfb4042419"


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def load_types():
    import comtypes.client
    mods = {}
    for f in ("esriSystem.olb", "esriGISClient.olb", "esriCarto.olb",
              "esriGeoDatabase.olb", "esriFramework.olb", "esriArcMapUI.olb"):
        p = os.path.join(GISCOM, f)
        if os.path.isfile(p):
            mods[f] = comtypes.client.GetModule(p)
    return mods


def get_rot(framework):
    import comtypes.client
    log("[A] 拿 AppROT")
    for pid in ("esriFramework.esriAppROT", "esriFramework.esriAppROT.1"):
        try:
            rot = comtypes.client.CreateObject(pid, interface=framework.IAppROT)
            log("     CreateObject(%s) -> %r" % (pid, rot))
            return rot
        except Exception as e:
            log("     %s 失败 %s: %s" % (pid, type(e).__name__, str(e)[:110]))
    try:
        clsid = framework.AppROT._reg_clsid_
        rot = comtypes.client.CreateObject(clsid, interface=framework.IAppROT)
        log("     by CLSID -> %r" % (rot,))
        return rot
    except Exception:
        log("     by CLSID 失败:\n" + traceback.format_exc())
    return None


def get_app(rot):
    log("[B] AppROT -> IApplication")
    try:
        n = rot.Count
        log("     Count = %r" % (n,))
    except Exception:
        log("     Count 失败:\n" + traceback.format_exc())
        return None
    for i in range(3):
        for label, fn in (("rot.Item(%d)" % i, lambda: rot.Item(i)),
                          ("getattr Item(%d)" % i, lambda: getattr(rot, "Item")(i)),
                          ("Item[%d]" % i, lambda: rot.Item[i])):
            try:
                app = fn()
                log("     %-18s -> %r" % (label, app))
                if app is not None:
                    return app
            except Exception as e:
                log("     %-18s 失败 %s: %s" % (label, type(e).__name__, str(e)[:90]))
    return None


def get_map(app, uimod):
    log("[C] IApplication -> IMxDocument -> FocusMap")
    doc = app.Document
    log("     Document = %r" % (doc,))
    mx = app.Document
    try:
        mx = app.Document.QueryInterface(uimod.IMxDocument)
        log("     QueryInterface(IMxDocument) = %r" % (mx,))
    except Exception:
        log("     QueryInterface(IMxDocument) 失败:\n" + traceback.format_exc())
    fmap = mx.FocusMap
    log("     FocusMap = %r  Name=%r LayerCount=%r"
        % (fmap, getattr(fmap, "Name", None), getattr(fmap, "LayerCount", None)))
    return fmap


def main():
    import comtypes.client

    mods = load_types()
    framework = mods["esriFramework.olb"]
    uimod = mods["esriArcMapUI.olb"]
    carto = mods["esriCarto.olb"]
    gis = mods["esriGISClient.olb"]
    esriSystem = mods["esriSystem.olb"]

    log("WMTSLayer 实现接口: %s"
        % [i.__name__ for i in carto.WMTSLayer._com_interfaces_][:12])

    rot = get_rot(framework)
    if rot is None:
        log("拿不到 AppROT")
        return 1
    app = get_app(rot)
    if app is None:
        log("拿不到 IApplication")
        return 1
    try:
        log("     app.Name = %r  app.Caption = %r" % (app.Name, app.Caption))
    except Exception as e:
        log("     app.Name/Caption 失败 %s" % type(e).__name__)

    fmap = get_map(app, uimod)
    before = fmap.LayerCount
    log("     加入前 LayerCount = %r" % before)

    log("[D] 造 WMTS 图层")
    url = ("https://t3.tianditu.gov.cn/img_w/wmts?"
           "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s" % TK)
    props = comtypes.client.CreateObject("esriSystem.PropertySet",
                                         interface=esriSystem.IPropertySet)
    props.SetProperty("URL", url)
    fac = comtypes.client.CreateObject("esriGISClient.WMTSConnectionFactory",
                                       interface=gis.IWMTSConnectionFactory)
    conn = fac.Open(props, 0, None)
    # WMTSConnectionName 本身就是可持久化的 IName
    raw = comtypes.client.CreateObject("esriGISClient.WMTSConnectionName")
    raw.QueryInterface(gis.IWMTSConnectionName).ConnectionProperties = props
    name = raw.QueryInterface(esriSystem.IName)

    raw_layer = comtypes.client.CreateObject("esriCarto.WMTSLayer")
    wmts = raw_layer.QueryInterface(carto.IWMTSLayer)
    log("     Connect -> %r" % (wmts.Connect(name),))
    ilayer = raw_layer.QueryInterface(carto.ILayer)
    try:
        ilayer.Name = u"TiandituTest"
    except Exception as e:
        log("     设 ILayer.Name 失败 %s" % type(e).__name__)

    log("[E] IMap.AddLayer")
    try:
        fmap.AddLayer(ilayer)
        log("     AddLayer OK")
    except Exception:
        log("     AddLayer 失败:\n" + traceback.format_exc())
    after = fmap.LayerCount
    log("     加入后 LayerCount = %r" % after)
    try:
        for i in range(after):
            try:
                l = fmap.Layer[i]
                log("       [%d] %r" % (i, getattr(l, "Name", "?")))
            except Exception:
                pass
    except Exception as e:
        log("     枚举图层失败 %s" % type(e).__name__)
    return 0 if after > before else 1


if __name__ == "__main__":
    sys.exit(main())
