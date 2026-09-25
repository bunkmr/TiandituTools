# -*- coding: utf-8 -*-
"""开发期验证脚本：打包 -> 安装 -> 启动 ArcMap -> 记录退出码与稳定性。

用法:
    python dev_test_addin.py                # 用当前 TiandituTools.esriaddin 直接测
    python dev_test_addin.py hidden 150     # 先按 TIANDITU_VARIANT=hidden 重新打包再测

判定标准：
    * 退出码 0 且一直存活 = 好
    * 存活到超时 = 好
    * 提前退出（无论退出码）= 有问题
"""
from __future__ import print_function

import datetime
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "TiandituTools.esriaddin")
GUID = "{A1B2C3D4-1234-5678-9ABC-DEF012345678}"
ADDINS = r"C:\Users\bunkr\Documents\ArcGIS\AddIns\Desktop10.4"
CACHE = r"C:\Users\bunkr\AppData\Local\ESRI\Desktop10.4\AssemblyCache"
BAK = os.path.join(ROOT, "_addin_removed_backup")
ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
LOG = os.path.join(os.environ.get("APPDATA", ""), "TiandituTools", "import_error.log")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True).stdout.decode("gbk", "replace")


def main():
    variant = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    wait_s = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    if variant:
        env = dict(os.environ)
        env["TIANDITU_VARIANT"] = variant
        print("== 按变体重新打包: TIANDITU_VARIANT=%s ==" % variant)
        r = subprocess.run([sys.executable, "build_addin.py"], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-300:])

    print("\n== 清理并安装 ==")
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(3)
    stamp = time.strftime("%H%M%S")
    for base in (ADDINS, CACHE):
        p = os.path.join(base, GUID)
        if os.path.exists(p):
            b = os.path.join(BAK, "rt_%s_%s_%s" % (os.path.basename(base), GUID, stamp))
            shutil.move(p, b)
            print("  备份移走:", p, "->", b)
    os.makedirs(os.path.join(ADDINS, GUID), exist_ok=True)
    shutil.copy2(OUT, os.path.join(ADDINS, GUID, "TiandituTools.esriaddin"))
    if os.path.exists(LOG):
        os.remove(LOG)

    print("\n== 启动 ArcMap，观测 %d 秒 ==" % wait_s)
    t0 = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(ROOT, "_t0.txt"), "w") as f:
        f.write(t0)
    print("  测试起点:", t0)

    p = subprocess.Popen([ARCMAP], creationflags=0x00000008)
    t = 0
    rc = None
    while t < wait_s:
        time.sleep(1)
        t += 1
        rc = p.poll()
        if rc is not None:
            break

    print("\n== 结果 ==")
    if rc is None:
        print("  [OK] %ds 内一直运行，未退出" % wait_s)
    else:
        print("  [问题] 在 %ds 退出，退出码 = %s (0x%X)" % (t, rc, rc & 0xFFFFFFFF))
    print("  插件是否被导入:", os.path.exists(LOG))
    if os.path.exists(LOG):
        print("   ", open(LOG, "rb").read().decode("utf-8", "replace").strip())
    gc = os.path.join(CACHE, GUID)
    print("  AssemblyCache 入口文件:",
          os.listdir(gc) if os.path.isdir(gc) else "(未生成)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
