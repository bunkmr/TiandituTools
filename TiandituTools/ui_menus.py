# -*- coding: utf-8 -*-
"""底图选择。

分两层，**严格分开**：
  * 数据层（可安全在 ArcMap 进程内使用）
      enumerate_basemaps() -> [(组名, 名称, payload)]
      apply_basemap(payload)  -> 在 ArcMap 中真正添加图层
    本模块顶层**不 import Tkinter**。
  * 界面层（只在独立进程里跑，见 ui_main.py）
      run_standalone() -> payload   （Tkinter 选择窗口）

payload 形态（可 JSON 化，用于跨进程传递）：
      {"kind": "maptype",  "maptype": "img"}
      {"kind": "group",    "key": "img_label"}
      {"kind": "catalog",  "entry": {...}}     WMTS 地址型条目
      {"kind": "xyz",      "entry": {...}}     XYZ 瓦片模板条目
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

from config import map_enabled
from tianditu_api import (
    TIANDITU_MAP_GROUPS,
    TIANDITU_MAP_INFO,
    _to_unicode,
    load_map_json,
)

try:
    import xyz_sources
except Exception:
    xyz_sources = None

GROUP_SINGLE = u"天地图（单图层）"
GROUP_LABELED = u"天地图（含注记）"


# ---------------------------------------------------------------------------
# 数据层 —— 在 ArcMap 进程内调用
# ---------------------------------------------------------------------------
def enumerate_basemaps():
    """返回 [(组名, 名称, payload)]；不依赖 ArcMap，可在任意进程调用。"""
    items = []

    for maptype in sorted(TIANDITU_MAP_INFO.keys()):
        items.append((
            GROUP_SINGLE,
            _to_unicode(TIANDITU_MAP_INFO[maptype]),
            {"kind": "maptype", "maptype": maptype},
        ))

    for key, name, _layers in TIANDITU_MAP_GROUPS:
        items.append((
            GROUP_LABELED,
            _to_unicode(name),
            {"kind": "group", "key": key},
        ))

    # 省级节点等「地址式」条目
    data = load_map_json("tianditu_province.json") or {}
    for group in sorted(data.keys()):
        gname = _to_unicode(group)
        for entry in data[group] or []:
            ename = _to_unicode(entry.get("name") or gname)
            if not map_enabled(ename):
                continue
            items.append((
                u"省级节点 · %s" % gname,
                ename,
                {"kind": "catalog", "entry": entry},
            ))

    # XYZ 瓦片源（内置 xyz.json + extra.json + 用户自定义，见 xyz_sources）
    if xyz_sources is not None:
        for gname, arr in xyz_sources.groups():
            for it in arr:
                if not map_enabled(it["name"]):
                    continue
                items.append((
                    gname,
                    it["name"],
                    {"kind": "xyz", "entry": it},
                ))
    return items


def apply_basemap(payload):
    """按 payload 添加底图。

    实现在 layer_manager.apply_basemap —— 它只用 ArcObjects，不依赖 arcpy，
    因此**既能在 ArcMap 进程内调用，也能在独立界面进程内调用**。
    返回 True/False。
    """
    from layer_manager import apply_basemap as _apply

    return _apply(payload)


# ---------------------------------------------------------------------------
# 界面层 —— 只在独立进程（ui_main.py）里调用
# ---------------------------------------------------------------------------

_DATUM_HINT = {
    u"gcj02": u"⚠ GCJ-02 火星坐标：与 WGS84/GPS 数据叠加会整体偏移 300~600 米",
    u"bd09": u"⚠ BD-09 坐标：与 WGS84 数据叠加会偏移",
}


def run_standalone():
    """Tkinter 底图选择窗口；返回所选 payload，取消返回 {}。"""
    import Tkinter as tk
    import ttk

    items = enumerate_basemaps()
    state = {"payload": None}

    root = tk.Tk()
    root.title(u"天地图 Tools - 添加底图".encode("utf-8"))
    # 尺寸交给 ui_util：夹进屏幕并按比例靠上摆放
    try:
        import ui_util
        ui_util.place(root, 620, 620, min_width=520, min_height=420)
    except Exception:
        root.geometry("620x620")
        root.minsize(520, 420)

    ttk.Label(
        root,
        text=u"选择要添加的底图：双击，或选中后点「添加」".encode("utf-8"),
    ).pack(anchor=tk.W, padx=10, pady=(10, 4))

    # 搜索框 —— 图源上百个以后，靠翻树太重
    findbar = ttk.Frame(root)
    findbar.pack(fill=tk.X, padx=10, pady=(0, 6))
    ttk.Label(findbar, text=u"筛选".encode("utf-8")).pack(side=tk.LEFT)
    var_find = tk.StringVar()
    ent_find = ttk.Entry(findbar, textvariable=var_find)
    ent_find.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
    lbl_count = ttk.Label(findbar, text=u"", foreground="#666")
    lbl_count.pack(side=tk.LEFT)

    wrap = ttk.Frame(root)
    wrap.pack(fill=tk.BOTH, expand=True, padx=10)
    tree = ttk.Treeview(wrap, columns=("name",), show="tree headings", height=18)
    tree.heading("#0", text=u"分类".encode("utf-8"))
    tree.heading("name", text=u"名称".encode("utf-8"))
    tree.column("#0", width=230, stretch=False)
    tree.column("name", width=340)
    sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # 用于筛选：iid -> (组名, 名称, payload)
    holders = {}

    def rebuild(keyword=u""):
        tree.delete(*tree.get_children())
        holders.clear()
        kw = _to_unicode(keyword).strip().lower()
        group_nodes = {}
        shown = 0
        for glabel, label, payload in items:
            if kw and kw not in label.lower() and kw not in glabel.lower():
                continue
            node = group_nodes.get(glabel)
            if node is None:
                node = tree.insert("", tk.END, text=glabel, open=True)
                group_nodes[glabel] = node
            iid = tree.insert(node, tk.END, text=u"", values=(label,))
            holders[iid] = payload
            shown += 1
        lbl_count.configure(text=u"共 %d 项".encode("utf-8") % shown)
        return shown

    def on_find(*_a):
        rebuild(var_find.get())

    ent_find.bind("<KeyRelease>", on_find)
    var_find.trace("w", lambda *a: on_find())

    def current_payload():
        sel = tree.selection()
        if not sel:
            return None
        return holders.get(sel[0])

    def on_select(_evt=None):
        p = current_payload()
        hint = u""
        if p and p.get("kind") == "xyz":
            e = p.get("entry") or {}
            hint = _DATUM_HINT.get(_to_unicode(e.get("datum") or u""), u"")
            if not hint and e.get("note"):
                hint = _to_unicode(e["note"])
        lbl_hint.configure(text=hint.encode("utf-8") if hint else "")
        btn_add.configure(state=(tk.NORMAL if p else tk.DISABLED))

    tree.bind("<<TreeviewSelect>>", on_select)

    def accept(_evt=None):
        p = current_payload()
        if not p:
            return
        state["payload"] = p
        try:
            root.destroy()
        except Exception:
            pass

    def open_manager():
        """就地打开自定义图源管理器，关掉后刷新列表（不必重开本窗口）"""
        try:
            import ui_xyz
            ui_xyz.show_manager(root)
        except Exception as e:
            try:
                import tkMessageBox as mb
                mb.showerror(u"天地图 Tools",
                             (u"打开图源管理器失败：%s" % e).encode("utf-8"))
            except Exception:
                pass
        # 管理器里可能加了源，重建（缓存有 mtime 签名，会自动重读文件）
        if xyz_sources is not None:
            try:
                xyz_sources.sources(reload=True)
            except Exception:
                pass
        del items[:]
        items.extend(enumerate_basemaps())
        rebuild(var_find.get())

    tree.bind("<Double-1>", accept)
    tree.bind("<Return>", accept)

    lbl_hint = ttk.Label(root, text=u"", foreground="#b06a00", wraplength=580,
                         justify=tk.LEFT)
    lbl_hint.pack(fill=tk.X, padx=10, pady=(6, 0))

    bar = ttk.Frame(root)
    bar.pack(fill=tk.X, padx=10, pady=10)
    btn_add = ttk.Button(bar, text=u"添加".encode("utf-8"), command=accept,
                         state=tk.DISABLED)
    btn_add.pack(side=tk.RIGHT, padx=4)
    ttk.Button(bar, text=u"取消".encode("utf-8"),
               command=root.destroy).pack(side=tk.RIGHT)
    ttk.Button(bar, text=u"管理图源…".encode("utf-8"),
               command=open_manager).pack(side=tk.LEFT)

    rebuild()

    try:
        root.attributes("-topmost", True)
        root.after(900, lambda: root.attributes("-topmost", False))
    except Exception:
        pass
    try:
        root.focus_force()
    except Exception:
        pass

    root.mainloop()
    return state["payload"] or {}
