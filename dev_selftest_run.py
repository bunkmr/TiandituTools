# -*- coding: utf-8 -*-
"""驱动「in-process 自检」：带 TIANDITU_SELFTEST 启动 ArcMap，等它自己跑完。

自检代码跑在 ArcMap 主线程上（见 TiandituTools/dev_selftest.py），
所以这里只负责：清场 → 启动 → 盯日志 → 截图 → 汇总。

用法：<py27> dev_selftest_run.py [等待秒] [maptypes]
"""
from __future__ import print_function, unicode_literals

import io
import os
import subprocess
import sys
import time

sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dev_e2e_run as E                       # noqa: E402  复用 log/shot/alive

ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
SELFTEST_LOG = os.path.join(os.environ.get("APPDATA") or "", "TiandituTools",
                            "selftest.log")

#: 设 TIANDITU_NOSHOT=1 关掉 PrintWindow 截图。
#: 为什么需要这个开关：PrintWindow 会让 ArcMap 在**窗口过程里同步重绘**，
#: 而 WMTS 绘制要取瓦片，等于把 ArcMap 主线程按在那里 —— 实测一截图，
#: 自检的定时器回调就整段停摆上百秒，把后面的步骤全堵死。
#: 现在自检自己用 IActiveView.Draw 渲染到位图（见 dev_selftest._draw_to_bmp），
#: 不再需要外部截图。
NOSHOT = bool(os.environ.get("TIANDITU_NOSHOT"))


def tail(path, n=40):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return lines[-n:]
    except Exception as e:
        return ["(读不到 %s: %r)" % (path, e)]


def main():
    wait_s = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    maptypes = sys.argv[2] if len(sys.argv) > 2 else "img,cia"

    E.log("=== 清场 ===")
    for pid in E.arcmap_pids():
        subprocess.call(["taskkill", "/F", "/PID", pid],
                        creationflags=E.CREATE_NO_WINDOW)
    time.sleep(2)

    try:
        if os.path.isfile(SELFTEST_LOG):
            os.remove(SELFTEST_LOG)
    except Exception:
        pass

    # py2 的 subprocess 要求 env 里**全是 str（bytes）**，不能有 unicode
    # （本模块开了 unicode_literals，所以键名默认是 unicode，必须显式转回）
    env = {}
    for k, v in os.environ.items():
        env[str(k)] = str(v)
    env[str("TIANDITU_SELFTEST")] = str(maptypes)
    env[str("TIANDITU_NO_UI")] = str("1")
    E.log("=== 启动 ArcMap（TIANDITU_SELFTEST=%s）===" % maptypes)
    proc = subprocess.Popen([ARCMAP], env=env,
                            creationflags=E.CREATE_NEW_CONSOLE, close_fds=True)
    E.log("pid=%d" % proc.pid)

    t0 = time.time()
    last = 0
    while time.time() - t0 < wait_s:
        time.sleep(5)
        el = int(time.time() - t0)
        up = E.alive(proc.pid)
        lines = tail(SELFTEST_LOG, 200)
        if len(lines) > last:
            for ln in lines[last:]:
                E.log("  | " + ln)
            last = len(lines)
        if el % 30 < 5:
            E.log("  ...t=%ds alive=%s selftest 行数=%d" % (el, up, len(lines)))
            if not NOSHOT:
                E.shot("ST%03d" % el)
        if not up:
            E.log("!!! ArcMap 已死亡（t=%ds）" % el)
            break
        if any("结束：tiles=" in ln or "异常过多" in ln or "放弃" in ln
               for ln in lines):
            E.log("  自检已收尾，再等 8s%s" % ("" if NOSHOT else " 抓最后一张图"))
            time.sleep(8)
            if not NOSHOT:
                E.shot("ST_end")
            break

    E.log("=== selftest.log 全文 ===")
    for ln in tail(SELFTEST_LOG, 200):
        E.log("  | " + ln)
    E.log("=== import_error.log 末 20 行 ===")
    ip = os.path.join(os.environ.get("APPDATA") or "", "TiandituTools",
                      "import_error.log")
    for ln in tail(ip, 20):
        E.log("  | " + ln)
    E.log("=== ArcMap 存活=%s ===" % E.alive(proc.pid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
