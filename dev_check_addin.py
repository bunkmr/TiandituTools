# -*- coding: utf-8 -*-
"""检查「天地图 Tools」加载项在 ArcMap 里是否正常（开发工具，不随插件发布）。

做的事：
  1. 连到正在运行的 ArcMap（esriFramework.AppROT -> IApplication）
  2. 找到加载项的工具条，把它的 **每个按钮** 列出来（caption / 图标 FaceID）
  3. 把工具条设为可见（showInitially="false"，默认不显示）
  4. 截一张屏幕并裁出工具条那一条，存成 _tb_check.png
  5. 打印分辨率/尺寸，便于确认 5 个按钮都在

用法（用 ArcGIS 的 Python 2.7 跑）：
    <ArcGIS py2> dev_check_addin.py
"""

from __future__ import print_function

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "TiandituTools")
sys.path.insert(0, PKG)

import arcobjects                                        # noqa: E402


def log(*a):
    sys.stdout.write(" ".join(str(x) for x in a) + "\n")
    sys.stdout.flush()


def _alive(obj):
    """comtypes 的 Find 找不到对象时不会返回 None，而是返回一个
    **NULL 接口指针** —— `obj is not None` 为真，一取属性就
    'ValueError: NULL COM pointer access'。所以必须真的摸一下。"""
    if obj is None:
        return False
    try:
        _ = obj.Caption
        return True
    except Exception:
        return False


def find_bar(cbs):
    """按名字找加载项工具条；找不到就按标题扫一遍"""
    for name in (u"TiandituTools_addin.toolbar", u"TiandituTools.toolbar"):
        try:
            bar = cbs.Find(name)
        except Exception:
            continue
        if _alive(bar):
            return bar, name
    try:
        n = cbs.Count
    except Exception:
        return None, None
    caps = []
    for i in range(n):
        try:
            bar = cbs.Item(i)
            cap = u"%s" % (bar.Caption,)
        except Exception:
            continue
        caps.append(cap)
        if u"天地图" in cap or u"Tianditu" in cap:
            return bar, u"按标题扫到: %s" % cap
    log("  命令条清单(%d): %s" % (n, u" | ".join(caps)))
    return None, None


def main():
    app = arcobjects.application()
    if app is None:
        log("连不上 ArcMap（application() 返回 None）")
        return 1
    doc = app.Document
    cbs = doc.CommandBars

    bar, how = find_bar(cbs)
    if bar is None:
        log("没找到「天地图 Tools」工具条（加载项可能没加载）")
        return 2
    log("找到工具条: %r  (通过 %r)" % (u"%s" % bar.Caption, how))

    try:
        cnt = bar.Controls.Count
    except Exception as e:
        log("取 Controls 失败: %r" % (e,))
        return 3
    log("按钮数: %d" % cnt)
    for i in range(1, cnt + 1):
        try:
            c = bar.Controls.Item(i)
            cap = u"%s" % c.Caption
        except Exception as e:
            log("  [%d] 读取失败 %r" % (i, e))
            continue
        fid = None
        for attr in ("FaceID", "ID"):
            try:
                fid = getattr(c, attr)
                break
            except Exception:
                pass
        log("  [%d] caption=%-10s faceId=%s" % (i, cap, fid))

    try:
        bar.Visible = True
        log("已设置 Visible = True")
    except Exception as e:
        log("设置 Visible 失败: %r" % (e,))
        return 4

    # 截屏：整个屏幕 -> 裁顶部两条（工具条常停靠在菜单栏下面）
    try:
        import ctypes
        from PIL import ImageGrab
        u32 = ctypes.windll.user32
        u32.SetProcessDPIAware()
        img = ImageGrab.grab()
        W, H = img.size
        log("屏幕 %dx%d" % (W, H))
        img.crop((0, 0, W, int(H * 0.22))).save(os.path.join(HERE, "_tb_check.png"))
        img.save(os.path.join(HERE, "_tb_check_full.png"))
        log("已存 _tb_check.png / _tb_check_full.png")
    except Exception as e:
        log("截屏跳过: %r" % (e,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
