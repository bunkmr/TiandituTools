# -*- coding: utf-8 -*-
"""端到端验证**新版**代码路径：外部进程直接调用 layer_manager.apply_basemap。

这条路径就是「点『添加底图』→ 界面进程自己把图层加进正在运行的 ArcMap」。
必须在 ArcMap 已运行时、用 32 位 ArcGIS Python 执行。
"""
from __future__ import print_function

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "TiandituTools")
sys.path.insert(0, PKG)


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def dump_map(tag):
    import arcobjects
    m = arcobjects.current_map()
    if m is None:
        log("%s: current_map = None" % tag)
        return
    log("%s: Name=%r LayerCount=%s" % (tag, m.Name, m.LayerCount))
    for i in range(m.LayerCount):
        try:
            log("      [%d] %r" % (i, m.Layer[i].Name))
        except Exception:
            pass


def main():
    try:
        import config
        k = config.get_key() or ""
        log("天地图 Key: %s" % (u"已设置(%d 位)" % len(k) if k else u"未设置"))
    except Exception:
        log("读 Key 失败:\n" + traceback.format_exc())

    import arcobjects
    import layer_manager as lm

    log("com_dir     = %s" % arcobjects.com_dir())
    log("is_cached   = %s" % arcobjects.is_cached())
    log("available   = %s" % arcobjects.available())
    log("ao_ready    = %s" % lm.ao_ready())
    if not lm.ao_ready():
        log("ArcObjects 不可用：%s" % arcobjects.get_last_error())
        return 1

    dump_map("加入前")

    log("--- 添加 影像地图 (img) ---")
    try:
        r = lm.apply_basemap({"kind": "maptype", "maptype": "img"})
        log("   -> %s" % r)
    except Exception:
        log("   抛异常:\n" + traceback.format_exc())

    log("--- 添加 影像注记 (cia) ---")
    try:
        r = lm.apply_basemap({"kind": "maptype", "maptype": "cia"})
        log("   -> %s" % r)
    except Exception:
        log("   抛异常:\n" + traceback.format_exc())

    dump_map("加入后")
    return 0


if __name__ == "__main__":
    sys.exit(main())
