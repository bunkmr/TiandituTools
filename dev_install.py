# -*- coding: utf-8 -*-
"""把 TiandituTools.esriaddin 安装到 ArcGIS 官方 well-known 目录（仅安装，不启动 ArcMap）。

等价于"双击 .esriaddin -> Install Add-In"的落盘动作：
    Documents\\ArcGIS\\AddIns\\Desktop10.4\\<AddInID>\\TiandituTools.esriaddin
ArcMap 下次启动时会把它解包到
    %LOCALAPPDATA%\\ESRI\\Desktop10.4\\AssemblyCache\\<AddInID>\\

安全策略：只做**可还原的移动**（带时间戳备份到 _addin_removed_backup），
不做任何删除。用法：python dev_install.py
"""
from __future__ import print_function

import os
import shutil
import subprocess
import time

ROOT = r"D:\Work\projects\arcmap"
OUT = os.path.join(ROOT, "TiandituTools.esriaddin")
GUID = "{A1B2C3D4-1234-5678-9ABC-DEF012345678}"
ADDINS = r"C:\Users\bunkr\Documents\ArcGIS\AddIns\Desktop10.4"
CACHE = r"C:\Users\bunkr\AppData\Local\ESRI\Desktop10.4\AssemblyCache"
BAK = os.path.join(ROOT, "_addin_removed_backup")
LOG = os.path.join(os.environ.get("APPDATA", ""), "TiandituTools", "import_error.log")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True).stdout.decode("gbk", "replace")


def main():
    if not os.path.isfile(OUT):
        print("ERROR: 缺少", OUT)
        return 1
    print("包: %s (%d bytes)" % (OUT, os.path.getsize(OUT)))

    print("\n== 停止 ArcMap ==")
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(2)
    print("   remaining:", "ArcMap.exe" in sh(["tasklist", "/FI", "IMAGENAME eq ArcMap.exe"]))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(BAK, exist_ok=True)
    print("\n== 移走旧安装（可还原）==")
    for base in (ADDINS, CACHE):
        p = os.path.join(base, GUID)
        if os.path.exists(p):
            dst = os.path.join(BAK, "%s_%s_%s"
                               % (os.path.basename(base), GUID, stamp))
            shutil.move(p, dst)
            print("   moved:", p, "->", dst)
        else:
            print("   (不存在)", p)

    print("\n== 安装 ==")
    dst_dir = os.path.join(ADDINS, GUID)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "TiandituTools.esriaddin")
    shutil.copy2(OUT, dst)
    print("   ->", dst, "(%d bytes)" % os.path.getsize(dst))

    if os.path.exists(LOG):
        os.remove(LOG)
        print("   旧诊断日志已清理")

    print("\n== 结果 ==")
    print("   AddIns\\%s : %s" % (GUID, sorted(os.listdir(dst_dir))))
    gc = os.path.join(CACHE, GUID)
    print("   AssemblyCache\\%s : %s"
          % (GUID, sorted(os.listdir(gc)) if os.path.isdir(gc) else "(下次启动 ArcMap 时生成)"))
    print("\n启动 ArcMap 后：自定义(Customize) -> 工具条(Toolbars) -> 勾选「天地图 Tools」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
