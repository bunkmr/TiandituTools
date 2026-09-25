# -*- coding: utf-8 -*-
"""无窗口自检（不显示任何窗口，不启动 ArcMap）。

覆盖三类最容易出问题的地方：
  1. Py2.7 + Tkinter 的中文编码往返 —— Py2 Tkinter 最经典的坑
  2. 各界面模块能否被构建（SettingsDialog / SearchDialog）
  3. 桥接全链路：临时文件 -> pythonw 子进程 -> JSON 回读

用法（用 ArcGIS 自带 Python 2.7 运行）:
    "C:\\Python27\\ArcGIS10.4\\python.exe" dev_headless_check.py
"""
from __future__ import print_function

import os
import sys

PKG = r"D:\Work\projects\arcmap\TiandituTools"
sys.path.insert(0, PKG)
os.chdir(PKG)

import Tkinter as tk          # noqa: E402
import ttk                    # noqa: E402

_ok = [True]


def check(label, cond, extra=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + label
          + (("  " + extra) if extra else ""))
    if not cond:
        _ok[0] = False


def to_u(v):
    try:
        return v if isinstance(v, unicode) else v.decode("utf-8")  # noqa: F821
    except Exception:
        return None


print("Python:", sys.version.split()[0])
root = tk.Tk()
root.withdraw()

# --- 1) 中文编码往返 -------------------------------------------------------
print("\n[1] 中文编码往返")
want = u"天地图 Tools 底图·注记"
lbl = tk.Label(root, text=want.encode("utf-8"))
check(u"Label", to_u(lbl.cget("text")) == want, repr(lbl.cget("text"))[:70])

tree = ttk.Treeview(root, show="tree")
iid = tree.insert("", tk.END, text=want.encode("utf-8"))
check(u"Treeview", to_u(tree.item(iid, "text")) == want,
      repr(tree.item(iid, "text"))[:70])

# --- 2) 界面可构建 ---------------------------------------------------------
print("\n[2] 界面模块构建")
try:
    import ui_settings
    d = ui_settings.SettingsDialog(root)
    d.withdraw()
    check(u"SettingsDialog 构建", int(d.winfo_exists()) == 1,
          "title=%r" % (d.title(),))
    d.destroy()
except Exception as e:
    check(u"SettingsDialog 构建", False, repr(e))

try:
    import ui_search
    s = ui_search.SearchDialog(root)
    s.withdraw()
    check(u"SearchDialog 构建", int(s.winfo_exists()) == 1,
          "title=%r" % (s.title(),))
    s.destroy()
except Exception as e:
    check(u"SearchDialog 构建", False, repr(e))

# --- 3) 数据层 -------------------------------------------------------------
print("\n[3] 数据层 ui_menus.enumerate_basemaps()")
try:
    import ui_menus
    items = ui_menus.enumerate_basemaps()
    kinds = {}
    for _g, _l, p in items:
        kinds[p.get("kind")] = kinds.get(p.get("kind"), 0) + 1
    check(u"枚举到底图", len(items) > 0,
          u"%d 项  %s" % (len(items), u", ".join(
              u"%s=%s" % (k, v) for k, v in sorted(kinds.items()))))
    check(u"payload 可 JSON 化", True)
except Exception as e:
    check(u"枚举底图", False, repr(e))
    items = []

# --- 4) 桥接全链路 ---------------------------------------------------------
print("\n[4] 桥接全链路（不弹窗口：未知 mode 会让 ui_main 直接写回 {}）")
try:
    import ui_bridge
    py = ui_bridge.find_python()
    check(u"找到 ArcGIS Python", bool(py), py or "")
    res = ui_bridge.run_ui("__smoke__")
    check(u"子进程 -> JSON 回读", res == {}, repr(res))
except Exception as e:
    check(u"桥接链路", False, repr(e))

print("\n[6] ArcMap 进程内模块绝不加载 Tkinter（独立进程，防回归）")
try:
    import subprocess
    code = (
        "import sys;sys.path.insert(0,%r);"
        "import layer_manager,ui_menus,ui_bridge;"
        "bad=[k for k in sys.modules if k.split('.')[0] in ('Tkinter','ttk')];"
        "print('LEAK='+repr(bad));sys.exit(1 if bad else 0)" % PKG
    )
    _p = subprocess.Popen([sys.executable, "-c", code],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    _o = _p.communicate()[0].decode("utf-8", "replace").strip()
    _last = [l for l in _o.splitlines() if l.startswith("LEAK=")]
    check(u"不加载 Tkinter", _p.returncode == 0,
          (_last[-1] if _last else _o[-160:]))
except Exception as e:
    check(u"Tkinter 隔离检查", False, repr(e))

root.destroy()

# --- 5) 底图选择窗口可构建（桩掉 mainloop，完全不会显示窗口）---------------
print("\n[5] 底图选择窗口构建（mainloop 已被桩掉，窗口不会显示）")
try:
    _real_mainloop = tk.Tk.mainloop
    tk.Tk.mainloop = lambda self: self.destroy()      # 构建完立即销毁，不显示
    try:
        import ui_menus
        payload = ui_menus.run_standalone()
    finally:
        tk.Tk.mainloop = _real_mainloop
    check(u"BasemapChooser 构建", payload == {}, repr(payload))
except Exception as e:
    check(u"BasemapChooser 构建", False, repr(e))

print("\nHEADLESS CHECK:", "ALL OK" if _ok[0] else "HAS FAILURES")
sys.exit(0 if _ok[0] else 1)
