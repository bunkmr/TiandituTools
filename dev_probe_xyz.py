# -*- coding: utf-8 -*-
"""批量探测内置 XYZ 图源的可用性（开发工具，不随插件发布）。

    python dev_probe_xyz.py            # 全部
    python dev_probe_xyz.py 开源        # 只测名字里含关键字的
"""

from __future__ import print_function

import io
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "TiandituTools"))

import xyz_sources as X      # noqa: E402

class _Out(object):
    """既能吃 str 也能吃 unicode 的 stdout。

    py2 里 io.open(1,'w') 是一个 TextIOWrapper，只收 unicode；而
    print_function 补的那个换行、以及各种 % 出来的 byte str 都是 str，
    一写就 TypeError('must be unicode, not str')。所以自己包一层。
    """
    def __init__(self, f):
        self.f = f

    def write(self, s):
        if not isinstance(s, bytes):
            s = s.encode("utf-8", "replace")
        self.f.write(s)

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass


sys.stdout = _Out(io.open(1, "wb", closefd=False))

# 命令行参数在 Windows 控制台是 GBK 字节串，跟 unicode 图源名比较会炸
kw = sys.argv[1].decode("mbcs", "ignore") if len(sys.argv) > 1 else u""
items = [i for i in X.sources() if (not kw or kw in i["name"] or kw in i["group"])]
print("探测 %d 个图源（关键字=%r）\n" % (len(items), kw))

results = []
lock = threading.Lock()


def work(it):
    try:
        ok, msg = X.probe(it, timeout=10)
    except Exception as e:
        ok, msg = False, "异常 %r" % (e,)
    with lock:
        results.append((ok, it, msg))
        mark = "OK  " if ok else "FAIL"
        first = msg.split("\n")[0]
        print(u"%-4s %-34s %s" % (mark, it["name"], first))


threads = []
for it in items:
    t = threading.Thread(target=work, args=(it,))
    t.daemon = True
    t.start()
    threads.append(t)
for t in threads:
    t.join()

okn = len([r for r in results if r[0]])
print("\n合计: %d 可用 / %d 失败 / 共 %d" % (okn, len(results) - okn, len(results)))
bad = [r for r in results if not r[0]]
if bad:
    print("\n失败明细:")
    for _ok, it, msg in bad:
        print(u"  · %s\n      %s\n      %s" % (it["name"], it["url"], msg.replace("\n", "\n      ")))
