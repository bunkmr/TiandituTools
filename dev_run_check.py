# -*- coding: utf-8 -*-
"""启动 ArcMap -> 验证加载项 -> 打开工具条 -> 截图 -> 优雅退出（开发工具）。

为什么值得跑这一趟：config.xml 里声明了 5 个 Button、Images/ 里也有 5 张
图标，但"声明对"和"ArcMap 真的能把它们实例化出来"是两件事 ——
类名写错、图标路径写错、__all__ 漏写，都只有在 ArcMap 里加载一次才会暴露。
（之前就踩过：Toolbar 写 class= 属性会让工厂去解析不存在的类。）

用法：python dev_run_check.py
"""

from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "TiandituTools")
APP = os.environ.get("APPDATA", "")
LOG = os.path.join(APP, "TiandituTools", "import_error.log")

ARCMAP = [
    r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe",
    r"C:\Program Files\ArcGIS\Desktop10.4\bin\ArcMap.exe",
]
PY2 = [
    r"C:\Python27\ArcGIS10.4\python.exe",
    r"C:\Python27\ArcGIS10.10\python.exe",
    r"C:\Python27\python.exe",
]

u32 = ctypes.windll.user32
u32.SetProcessDPIAware()


def first(paths):
    for p in paths:
        if os.path.isfile(p):
            return p
    return None


def windows(substr):
    out = []

    def cb(h, _l):
        n = u32.GetWindowTextLengthW(h)
        if n and u32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            if substr in buf.value:
                rc = wintypes.RECT()
                u32.GetWindowRect(h, ctypes.byref(rc))
                out.append((h, buf.value, rc.left, rc.top, rc.right, rc.bottom))
        return True

    u32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return out


def wait_for(substr, timeout):
    end = time.time() + timeout
    while time.time() < end:
        ws = windows(substr)
        if ws:
            return ws[0]
        time.sleep(1.0)
    return None


def run(args, cwd, timeout=180):
    print("  $ %s" % " ".join(os.path.basename(a) for a in args))
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("    (超时)")
        return ""
    txt = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    for line in (txt + err).splitlines():
        if "sitecustomize" in line:
            continue
        print("    " + line)
    return txt


def tail_log(path, n=40):
    if not os.path.isfile(path):
        return "(没有日志文件)"
    with open(path, "rb") as f:
        lines = f.read().decode("utf-8", "replace").splitlines()
    return u"\n".join(lines[-n:])


def main():
    exe = first(ARCMAP)
    py2 = first(PY2)
    if not exe or not py2:
        print("找不到 ArcMap.exe 或 ArcGIS Python 2.7")
        return 1
    print("ArcMap: %s" % exe)
    print("python2: %s" % py2)

    if os.path.isfile(LOG):
        os.remove(LOG)

    print("\n== 启动 ArcMap ==")
    subprocess.Popen([exe], cwd=os.path.dirname(exe))
    win = wait_for("ArcMap", 180)
    if not win:
        print("  等不到 ArcMap 窗口")
        return 2
    print("  窗口出现: %r" % win[1])

    # 等加载项加载 + 初始地图就绪。不用精确值，日志里有时间戳可对照。
    print("  等 35 秒让加载项与初始文档就绪 …")
    time.sleep(35)

    print("\n== 检查加载项 / 打开工具条 ==")
    run([py2, os.path.join(HERE, "dev_check_addin.py")], HERE)

    print("\n== 加载项日志（尾部）==")
    print(tail_log(LOG, 30))

    print("\n== 优雅退出 ArcMap ==")
    run([py2, os.path.join(HERE, "dev_quit_arcmap.py")], HERE, timeout=90)
    end = time.time() + 60
    while time.time() < end and windows("ArcMap"):
        time.sleep(2)
    left = windows("ArcMap")
    if left:
        print("  仍在运行，强制结束")
        subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"],
                       capture_output=True)
    else:
        print("  已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
