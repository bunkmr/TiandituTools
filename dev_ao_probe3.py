# -*- coding: utf-8 -*-
"""快速判定：ArcObjects 组件类是否支持 IDispatch（决定 win32com 后期绑定能否用）"""
from __future__ import print_function

import sys

import pythoncom

PIDS = [
    "esriCarto.WMTSLayer",
    "esriCarto.WMTSLayerFactory",
    "esriCarto.LayerFile",
    "esriCarto.WMSLayer",
    "esriGISClient.WMTSConnection",
    "esriGISClient.WMTSConnectionFactory",
    "esriCatalogUI.GxWMTSConnectionFactory",
    "esriCatalogUI.GxWMTSConnection",
    "esriSystem.Array",
]


def main():
    pythoncom.CoInitialize()
    for pid in PIDS:
        sys.stdout.write("== %s\n" % pid)
        sys.stdout.flush()
        try:
            clsid = pythoncom.CLSIDFromProgID(pid)
        except Exception as e:
            sys.stdout.write("   ProgID 未注册: %s\n" % (str(e)[:80],))
            sys.stdout.flush()
            continue
        sys.stdout.write("   clsid=%s\n" % clsid)
        sys.stdout.flush()
        try:
            unk = pythoncom.CoCreateInstance(clsid, None, pythoncom.CLSCTX_ALL,
                                             pythoncom.IID_IUnknown)
        except Exception as e:
            sys.stdout.write("   CoCreateInstance 失败: %s\n" % (str(e)[:120],))
            sys.stdout.flush()
            continue
        sys.stdout.write("   IUnknown OK -> %r\n" % (unk,))
        sys.stdout.flush()
        try:
            disp = unk.QueryInterface(pythoncom.IID_IDispatch)
            sys.stdout.write("   >>> IDispatch 支持 OK\n")
            try:
                ti = disp.GetTypeInfo()
                sys.stdout.write("       GetTypeInfo -> %r\n" % (ti,))
            except Exception as e:
                sys.stdout.write("       GetTypeInfo 失败 %s\n" % (str(e)[:80],))
        except Exception as e:
            sys.stdout.write("   >>> IDispatch 不支持: %s\n" % (str(e)[:100],))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
