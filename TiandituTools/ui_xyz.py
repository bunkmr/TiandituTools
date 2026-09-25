# -*- coding: utf-8 -*-
"""自定义 XYZ 图源管理（Tkinter，只在独立进程里跑）。

这里只管"图源清单"这一件事：
  * 内置源（maps/xyz.json）**只读**，但可以「复制为自定义」再改；
  * 自定义源存到 %APPDATA%\\TiandituTools\\config.json 的 xyzSources；
  * 每条都能就地「测试」—— 真去拉一张瓦片看看通不通。

为什么不放在「设置」里：设置窗口已经有两个页签、管的是 Key 和显示开关；
图源是要经常增删的东西，独立窗口更顺手，从底图选择窗直接就能打开。

本模块不 import arcpy、不 import layer_manager。
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import threading

import Tkinter as tk
import tkMessageBox
import ttk

import xyz_sources
import ui_util
from tianditu_api import _to_unicode

#: 新增时的引导模板 —— 大多数人卡在"URL 该长什么样"
TEMPLATES = [
    (u"标准 XYZ（Google/OSM 风格）", u"https://host/path/{z}/{x}/{y}.png"),
    (u"带子域（{s} = 0..3 或 a..d）", u"https://{s}.host/path/{z}/{x}/{y}.png"),
    (u"ArcGIS REST 切片（注意 y 在前）", u"https://host/arcgis/rest/services/XXX/MapServer/tile/{z}/{y}/{x}"),
    (u"TMS 行号南起（{-y}）", u"https://host/path/{z}/{x}/{-y}.png"),
    (u"天地图 DataServer", u"https://t{s}.tianditu.gov.cn/DataServer?T=vec_w&x={x}&y={y}&l={z}&tk={tk}"),
]


def _u(v):
    return _to_unicode(v)


class SourceDialog(tk.Toplevel):
    """新增 / 编辑一个 XYZ 图源"""

    def __init__(self, parent, entry=None, title=u"新增 XYZ 图源"):
        tk.Toplevel.__init__(self, parent)
        self.title(title.encode("utf-8"))
        self.resizable(False, True)
        self.result = None
        self.entry = dict(entry or {})
        self._build()
        self._load()
        try:
            # 表单挺长的（十几行），按实际需要量一次再夹进屏幕 /
            # 居中到父窗口上 —— 否则在缩放大屏上会跑到屏幕右下角去。
            self.update_idletasks()
            ui_util.center_on(self, parent, self.winfo_reqwidth(),
                              self.winfo_reqheight())
            self.grab_set()
            self.transient(parent)
            self.focus_set()
        except Exception:
            pass

    def _build(self):
        f = ttk.Frame(self, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        f.columnconfigure(1, weight=1)

        r = [0]

        def row(label, widget, hint=None):
            ttk.Label(f, text=label.encode("utf-8")).grid(
                row=r[0], column=0, sticky=tk.NW, pady=4, padx=(0, 8))
            widget.grid(row=r[0], column=1, sticky=tk.EW, pady=4)
            r[0] += 1
            if hint:
                ttk.Label(f, text=hint.encode("utf-8"), foreground="#777",
                          wraplength=420, justify=tk.LEFT).grid(
                    row=r[0], column=1, sticky=tk.W, pady=(0, 6))
                r[0] += 1

        self.var_name = tk.StringVar()
        row(u"名称", ttk.Entry(f, textvariable=self.var_name, width=52))

        self.var_url = tk.StringVar()
        ent_url = ttk.Entry(f, textvariable=self.var_url, width=52)
        row(u"URL 模板", ent_url,
            u"占位符：{x} {y} {z} {-y}(TMS 南起) {s}(子域) {tk}(天地图 Key)")

        # 模板速填
        tplf = ttk.Frame(f)
        tplf.grid(row=r[0], column=1, sticky=tk.W, pady=(0, 6))
        r[0] += 1
        ttk.Label(tplf, text=u"示例：".encode("utf-8")).pack(side=tk.LEFT)
        var_tpl = tk.StringVar()
        cmb = ttk.Combobox(tplf, textvariable=var_tpl, width=30, state="readonly",
                           values=[t[0].encode("utf-8") for t in TEMPLATES])
        cmb.pack(side=tk.LEFT)
        ttk.Button(tplf, text=u"填入".encode("utf-8"),
                   command=lambda: self._use_tpl(cmb)).pack(side=tk.LEFT, padx=4)

        self.var_group = tk.StringVar()
        row(u"分组", ttk.Entry(f, textvariable=self.var_group, width=24),
            u"在底图选择窗里按这个名字归组")

        zf = ttk.Frame(f)
        zf.grid(row=r[0], column=1, sticky=tk.W, pady=4)
        r[0] += 1
        ttk.Label(zf, text=u"层级 z".encode("utf-8")).pack(side=tk.LEFT)
        self.var_zmin = tk.StringVar()
        self.var_zmax = tk.StringVar()
        ttk.Entry(zf, textvariable=self.var_zmin, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(zf, text=u"到".encode("utf-8")).pack(side=tk.LEFT)
        ttk.Entry(zf, textvariable=self.var_zmax, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(zf, text=u"（该源实际有数据的层级范围）".encode("utf-8"),
                  foreground="#777").pack(side=tk.LEFT, padx=6)

        self.var_subs = tk.StringVar()
        row(u"子域列表", ttk.Entry(f, textvariable=self.var_subs, width=32),
            u"逗号分隔；模板里用了 {s} 才需要，比如 0,1,2,3 或 a,b,c")

        self.var_referer = tk.StringVar()
        row(u"Referer", ttk.Entry(f, textvariable=self.var_referer, width=40),
            u"源有防盗链时填它的站点首页，比如 https://map.qq.com/")

        self.var_datum = tk.StringVar()
        cmb_d = ttk.Combobox(f, textvariable=self.var_datum, width=14,
                             state="readonly",
                             values=["wgs84", "gcj02", "bd09"])
        row(u"坐标系", cmb_d,
            u"gcj02=国内偏移源（高德/腾讯等），叠加 WGS84 数据会错位数百米")

        self.var_proxy = tk.StringVar()
        cmb_p = ttk.Combobox(f, textvariable=self.var_proxy, width=26,
                             state="readonly",
                             values=[u"跟随全局设置", u"强制走代理", u"强制直连"])
        row(u"代理", cmb_p,
            u"Google/OSM 这类境外源需要代理；天地图/高德/Esri 直连即可")

        self.var_note = tk.StringVar()
        row(u"备注", ttk.Entry(f, textvariable=self.var_note, width=52))

        bf = ttk.Frame(f)
        bf.grid(row=r[0], column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Button(bf, text=u"确定".encode("utf-8"),
                   command=self.on_ok).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bf, text=u"取消".encode("utf-8"),
                   command=self.destroy).pack(side=tk.RIGHT)

    def _use_tpl(self, cmb):
        idx = cmb.current()
        if idx >= 0:
            self.var_url.set(TEMPLATES[idx][1])

    def _load(self):
        e = self.entry
        self.var_name.set(_u(e.get("name") or u""))
        self.var_url.set(_u(e.get("url") or u""))
        self.var_group.set(_u(e.get("group") or u"我的图源"))
        self.var_zmin.set(str(e.get("zmin", xyz_sources.DEFAULT_ZMIN)))
        self.var_zmax.set(str(e.get("zmax", xyz_sources.DEFAULT_ZMAX)))
        self.var_subs.set(u",".join(_u(s) for s in (e.get("subdomains") or [])))
        self.var_referer.set(_u(e.get("referer") or u""))
        self.var_datum.set(_u(e.get("datum") or u"wgs84"))
        pr = e.get("proxy")
        self.var_proxy.set({True: u"强制走代理", False: u"强制直连"}.get(
            pr, u"跟随全局设置"))
        self.var_note.set(_u(e.get("note") or u""))

    def on_ok(self):
        url = self.var_url.get().strip()
        if not url:
            tkMessageBox.showwarning(u"天地图 Tools", u"URL 模板不能为空".encode("utf-8"))
            return
        if "{" not in url:
            tkMessageBox.showwarning(
                u"天地图 Tools",
                u"URL 里必须有占位符（至少 {z}/{x}/{y}），\n"
                u"否则它是一条固定地址、不是瓦片模板。".encode("utf-8"))
            return

        def _int(v, d):
            try:
                return int(str(v).strip())
            except Exception:
                return d

        proxy = {u"强制走代理": True, u"强制直连": False}.get(self.var_proxy.get())
        raw = {
            "name": self.var_name.get().strip() or url,
            "url": url,
            "group": self.var_group.get().strip() or u"我的图源",
            "zmin": _int(self.var_zmin.get(), 0),
            "zmax": _int(self.var_zmax.get(), 18),
            "subdomains": [s.strip() for s in self.var_subs.get().split(",") if s.strip()],
            "referer": self.var_referer.get().strip(),
            "datum": (self.var_datum.get() or u"wgs84"),
            "proxy": proxy,
            "note": self.var_note.get().strip(),
        }
        it = xyz_sources.normalize(raw, raw["group"])
        if not it:
            tkMessageBox.showerror(u"天地图 Tools",
                                   u"这条记录不是合法的 XYZ 模板。".encode("utf-8"))
            return
        # 编辑已有条目时保留原 id，否则每次编辑都会变成新的一条
        if self.entry.get("id"):
            it["id"] = self.entry["id"]
        self.result = it
        self.destroy()


class Manager(tk.Toplevel):
    """图源清单"""

    def __init__(self, parent=None):
        tk.Toplevel.__init__(self, parent)
        self.title(u"天地图 Tools - 图源管理".encode("utf-8"))
        ui_util.place(self, 900, 520, min_width=680, min_height=380)
        self._build()
        self.reload()
        try:
            self.update_idletasks()
            self.focus_set()
        except Exception:
            pass

    def _build(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 4))
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text=(u"内置图源只读（可「复制为自定义」后修改）；"
                  u"自定义图源保存在 %APPDATA%\\TiandituTools\\config.json"
                  ).encode("utf-8"),
            foreground="#555",
        ).pack(anchor=tk.W)

        wrap = ttk.Frame(self, padding=(10, 0))
        wrap.pack(fill=tk.BOTH, expand=True)
        cols = ("name", "group", "z", "datum", "kind", "url")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, t, w in (("name", u"名称", 205), ("group", u"分组", 165),
                        ("z", u"层级", 62), ("datum", u"坐标系", 74),
                        ("kind", u"来源", 66), ("url", u"URL 模板", 300)):
            self.tree.heading(c, text=t.encode("utf-8"))
            self.tree.column(c, width=w, stretch=(c == "url"))
        sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.on_edit())

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text=u"新增".encode("utf-8"),
                   command=self.on_add).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text=u"编辑".encode("utf-8"),
                   command=self.on_edit).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text=u"复制为自定义".encode("utf-8"),
                   command=self.on_clone).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text=u"删除".encode("utf-8"),
                   command=self.on_delete).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text=u"测试连通性".encode("utf-8"),
                   command=self.on_test).pack(side=tk.LEFT, padx=12)
        ttk.Button(bar, text=u"关闭".encode("utf-8"),
                   command=self.destroy).pack(side=tk.RIGHT)

        self.lbl = ttk.Label(self, text=u"", foreground="#0078d7", wraplength=860,
                             justify=tk.LEFT)
        self.lbl.pack(fill=tk.X, padx=10, pady=(0, 8))

    # -- 数据 --------------------------------------------------------------

    def _user_entries(self):
        """用户自定义条目（原始 dict 列表，保留 id）"""
        import json

        import config
        conf = config.load_config()
        out = []
        for raw in (conf.get(xyz_sources.CONFIG_KEY) or []):
            it = xyz_sources.normalize(raw, u"我的图源")
            if it:
                out.append(it)
        return out

    def _save_user(self, entries):
        xyz_sources.save_user_sources(entries)

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for it in xyz_sources.sources(reload=True):
            iid = self.tree.insert(
                "", tk.END,
                values=(_u(it["name"]), _u(it["group"]),
                        u"%d~%d" % (it["zmin"], it["zmax"]),
                        _u(it["datum"]),
                        u"内置" if it.get("builtin") else u"自定义",
                        _u(it["url"])))
            self._rows[iid] = it
        self.lbl.configure(text=u"共 %d 条".encode("utf-8") % len(self._rows))
        # 让"我的图源"排在最前，方便找
        pass

    def _selected(self):
        sel = self.tree.selection()
        return self._rows.get(sel[0]) if sel else None

    # -- 动作 --------------------------------------------------------------

    def on_add(self):
        dlg = SourceDialog(self, None, u"新增 XYZ 图源")
        self.wait_window(dlg)
        if dlg.result:
            ent = self._user_entries()
            ent = [e for e in ent if e["id"] != dlg.result["id"]] + [dlg.result]
            self._save_user(ent)
            self.reload()
            self.lbl.configure(text=u"已新增：%s".encode("utf-8") % dlg.result["name"])

    def on_edit(self):
        it = self._selected()
        if not it:
            return
        if it.get("builtin"):
            tkMessageBox.showinfo(
                u"天地图 Tools",
                u"内置图源不能直接改（升级插件会覆盖）。\n\n"
                u"请用「复制为自定义」，改出来的那条存你自己的 config.json。"
                .encode("utf-8"))
            return
        dlg = SourceDialog(self, it, u"编辑 XYZ 图源")
        self.wait_window(dlg)
        if dlg.result:
            ent = [e for e in self._user_entries() if e["id"] != it["id"]]
            ent.append(dlg.result)
            self._save_user(ent)
            self.reload()

    def on_clone(self):
        it = self._selected()
        if not it:
            return
        raw = dict(it)
        raw["id"] = None
        raw["name"] = _u(it["name"]) + u" - 副本"
        raw["group"] = u"我的图源"
        dlg = SourceDialog(self, raw, u"复制为自定义图源")
        self.wait_window(dlg)
        if dlg.result:
            ent = self._user_entries()
            ent.append(dlg.result)
            self._save_user(ent)
            self.reload()

    def on_delete(self):
        it = self._selected()
        if not it:
            return
        if it.get("builtin"):
            tkMessageBox.showinfo(u"天地图 Tools",
                                  u"内置图源不能删除。".encode("utf-8"))
            return
        if not tkMessageBox.askyesno(
                u"天地图 Tools",
                (u"确定删除「%s」？" % _u(it["name"])).encode("utf-8")):
            return
        ent = [e for e in self._user_entries() if e["id"] != it["id"]]
        self._save_user(ent)
        self.reload()
        # 已经加进地图的图层不会因此消失，但重启 ArcMap 后它就取不到瓦片了，
        # 这一点必须讲清楚，否则用户会以为插件坏了。
        self.lbl.configure(
            text=u"已删除。注意：地图里若已添加过该图层，重启 ArcMap 后将无法再出图。"
                 .encode("utf-8"))

    def on_test(self):
        it = self._selected()
        if not it:
            return
        self.lbl.configure(text=u"正在测试：%s …".encode("utf-8") % _u(it["name"]))

        def run():
            try:
                ok, msg = xyz_sources.probe(it, timeout=12)
            except Exception as e:
                ok, msg = False, u"异常 %r" % (e,)
            self.after(0, lambda: self._show_test(it, ok, msg))

        threading.Thread(target=run).start()

    def _show_test(self, it, ok, msg):
        head = (u"✓ 可用" if ok else u"✗ 不通")
        self.lbl.configure(text=u"%s  %s：%s" % (head, _u(it["name"]),
                                               msg.split(u"\n")[0]),
                           foreground="#0a7d28" if ok else "#c00")
        if ok:
            tkMessageBox.showinfo(u"天地图 Tools",
                                  (u"%s\n\n%s" % (_u(it["name"]), msg)).encode("utf-8"))
        else:
            tkMessageBox.showerror(u"天地图 Tools",
                                   (u"%s\n\n%s" % (_u(it["name"]), msg)).encode("utf-8"))


def show_manager(parent=None):
    """就地打开管理器（从底图选择窗调用；也供 ui_main 单独使用）"""
    m = Manager(parent)
    try:
        m.lift()
        m.attributes("-topmost", True)
        m.after(900, lambda: m.attributes("-topmost", False))
    except Exception:
        pass
    if parent is not None:
        try:
            parent.wait_window(m)
        except Exception:
            pass
    return m


def run_standalone():
    """独立进程入口（ui_main.py 的 mode="xyz"）"""
    root = tk.Tk()
    root.withdraw()
    m = Manager(root)
    try:
        m.deiconify()
        m.lift()
        m.focus_force()
        m.attributes("-topmost", True)
        m.after(900, lambda: m.attributes("-topmost", False))
    except Exception:
        pass
    root.wait_window(m)
    try:
        root.destroy()
    except Exception:
        pass
    return {}
