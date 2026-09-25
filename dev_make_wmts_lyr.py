# -*- coding: utf-8 -*-
"""天地图 WMTS -> .lyr 生成器（ArcObjects + comtypes）

用法: python dev_make_wmts_lyr.py <maptype> <tk> <out.lyr> [subdomain]
"""
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


def caps_url(maptype, tk, sub="t3"):
    return ("https://%s.tianditu.gov.cn/%s_w/wmts?"
            "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s" % (sub, maptype, tk))


def make_connection(esriSystem, gis, url):
    import comtypes.client

    props = comtypes.client.CreateObject("esriSystem.PropertySet",
                                         interface=esriSystem.IPropertySet)
    props.SetProperty("URL", url)
    props.SetProperty("UserName", "")
    props.SetProperty("Password", "")

    fac = comtypes.client.CreateObject("esriGISClient.WMTSConnectionFactory",
                                       interface=gis.IWMTSConnectionFactory)
    conn = fac.Open(props, 0, None)
    log("   factory.Open -> %r" % (conn,))
    return props, conn


def name_of(conn):
    try:
        nm = conn.FullName
    except Exception as e:
        log("   conn.FullName 失败 %s" % type(e).__name__)
        return None
    if nm is None:
        return None
    try:
        ns = nm.NameString
    except Exception:
        ns = "<读不到>"
    log("   conn.FullName.NameString = %r" % (ns,))
    return nm


def try_build(carto, gis, esriSystem, url, layer_id, display_name, out_path):
    import comtypes.client

    log("[1] 打开 WMTS 连接")
    props, conn = make_connection(esriSystem, gis, url)
    nm = name_of(conn)

    log("[2] 建 WMTSLayer 并绑定连接")
    lyr = comtypes.client.CreateObject("esriCarto.WMTSLayer",
                                       interface=carto.IWMTSLayer)
    bound = None
    if nm is not None:
        for label, fn in (("Connect(IName)", lambda: lyr.Connect(nm)),
                          ("DataSourceName=IName", lambda: setattr(lyr, "DataSourceName", nm))):
            try:
                r = fn()
                log("   %-22s OK  ret=%r" % (label, r))
                bound = label
                break
            except Exception as e:
                log("   %-22s 失败 %s: %s" % (label, type(e).__name__, str(e)[:120]))

    if bound is None:
        # 退路：直接用 WMTSConnectionName
        log("   改用 WMTSConnectionName")
        try:
            cn = comtypes.client.CreateObject("esriGISClient.WMTSConnectionName",
                                              interface=gis.IWMTSConnectionName)
            cn.ConnectionProperties = props
            unk = cn.OpenEx(None)
            log("   OpenEx -> %r" % (unk,))
            nm2 = None
            try:
                nm2 = comtypes.client.CreateObject  # noqa
            except Exception:
                pass
            c2 = unk.QueryInterface(gis.IWMTSConnection)
            nm2 = name_of(c2)
            if nm2 is not None:
                lyr.Connect(nm2)
                bound = "WMTSConnectionName"
                log("   Connect 通过 WMTSConnectionName OK")
        except Exception:
            log("   WMTSConnectionName 路径失败:\n" + traceback.format_exc())

    log("[3] 只读状态")
    for a in ("Valid", "Name"):
        try:
            log("   %-8s = %r" % (a, getattr(lyr, a)))
        except Exception as e:
            log("   %-8s 读取失败 %s" % (a, type(e).__name__))
    try:
        ds = lyr.DataSourceName
        log("   DataSourceName = %r  NameString=%r"
            % (ds, getattr(ds, "NameString", None) if ds else None))
    except Exception as e:
        log("   DataSourceName 读取失败 %s" % type(e).__name__)

    log("[4] 设图层显示名")
    for a, v in (("Name", display_name), ("LayerName", layer_id)):
        try:
            setattr(lyr, a, v)
            log("   %-10s = %r OK" % (a, v))
        except Exception as e:
            log("   %-10s = %r 失败 %s" % (a, v, type(e).__name__))

    log("[5] 写 .lyr")
    if os.path.isfile(out_path):
        os.remove(out_path)
    lf = comtypes.client.CreateObject("esriCarto.LayerFile", interface=carto.ILayerFile)
    lf.New(out_path)
    lf.ReplaceContents(lyr)
    lf.Save()
    lf.Close()
    ok = os.path.isfile(out_path)
    log("   %s  (%s B)" % (out_path, os.path.getsize(out_path) if ok else "-"))
    return ok


def main():
    maptype = sys.argv[1] if len(sys.argv) > 1 else "img"
    tk = sys.argv[2] if len(sys.argv) > 2 else ""
    out = sys.argv[3] if len(sys.argv) > 3 else r"D:\Work\projects\arcmap\_test_wmts.lyr"
    sub = sys.argv[4] if len(sys.argv) > 4 else "t3"
    if not tk:
        log("缺少 tk")
        return 2

    url = caps_url(maptype, tk, sub)
    log("URL = %s" % url)
    mods = load_types()
    try:
        ok = try_build(mods["esriCarto.olb"], mods["esriGISClient.olb"],
                       mods["esriSystem.olb"], url, maptype, maptype, out)
    except Exception:
        log("EXC:\n" + traceback.format_exc())
        return 1
    log("RESULT: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
