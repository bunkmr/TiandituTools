# -*- coding: utf-8 -*-
"""校验 tile_proxy 的两个关键修复：
  1. 改写后的 xlink:href 必须以 `&` 结尾（否则 ArcMap 拼 GetTile 会粘连）；
  2. 复现 ArcMap 原样发出的查询串，确认规整后能真正取到瓦片。
"""
from __future__ import print_function, unicode_literals

import io
import sys

sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "TiandituTools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tile_proxy as tp                                   # noqa: E402
from config import get_key                                # noqa: E402

KEY = get_key()
print(u"key = %s..." % KEY[:8])
tp.start(key=KEY, prefer_port=18077)

# --- 1) href 必须以便 & 结尾 ---------------------------------------------
_ctype, body = tp._fetch("/cva_w/wmts",
                         u"SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0")
fixed = tp.rewrite_capabilities(body, u"http://127.0.0.1:18077", KEY)
hrefs = sorted(set(tp._HREF_RE.findall(fixed)))
for h in hrefs:
    print(u"href: %s" % h)
tile_hrefs = [h for h in hrefs if u"/t" in h and u"tianditu.gov.cn" not in h]
assert tile_hrefs, hrefs
# ServiceProvider 里那个 www.tianditu.gov.cn 是联系方式，不是瓦片端点，不该动
assert any(h == u"http://www.tianditu.gov.cn" for h in hrefs), hrefs
bad = [h for h in tile_hrefs if not h.endswith(u"&")]
print(u"href 结尾检查: %s" % (u"全部以 & 结尾 ✓" if not bad else u"有问题 %s" % bad))
assert not bad

# --- 2) 复现 ArcMap 原样发出的查询串 ------------------------------------
raw = (u"tk=%sservice=WMTS&request=GetTile&version=1.0.0&layer=cva"
       u"&style=default&format=&TileMatrixSet=w"
       u"&TileMatrix=1&TileRow=0&TileCol=0" % KEY)
q = tp._normalize_tile_query(raw, KEY)
print(u"\n原始 : %s" % raw)
print(u"规整 : %s" % q)
assert u"tk=%s&service=WMTS" % KEY in q, q
assert u"FORMAT=tiles" in q, q
assert u"format=" not in q

# 多打几发，确认不是偶发
ok = 0
for tm, row, col in ((1, 0, 0), (1, 0, 1), (2, 1, 1), (5, 10, 20), (10, 400, 800)):
    qq = tp._normalize_tile_query(
        raw.replace(u"TileMatrix=1", u"TileMatrix=%d" % tm)
           .replace(u"TileRow=0", u"TileRow=%d" % row)
           .replace(u"TileCol=0", u"TileCol=%d" % col), KEY)
    try:
        ct, b = tp._fetch("/t0/cva_w/wmts", qq)
        mark = u"OK " if b[:3] in (b"\xff\xd8\xff",) or b[:4] == b"\x89PNG" \
            else u"?  "
        print(u"  %s z=%d row=%d col=%d -> %s %d 字节 %r"
              % (mark, tm, row, col, ct, len(b), b[:4]))
        if mark.strip() == "OK":
            ok += 1
    except Exception as e:
        print(u"  ERR z=%d row=%d col=%d -> %r" % (tm, row, col, e))

print(u"\n成功 %d/5" % ok)
tp.stop()
print(u"统计：%s" % tp.stats())
print(u"OK")
