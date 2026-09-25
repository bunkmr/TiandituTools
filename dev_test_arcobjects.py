# -*- coding: utf-8 -*-
"""端到端验证 TiandituTools/arcobjects.py（在 ArcMap 之外驱动，用 AppROT 找目标）"""
from __future__ import print_function

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "TiandituTools"))

TK = "215a6b9d9f7cba63e8e128dfb4042419"


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def main():
    import arcobjects

    log("com_dir   = %s" % arcobjects.com_dir())
    log("is_cached = %s" % arcobjects.is_cached())
    log("available = %s" % arcobjects.available())
    if not arcobjects.available():
        log("不可用：%s" % arcobjects.get_last_error())
        return 1

    try:
        m0 = arcobjects.current_map()
        log("current_map = %r" % (m0,))
        if m0 is None:
            log("没有地图")
            return 1
        log("   Name=%r LayerCount=%r" % (m0.Name, m0.LayerCount))
        before = m0.LayerCount
    except Exception:
        log("取地图失败:\n" + traceback.format_exc())
        return 1

    try:
        arcobjects.add_wmts(
            "https://t3.tianditu.gov.cn/img_w/wmts?"
            "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s" % TK,
            u"\u5929\u5730\u56fe-\u5f71\u50cf\u5730\u56fe",
        )
        log("add_wmts OK")
    except Exception:
        log("add_wmts 失败:\n" + traceback.format_exc())
        return 1

    m = arcobjects.current_map()
    log("加入后 LayerCount = %r (before=%r)" % (m.LayerCount, before))
    try:
        for i in range(m.LayerCount):
            l = m.Layer[i]
            log("    [%d] %r" % (i, getattr(l, "Name", "?")))
    except Exception:
        log("枚举失败:\n" + traceback.format_exc())

    # 顺带验证第二层（注记）与组顺序
    try:
        arcobjects.add_wmts(
            "https://t3.tianditu.gov.cn/cia_w/wmts?"
            "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0&tk=%s" % TK,
            u"\u5929\u5730\u56fe-\u5f71\u50cf\u6ce8\u8bb0",
            extra=None,
        )
        log("第二个图层 OK")
    except Exception:
        log("第二个图层失败:\n" + traceback.format_exc())

    m = arcobjects.current_map()
    log("最终 LayerCount = %r" % m.LayerCount)
    for i in range(m.LayerCount):
        try:
            log("    [%d] %r" % (i, m.Layer[i].Name))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
