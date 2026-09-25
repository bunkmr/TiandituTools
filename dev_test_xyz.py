# -*- coding: utf-8 -*-
"""XYZ 中转链路自检（开发工具，不随插件发布）。

用一个**真实的中转进程**走完整链路：
    1. 起 tile_server（独立进程，和 ArcMap 走的是同一条路）
    2. 要一份 XYZ 的 capabilities，检查 TileMatrix / ResourceURL / 格网参数
    3. 要一张瓦片，检查真的拿到图片
    4. 要一张地理上有内容的瓦片（北京），并核对字节数
    5. 顺带确认天地图那条老路没被改坏

    python dev_test_xyz.py            # 用内置第一个源
    python dev_test_xyz.py <源名关键字>
"""

from __future__ import print_function

import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "TiandituTools")
sys.path.insert(0, PKG)

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

import tile_proxy                                    # noqa: E402
import xyz_sources                                   # noqa: E402

PY = r"C:\Python27\ArcGIS10.4\python.exe"
PORT = 17899
APPD = os.path.join(os.environ.get("APPDATA") or "", "TiandituTools")


def get(port, path_and_query, timeout=20):
    st, body = tile_proxy._local_get(port, path_and_query, timeout=timeout)
    return st, body


def main():
    # 命令行参数在 Windows 控制台是 GBK 字节串，与 unicode 图源名比较会炸
    kw = sys.argv[1].decode("mbcs", "ignore") if len(sys.argv) > 1 else u""
    items = [i for i in xyz_sources.sources() if not kw or kw in i["name"]]
    if not items:
        print("没有匹配的图源")
        return 1
    ent = items[0]
    print(u"测试图源: %s (%s)" % (ent["name"], ent["id"]))
    print(u"  模板: %s" % ent["url"])
    print(u"  层级: z%d~z%d  datum=%s" % (ent["zmin"], ent["zmax"], ent["datum"]))
    print()

    # --- 起独立中转（和正式路径同一个入口） ---
    dn = open(os.devnull, "rb")
    log = open(os.path.join(HERE, "_xyz_relay.log"), "wb")
    proc = subprocess.Popen([PY, os.path.join(PKG, "tile_server.py"), str(PORT)],
                            cwd=PKG, stdin=dn, stdout=log, stderr=log)
    try:
        ok = False
        for _ in range(40):
            time.sleep(0.4)
            try:
                st, b = get(PORT, "/ping", timeout=2)
                if st == 200 and b.strip() == b"OK":
                    ok = True
                    break
            except Exception:
                pass
        if not ok:
            print("中转没起来，看 _xyz_relay.log")
            return 1
        print(u"中转就绪 127.0.0.1:%d" % PORT)
        print(u"stats: %s" % get(PORT, "/stats")[1][:200])
        print()

        # --- 1. capabilities ---
        caps_q = ("/xyz/%s/esri/wmts?SERVICE=WMTS&REQUEST=GetCapabilities"
                  "&VERSION=1.0.0" % ent["id"])
        st, body = get(PORT, caps_q)
        xml = body.decode("utf-8", "replace")
        print(u"[1] capabilities  HTTP %d  %d 字节" % (st, len(body)))
        checks = [
            (u"含 TileMatrixSet", u"<TileMatrixSet>" in xml),
            (u"含 ResourceURL", u"<ResourceURL" in xml),
            (u"左上角正确(-X +Y)",
             (u"<TopLeftCorner>-%s %s</TopLeftCorner>"
              % (xyz_sources.HALF_WORLD, xyz_sources.HALF_WORLD)) in xml),
            (u"指向本机 127.0.0.1", u"127.0.0.1:%d" % PORT in xml),
        ]
        nmat = xml.count("<TileMatrix>")
        checks.append((u"TileMatrix 数量 = z%d..z%d (%d)"
                       % (ent["zmin"], ent["zmax"], ent["zmax"] - ent["zmin"] + 1),
                       nmat == ent["zmax"] - ent["zmin"] + 1))
        # 第 1 级的 ScaleDenominator 应当等于 559082264.0287178 / 2^zmin
        m = re.search(u"<ows:Identifier>%d</ows:Identifier>\\s*"
                      u"<ScaleDenominator>([0-9.]+)</ScaleDenominator>"
                      % ent["zmin"], xml)
        if m:
            got = float(m.group(1))
            want = xyz_sources.scale_denominator(ent["zmin"])
            checks.append((u"z=%d 比例尺 %.6f（应为 %.6f）" % (ent["zmin"], got, want),
                           abs(got - want) < 1.0))
        else:
            checks.append((u"找到 z=%d 的比例尺" % ent["zmin"], False))
        for name, good in checks:
            print(u"    %s %s" % (u"OK  " if good else u"!!!!", name))

        # --- 2. 瓦片：北京 z=9 ---
        z = int((ent["zmin"] + ent["zmax"]) / 2)
        x, y = xyz_sources.lonlat_to_tile(*xyz_sources.PROBE_LONLAT[:2] + (z,))
        tile_q = ("/xyz/%s/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                  "&LAYER=%s&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles"
                  "&TILEMATRIX=%d&TILEROW=%d&TILECOL=%d"
                  % (ent["id"], ent["id"], z, y, x))
        t0 = time.time()
        st, body = get(PORT, tile_q, timeout=30)
        ms = int((time.time() - t0) * 1000)
        kind = xyz_sources._img_kind(body) or u"?"
        print(u"\n[2] 瓦片 z=%d row=%d col=%d  HTTP %d  %s  %d 字节  %d ms"
              % (z, y, x, st, kind, len(body), ms))
        print(u"    地址: %s" % xyz_sources.tile_url(ent, z, x, y))

        # --- 3. 粘连查询串（ArcMap 的典型脏请求）也要能认 ---
        dirty = ("/xyz/%s/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                 "&LAYER=%s&TILEMATRIX=%d&TILEROW=%d&TILECOL=%d"
                 "service=WMTS&request=GetTile&layer=%s&TILEMATRIX=%d"
                 "&TILEROW=%d&TILECOL=%d&FORMAT="
                 % (ent["id"], ent["id"], z, y, x, ent["id"], z, y, x))
        st2, body2 = get(PORT, dirty, timeout=30)
        print(u"\n[3] 粘连查询串  HTTP %d  %s  %d 字节  ->  %s"
              % (st2, xyz_sources._img_kind(body2) or u"?", len(body2),
                 u"OK" if len(body2) > 500 else u"!!!! 内容可疑"))

        # --- 4. 天地图老路没坏 ---
        key = tile_proxy.read_port_file  # noqa: F841  (只是避免 lint 抱怨)
        st3, body3 = get(PORT, "/img_w/esri/wmts?SERVICE=WMTS&REQUEST=GetCapabilities"
                               "&VERSION=1.0.0", timeout=30)
        print(u"\n[4] 天地图 capabilities  HTTP %d  %d 字节  -> %s"
              % (st3, len(body3),
                 u"OK（仍含 127.0.0.1 改写）"
                 if (b"127.0.0.1" in body3) else u"!!!! 异常"))

        st4, body4 = get(PORT, "/stats")
        print(u"\n[5] 统计: %s" % body4.decode("utf-8", "replace"))
        return 0
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        log.close()


if __name__ == "__main__":
    sys.exit(main())
