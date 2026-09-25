# -*- coding: utf-8 -*-
"""实验：外部进程加好图层后**保持存活**，观察 ArcMap 是否稳定；
然后本进程退出，再观察 ArcMap 是否因为「图层对象在别的进程里」而崩。

结论用于决定：底图到底该在外部进程加（不阻塞 ArcMap），
还是必须在 ArcMap 进程内加（图层对象必须活在 ArcMap 里）。
"""
from __future__ import print_function

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "TiandituTools"))

HOLD = int(os.environ.get("HOLD_SECONDS", "70"))


def log(*a):
    import datetime
    sys.stdout.write("[%s] %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"),
                                    " ".join(str(x) for x in a)))
    sys.stdout.flush()


def main():
    import arcobjects
    import layer_manager as lm

    if not lm.ao_ready():
        log("ArcObjects 不可用：%s" % arcobjects.get_last_error())
        return 1

    log("添加 影像地图 ...")
    log("apply_basemap -> %s" % lm.apply_basemap({"kind": "maptype", "maptype": "img"}))

    m = arcobjects.current_map()
    log("当前 LayerCount = %s" % (m.LayerCount if m else None))

    log("本进程保持存活 %ds（模拟界面窗口一直开着）..." % HOLD)
    for i in range(HOLD):
        time.sleep(1)
        if i % 10 == 9:
            mm = arcobjects.current_map()
            log("  t=%ds ArcMap=%s LayerCount=%s"
                % (i + 1, "alive" if mm else "GONE", mm.LayerCount if mm else "-"))
    log("本进程即将退出（观察 ArcMap 是否会因为代理对象消失而崩）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
