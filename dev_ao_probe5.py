# -*- coding: utf-8 -*-
"""探路：绕开 comtypes 的 propputref 属性描述符缺陷，把 WMTS 图层建出来"""
from __future__ import print_function

import os
import sys
import traceback

GISCOM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def load_types():
    import comtypes.client
    mods = {}
    for f in ("esriSystem.olb", "esriGISClient.olb", "esriCarto.olb", "esriGeoDatabase.olb"):
        p = os.path.join(GISCOM, f)
        if os.path.isfile(p):
            mods[f] = comtypes.client.GetModule(p)
    return mods


def describe_methods(iface):
    log("    %s._methods_ 共 %d 条" % (iface.__name__, len(iface._methods_)))
    for i, m in enumerate(iface._methods_):
        fl = getattr(m, "flags", None)
        log("      [%2d] %-22s flags=%s" % (i, getattr(m, "name", "?"), fl))


def call_iface(iface, name, want_flag, inst, *args):
    """直接调用 _methods_ 里的条目，绕过属性描述符"""
    for m in iface._methods_:
        flags = getattr(m, "flags", None) or []
        if getattr(m, "name", None) == name and want_flag in flags:
            fn = m.__get__(inst, type(inst))
            return fn(*args)
    raise RuntimeError("method %s/%s not found" % (name, want_flag))


def main():
    import comtypes.client

    mods = load_types()
    esriSystem = mods["esriSystem.olb"]
    gis = mods["esriGISClient.olb"]
    carto = mods["esriCarto.olb"]

    url = ("https://t3.tianditu.gov.cn/img_w/wmts?"
           "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
           "&tk=215a6b9d9f7cba63e8e128dfb4042419")

    log("== IWMTSLayer 方法表 ==")
    describe_methods(carto.IWMTSLayer)
    log("== IWMTSConnection 方法表 ==")
    describe_methods(gis.IWMTSConnection)
    log("== ILayerFile 方法表 ==")
    describe_methods(carto.ILayerFile)

    log("\n== 建连接 ==")
    props = comtypes.client.CreateObject("esriSystem.PropertySet",
                                         interface=esriSystem.IPropertySet)
    props.SetProperty("URL", url)
    fac = comtypes.client.CreateObject("esriGISClient.WMTSConnectionFactory",
                                       interface=gis.IWMTSConnectionFactory)
    conn = fac.Open(props, 0, None)
    log("   conn=%r" % (conn,))
    name = None
    try:
        name = conn.FullName
        log("   conn.FullName = %r" % (name,))
        if name is not None:
            log("   FullName.NameString = %r" % (name.NameString,))
    except Exception:
        log("   FullName 失败:\n" + traceback.format_exc())

    log("\n== 建图层 ==")
    lyr = comtypes.client.CreateObject("esriCarto.WMTSLayer", interface=carto.IWMTSLayer)

    for label, fn in (
        ("A: Connect(IName)", lambda: call_iface(carto.IWMTSLayer, "Connect", "in", lyr, name)),
        ("B: WMTSConnection=conn",
         lambda: call_iface(carto.IWMTSLayer, "WMTSConnection", "propputref", lyr, conn)),
        ("C: WMTSConnection=conn(put)",
         lambda: call_iface(carto.IWMTSLayer, "WMTSConnection", "propput", lyr, conn)),
        ("D: DataSourceName=IName",
         lambda: call_iface(carto.IWMTSLayer, "DataSourceName", "propput", lyr, name)),
    ):
        try:
            r = fn()
            log("   %-28s -> OK %r" % (label, r))
        except Exception as e:
            log("   %-28s -> 失败 %s: %s" % (label, type(e).__name__, str(e)[:140]))

    log("\n== 设属性 ==")
    for attr, val in (("LayerName", "img"), ("Name", u"\u5929\u5730\u56fe-\u5f71\u50cf"),
                      ("TileMatrixSet", "w"), ("ImageFormat", "tiles")):
        try:
            call_iface(carto.IWMTSLayer, attr, "propput", lyr, val)
            log("   %-14s = %-10r OK" % (attr, val))
        except Exception as e:
            log("   %-14s = %-10r 失败 %s: %s" % (attr, val, type(e).__name__, str(e)[:100]))

    log("\n== 状态 ==")
    for attr in ("Name", "LayerName", "Valid", "TileMatrixSet", "ImageFormat", "Style"):
        try:
            v = call_iface(carto.IWMTSLayer, attr, "propget", lyr)
            log("   %-14s = %r" % (attr, v))
        except Exception as e:
            log("   %-14s 读取失败 %s" % (attr, type(e).__name__))

    log("\n== 存 .lyr ==")
    out = r"D:\Work\projects\arcmap\_test_wmts.lyr"
    if os.path.isfile(out):
        os.remove(out)
    lf = comtypes.client.CreateObject("esriCarto.LayerFile", interface=carto.ILayerFile)
    lf.New(out)
    log("   New OK")
    try:
        call_iface(carto.ILayerFile, "Layer", "propputref", lf, lyr)
        log("   Layer= OK")
    except Exception:
        try:
            call_iface(carto.ILayerFile, "Layer", "propput", lf, lyr)
            log("   Layer= (put) OK")
        except Exception:
            log("   Layer= 失败:\n" + traceback.format_exc())
    lf.Save()
    lf.Close()
    log("   文件: %s (%s B)" % (os.path.isfile(out), os.path.getsize(out) if os.path.isfile(out) else 0))


if __name__ == "__main__":
    main()
