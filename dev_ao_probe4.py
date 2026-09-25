# -*- coding: utf-8 -*-
"""第四阶段：用 comtypes 生成 ArcObjects 类型库，列出 WMTS 相关接口的准确方法名"""
from __future__ import print_function

import os
import sys
import traceback

GISCOM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"

# 顺序很重要：依赖的先来
OLBS = ["esriSystem.olb", "esriGISClient.olb", "esriCarto.olb",
        "esriCatalog.olb", "esriCatalogUI.olb", "esriGeoDatabase.olb"]

WANT = ["IWMTSServiceDescription", "IWMTSConnection", "IWMTSConnectionName",
        "IWMTSConnectionFactory", "IWMTSLayer", "IWMTSLayerDescription",
        "ILayerFile", "ILayer", "IName", "IWMTSLayerFactory"]


def flush(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def members(cls):
    """把 comtypes 生成类的 _methods_ 摊平成人能读的形式"""
    out = []
    for m in getattr(cls, "_methods_", []):
        name = getattr(m, "name", None)
        if not name:
            continue
        kind = "M"
        if name.startswith("Get") or name.startswith("_get"):
            kind = "get"
        elif name.startswith("Put") or name.startswith("_set"):
            kind = "set"
        args = getattr(m, "argtypes", None)
        out.append((name, kind, args))
    return out


def main():
    import comtypes
    import comtypes.client

    flush("comtypes %s" % comtypes.__version__)

    mods = {}
    for f in OLBS:
        p = os.path.join(GISCOM, f)
        if not os.path.isfile(p):
            flush("!! 缺 %s" % f)
            continue
        flush("GetModule %s ..." % f)
        try:
            mods[f] = comtypes.client.GetModule(p)
            flush("   OK -> %s" % getattr(mods[f], "__file__", "?"))
        except Exception:
            flush("   FAIL:\n" + traceback.format_exc())

    flush("\n" + "=" * 72)
    flush("接口方法清单")
    flush("=" * 72)
    for m in mods.values():
        for name in WANT:
            cls = getattr(m, name, None)
            if cls is None:
                continue
            flush("\n--- %s  (from %s) ---" % (name, os.path.basename(m.__file__)))
            for n, kind, args in members(cls):
                a = ""
                if args:
                    try:
                        a = "  " + ", ".join(str(getattr(t, "__name__", t)) for t in args)
                    except Exception:
                        a = "  ?"
                flush("    [%-3s] %s%s" % (kind, n, a))

    flush("\n" + "=" * 72)
    flush("试创建组件类")
    flush("=" * 72)
    for pid in ("esriCarto.WMTSLayer", "esriCarto.LayerFile",
                "esriGISClient.WMTSConnection", "esriGISClient.WMTSConnectionFactory"):
        try:
            o = comtypes.client.CreateObject(pid)
            flush("  OK  %-38s -> %r" % (pid, o))
        except Exception as e:
            flush("  NO  %-38s <%s: %s>" % (pid, type(e).__name__, str(e)[:120]))


if __name__ == "__main__":
    main()
