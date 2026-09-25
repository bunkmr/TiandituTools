# -*- coding: utf-8 -*-
"""轮询 AppROT / GetActiveObject，观察 ArcMap 启动过程中什么时候能被外部进程抓到。

必须用 32 位 ArcGIS Python 运行（C:\\Python27\\ArcGIS10.4\\python.exe）。
"""
from __future__ import print_function

import os
import sys
import time
import traceback
from datetime import datetime

GISCOM = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\com"


def log(*a):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"),
                       " ".join(str(x) for x in a)))
    sys.stdout.flush()


def main():
    import comtypes.client
    from comtypes.client import GetModule

    mods = {}
    for f in ("esriSystem.olb", "esriGISClient.olb", "esriCarto.olb",
              "esriFramework.olb", "esriArcMapUI.olb"):
        p = os.path.join(GISCOM, f)
        if os.path.isfile(p):
            try:
                mods[f] = GetModule(p)
            except Exception as e:
                log("GetModule %s 失败 %r" % (f, e))
    fw = mods.get("esriFramework.olb")
    if fw is None:
        log("esriFramework 未加载")
        return 1

    # 预创建（避免把首次生成时间算进轮询）
    try:
        probe = comtypes.client.CreateObject("esriFramework.esriAppROT",
                                             interface=fw.IAppROT)
        log("AppROT 对象创建成功: %r" % (probe,))
    except Exception:
        log("AppROT 创建失败:\n" + traceback.format_exc())
        probe = None

    t0 = time.time()
    while time.time() - t0 < 100:
        el = time.time() - t0
        import comtypes.client as cc

        # 1) AppROT
        try:
            rot = cc.CreateObject("esriFramework.esriAppROT",
                                  interface=fw.IAppROT)
            n = rot.Count
            detail = ""
            if n:
                try:
                    app = rot.Item(0)
                    detail = " Caption=%r Name=%r" % (
                        getattr(app, "Caption", "?"), getattr(app, "Name", "?"))
                except Exception as e:
                    detail = " Item(0) 失败 %r" % (e,)
            log("t=%5.1fs AppROT.Count=%s%s" % (el, n, detail))
        except Exception as e:
            log("t=%5.1fs AppROT 失败 %r" % (el, e))

        # 2) GetActiveObject 两条 ProgID
        for pid in ("esriArcMap.Application", "esriFramework.esriAppROT"):
            try:
                o = cc.GetActiveObject(pid)
                log("t=%5.1fs GetActiveObject(%s) -> %r" % (el, pid, o))
            except Exception as e:
                log("t=%5.1fs GetActiveObject(%s) 失败 %s: %s"
                    % (el, pid, type(e).__name__, str(e)[:80]))
        time.sleep(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
