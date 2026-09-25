# -*- coding: utf-8 -*-
"""第六条线索：用 WMTSConnectionName（本身就是 IName）让连接可持久化"""
from __future__ import print_function

import os
import re
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
    for f in ("esriSystem.olb", "esriGISClient.olb", "esriCarto.olb", "esriGeoDatabase.olb"):
        p = os.path.join(GISCOM, f)
        if os.path.isfile(p):
            mods[f] = comtypes.client.GetModule(p)
    return mods


def strings(path):
    data = open(path, "rb").read()
    got = set()
    for enc in ("utf-16-le", "utf-8", "latin-1"):
        t = data.decode(enc, "ignore")
        for m in re.findall(r"https?://[^\x00-\x1f\"'<> ]{5,220}", t):
            got.add(m)
    return data, got


def main():
    import comtypes.client

    maptype = "img"
    url = ("https://t3.tianditu.gov.cn/%s_w/wmts?"
           "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s" % (maptype, TK))
    out = r"D:\Work\projects\arcmap\_test_wmts2.lyr"
    log("URL = %s\n" % url)

    mods = load_types()
    esriSystem, gis, carto = (mods["esriSystem.olb"], mods["esriGISClient.olb"],
                              mods["esriCarto.olb"])

    props = comtypes.client.CreateObject("esriSystem.PropertySet",
                                         interface=esriSystem.IPropertySet)
    props.SetProperty("URL", url)
    props.SetProperty("url", url)

    log("[A] WMTSConnectionName 作为 IName")
    raw = comtypes.client.CreateObject("esriGISClient.WMTSConnectionName")
    log("     raw = %r" % (raw,))
    cn = raw.QueryInterface(gis.IWMTSConnectionName)
    cn.ConnectionProperties = props
    log("     ConnectionProperties 设定 OK")
    name = raw.QueryInterface(esriSystem.IName)
    try:
        log("     NameString = %r" % (name.NameString,))
    except Exception:
        log("     NameString 读取失败:\n" + traceback.format_exc())
    try:
        log("     IsValid = %r" % (name.IsValid(),))
    except Exception as e:
        log("     IsValid 失败 %s" % type(e).__name__)

    log("[B] WMTSLayer.Connect(WMTSConnectionName)")
    lyr = comtypes.client.CreateObject("esriCarto.WMTSLayer", interface=carto.IWMTSLayer)
    ok = lyr.Connect(name)
    log("     Connect -> %r" % (ok,))
    try:
        ds = lyr.DataSourceName
        log("     DataSourceName = %r" % (ds,))
        if ds:
            log("     DataSourceName.NameString = %r" % (ds.NameString,))
    except Exception as e:
        log("     DataSourceName 失败 %s" % type(e).__name__)

    log("[C] 存 .lyr")
    if os.path.isfile(out):
        os.remove(out)
    lf = comtypes.client.CreateObject("esriCarto.LayerFile", interface=carto.ILayerFile)
    lf.New(out)
    lf.ReplaceContents(lyr)
    lf.Save()
    lf.Close()
    data, urls = strings(out)
    log("     大小 %d B" % len(data))
    log("     内嵌 URL: %s" % (sorted(urls) or "（无）"))
    for kw in ("tianditu", "img_w", "tk="):
        log("     含 %-10s : %s" % (kw, kw in data.decode("utf-16-le", "ignore")
                                    or kw in data.decode("latin-1", "ignore")))


if __name__ == "__main__":
    main()
