# -*- coding: utf-8 -*-
"""ArcObjects 可达性探针（在 ArcMap 之外运行，验证 COM 通道）

1) 枚举 esriCarto.olb / esriGISClient.olb / esriDataSourcesRaster.olb 里所有含
   WMS / WMTS 的接口与组件类，找出现成的建模入口；
2) 试各种方式拿到正在运行的 ArcMap Application 对象。
"""
from __future__ import print_function

import os
import sys

COM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def dump_typelib(path, keys=("wmts", "wms", "ogc")):
    import pythoncom

    print("\n--- %s ---" % os.path.basename(path))
    try:
        tl = pythoncom.LoadTypeLib(path)
    except Exception as e:
        print("  LoadTypeLib FAIL: %r" % (e,))
        return
    try:
        n = tl.GetTypeInfoCount()
    except Exception as e:
        print("  GetTypeInfoCount FAIL: %r" % (e,))
        return
    print("  类型数: %d" % n)
    libname = ""
    try:
        libname = tl.GetDocumentation(-1)[0]
    except Exception:
        pass
    print("  库名: %r" % libname)

    for i in range(n):
        try:
            doc = tl.GetDocumentation(i)
            name = doc[0] or ""
        except Exception:
            continue
        low = name.lower()
        if not any(k in low for k in keys):
            continue
        kind = "?"
        guid = ""
        try:
            attr = tl.GetTypeInfoAttr(i)
            kind = {0: "enum", 1: "record", 2: "module", 3: "interface",
                    4: "dispinterface", 5: "coclass", 6: "alias",
                    7: "union"}.get(attr.typekind, str(attr.typekind))
            guid = str(attr.guid)
        except Exception as e:
            kind = "err:%r" % (e,)
        print("  [%2d] %-10s %-34s %s" % (i, kind, name, guid))


def try_guid_strings():
    """直接在注册表里找 ProgID，最直观"""
    import winreg

    print("\n--- 注册表 ProgID 里含 WMTS / WMS 的 ---")
    found = []
    for hive, flag in ((winreg.HKEY_CLASSES_ROOT, 0),):
        try:
            k = winreg.OpenKey(hive, "CLSID")
        except Exception as e:
            print("  打不开 CLSID: %r" % (e,))
            return found
    return found


def scan_progids():
    """扫 HKCR 下的子键名（ProgID 就是 HKCR 的子键）"""
    try:
        import winreg
    except ImportError:
        import _winreg as winreg
    hits = []
    try:
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "")
    except Exception as e:
        print("  HKCR 打开失败: %r" % (e,))
        return hits
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(k, i)
        except OSError:
            break
        i += 1
        low = sub.lower()
        if ("wmts" in low or "wms" in low) and "." in sub:
            hits.append(sub)
    return sorted(set(hits))


def try_app():
    print("\n--- 拿 ArcMap Application ---")
    import win32com.client

    for how, fn in (
        ("GetActiveObject", lambda pid: win32com.client.GetActiveObject(pid)),
        ("Dispatch", lambda pid: win32com.client.Dispatch(pid)),
    ):
        for pid in ("esriArcMap.Application", "ArcMap.Application", "esriArcMap.Application.1"):
            try:
                app = fn(pid)
                print("  OK   %-16s %-30s -> %r" % (how, pid, app))
                try:
                    print("       Name = %r" % (app.Name,))
                except Exception as e:
                    print("       .Name 失败: %r" % (e,))
                try:
                    doc = app.Document
                    print("       Document = %r" % (doc,))
                    try:
                        fmap = doc.FocusMap
                        print("       FocusMap = %r  Name=%r" % (fmap, getattr(fmap, "Name", None)))
                        try:
                            print("       FocusMap.LayerCount = %r" % (fmap.LayerCount,))
                        except Exception as e:
                            print("       LayerCount 失败: %r" % (e,))
                    except Exception as e:
                        print("       FocusMap 失败: %r" % (e,))
                except Exception as e:
                    print("       .Document 失败: %r" % (e,))
            except Exception as e:
                print("  NO   %-16s %-30s <%s: %s>" % (how, pid, type(e).__name__, str(e)[:110]))


def main():
    print("pid=%d  python=%s" % (os.getpid(), sys.version))
    try:
        import pythoncom
        pythoncom.CoInitialize()
        print("CoInitialize OK")
    except Exception as e:
        print("CoInitialize FAIL: %r" % (e,))

    hr("1. 注册表 HKCR 里含 WMTS/WMS 的 ProgID")
    for s in scan_progids():
        print("  " + s)

    hr("2. typelib 里的 WMTS/WMS 类型")
    for f in ("esriCarto.olb", "esriGISClient.olb", "esriDataSourcesRaster.olb",
              "esriGeoDatabase.olb", "esriCatalog.olb", "esriArcMap.olb"):
        p = os.path.join(COM, f)
        if os.path.isfile(p):
            dump_typelib(p)
        else:
            print("\n--- %s 不存在 ---" % f)

    hr("3. ArcMap Application")
    try_app()


if __name__ == "__main__":
    main()
