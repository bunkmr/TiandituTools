# -*- coding: utf-8 -*-
"""第二阶段探针：AppROT 找 ArcMap + 生成 esriCarto/esriGISClient 类型库模块并列出 WMTS 接口成员"""
from __future__ import print_function

import os
import sys

COM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"


def hr(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


def app_rot():
    hr("1. esriFramework.AppROT -> ArcMap")
    import win32com.client

    for pid in ("esriFramework.AppROT", "esriFramework.AppROTClass",
                "esriArcMap.Application", "esriArcMapUI.MxApplication"):
        try:
            rot = win32com.client.Dispatch(pid)
        except Exception as e:
            print("  NO  Dispatch(%s) <%s>" % (pid, str(e)[:90]))
            continue
        print("  OK  Dispatch(%s) -> %r" % (pid, rot))
        try:
            n = rot.Count
            print("      Count = %r" % n)
        except Exception as e:
            print("      .Count 失败 %r" % (e,))
            continue
        for i in range(n):
            try:
                app = rot.Item(i)
                nm = ""
                try:
                    nm = app.Name
                except Exception:
                    pass
                print("      [%d] app=%r Name=%r" % (i, app, nm))
                try:
                    doc = app.Document
                    print("          Document=%r" % (doc,))
                    try:
                        fm = doc.FocusMap
                        print("          FocusMap=%r  Name=%r LayerCount=%r"
                              % (fm, getattr(fm, "Name", None), getattr(fm, "LayerCount", None)))
                    except Exception as e2:
                        print("          FocusMap 失败 %r" % (e2,))
                except Exception as e2:
                    print("          .Document 失败 %r" % (e2,))
            except Exception as e:
                print("      Item(%d) 失败 %r" % (i, e))
        return


def gen_modules():
    hr("2. 生成类型库模块并列出成员")
    import pythoncom
    import win32com.client.gencache as gencache

    try:
        gencache.is_readonly = False
    except Exception:
        pass

    for olb, want in (
        ("esriCarto.olb", ("IWMTSLayer", "WMTSLayer", "WMTSLayerFactory", "ILayer")),
        ("esriGISClient.olb", ("IWMTSConnection", "WMTSConnection",
                               "IWMTSConnectionFactory", "WMTSConnectionFactory",
                               "IWMTSServiceDescription")),
    ):
        path = os.path.join(COM, olb)
        if not os.path.isfile(path):
            print("  %s 不存在" % olb)
            continue
        try:
            tl = pythoncom.LoadTypeLib(path)
            la = tl.GetLibAttr()
            guid = str(la[0])
            major, minor = la[3], la[4]
            print("\n--- %s  guid=%s ver=%d.%d ---" % (olb, guid, major, minor))
        except Exception as e:
            print("  %s 读类型库失败 %r" % (olb, e))
            continue
        try:
            mod = gencache.EnsureModule(guid, 0, major, minor)
        except Exception as e:
            print("  EnsureModule 失败 %r" % (e,))
            continue
        print("  模块: %s" % mod.__file__)
        for name in want:
            cls = getattr(mod, name, None)
            if cls is None:
                print("    %-26s (无)" % name)
                continue
            meths = sorted(m[1] for m in getattr(cls, "_methods_", []))
            getters = sorted((getattr(cls, "_prop_map_get_", {}) or {}).keys())
            setters = sorted((getattr(cls, "_prop_map_put_", {}) or {}).keys())
            print("    %-26s" % name)
            print("        方法: %s" % (", ".join(meths) or "-"))
            print("        读属性: %s" % (", ".join(getters) or "-"))
            print("        写属性: %s" % (", ".join(setters) or "-"))


def main():
    print("py=%s" % sys.version)
    import pythoncom
    pythoncom.CoInitialize()
    app_rot()
    gen_modules()


if __name__ == "__main__":
    main()
