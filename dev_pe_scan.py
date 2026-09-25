# -*- coding: utf-8 -*-
"""扫描 ArcGIS 安装目录，找出哪些模块引用了 DFORRT.DLL（Fortran 运行时）。

只做只读扫描。逐文件分块读，命中即停，避免大文件拖慢。
"""
from __future__ import print_function

import os
import sys
import time

ROOTS = [
    r"C:\Program Files (x86)\ArcGIS\Desktop10.4",
]
NEEDLES = (b"DFORRT", b"dforrt")
EXTS = (".dll", ".exe", ".pyd", ".ocx", ".olb")
MAX_BYTES = 80 * 1024 * 1024      # 跳过超大文件
CHUNK = 1 << 20


def hits(path):
    try:
        size = os.path.getsize(path)
    except Exception:
        return False
    if size > MAX_BYTES:
        return None               # 跳过
    try:
        with open(path, "rb") as f:
            prev = b""
            while True:
                buf = f.read(CHUNK)
                if not buf:
                    return False
                data = prev + buf
                for n in NEEDLES:
                    if n in data:
                        return True
                prev = buf[-16:]
    except Exception:
        return False


def main():
    found = []
    skipped = []
    scanned = 0
    t0 = time.time()
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.lower().endswith(EXTS):
                    continue
                p = os.path.join(dirpath, fn)
                r = hits(p)
                scanned += 1
                if r is True:
                    found.append(p)
                    print("  [命中] %s" % p)
                    sys.stdout.flush()
                elif r is None:
                    skipped.append(p)
                if scanned % 200 == 0:
                    print("  ... 已扫描 %d 个文件，用时 %.1fs"
                          % (scanned, time.time() - t0))
                    sys.stdout.flush()
    print()
    print("=== 结果 ===")
    print("扫描文件数: %d，用时 %.1fs" % (scanned, time.time() - t0))
    print("引用 DFORRT 的模块数: %d" % len(found))
    for p in found:
        print("   %s" % p)
    print("跳过的超大文件数: %d" % len(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
