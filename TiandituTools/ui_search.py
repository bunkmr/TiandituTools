# -*- coding: utf-8 -*-

"""搜索对话框：地名 / 地理编码 / 逆地理编码（Tkinter）"""

from __future__ import print_function

import os as _os, sys as _sys
_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import ttk

import Tkinter as tk
import tkMessageBox

from config import get_key
from tianditu_api import _to_unicode, geocode, regeocode, search_poi


class SearchDialog(tk.Toplevel):
    def __init__(self, parent=None):
        tk.Toplevel.__init__(self, parent)
        self.title(u"天地图 Tools - 搜索".encode("utf-8"))
        try:
            import ui_util
            ui_util.place(self, 480, 380, min_width=400, min_height=300)
        except Exception:
            self.geometry("480x360")
            self.minsize(400, 300)
        self._result = None          # 选中结果，回传给主进程执行
        self._build()
        try:
            self.update_idletasks()
            self.grab_set()
        except Exception:
            pass
        if parent:
            try:
                self.transient(parent)
            except Exception:
                pass
        self.focus_set()

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # --- 地名搜索 ---
        f1 = ttk.Frame(nb, padding=6)
        nb.add(f1, text=u"地名搜索".encode("utf-8"))
        top = ttk.Frame(f1)
        top.pack(fill=tk.X, pady=4)
        self.var_kw = tk.StringVar()
        self.ent_kw = ttk.Entry(top, textvariable=self.var_kw)
        self.ent_kw.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(top, text=u"搜索".encode("utf-8"), command=self.do_search).pack(
            side=tk.LEFT
        )
        # 注意：必须绑定到 Entry 控件，StringVar 没有 bind 方法
        # （原实现写成 self.var_kw.bind(...) 会抛 AttributeError，导致搜索窗口
        #   根本构建不出来）
        self.ent_kw.bind("<Return>", lambda e: self.do_search())

        cols = ("admin", "name", "lonlat")
        self.tree = ttk.Treeview(f1, columns=cols, show="headings", height=12)
        self.tree.heading("admin", text=u"序号/行政区".encode("utf-8"))
        self.tree.heading("name", text=u"地点".encode("utf-8"))
        self.tree.heading("lonlat", text=u"经纬度".encode("utf-8"))
        self.tree.column("admin", width=80)
        self.tree.column("name", width=200)
        self.tree.column("lonlat", width=140)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=4)
        self.tree.bind("<Double-1>", self._on_tree_dbl)
        ttk.Label(
            f1, text=u"双击结果定位；统计节点双击可下钻".encode("utf-8"), foreground="#666"
        ).pack(anchor=tk.W)

        # --- 地理编码 ---
        f2 = ttk.Frame(nb, padding=6)
        nb.add(f2, text=u"地理编码".encode("utf-8"))
        r2 = ttk.Frame(f2)
        r2.pack(fill=tk.X, pady=4)
        self.var_addr = tk.StringVar()
        ttk.Entry(r2, textvariable=self.var_addr).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        ttk.Button(r2, text=u"查询".encode("utf-8"), command=self.do_geocode).pack(
            side=tk.LEFT
        )
        self.lbl_geo = tk.Label(
            f2, text=u"", justify=tk.LEFT, anchor=tk.W, wraplength=440
        )
        self.lbl_geo.pack(fill=tk.X, pady=8)
        self._geo_lonlat = None
        ttk.Button(
            f2,
            text=u"添加到地图".encode("utf-8"),
            command=self._add_geo_point,
        ).pack(anchor=tk.W)

        # --- 逆编码 ---
        f3 = ttk.Frame(nb, padding=6)
        nb.add(f3, text=u"逆地理编码".encode("utf-8"))
        r3 = ttk.Frame(f3)
        r3.pack(fill=tk.X, pady=4)
        self.var_lonlat = tk.StringVar()
        ttk.Entry(
            r3, textvariable=self.var_lonlat, width=30
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(r3, text=u"查询".encode("utf-8"), command=self.do_regeocode).pack(
            side=tk.LEFT
        )
        ttk.Label(
            f3, text=u"格式: 经度,纬度  例: 102.833,24.880".encode("utf-8"),
            foreground="#666",
        ).pack(anchor=tk.W)
        self.lbl_regeo = tk.Label(
            f3, text=u"", justify=tk.LEFT, anchor=tk.W, wraplength=440
        )
        self.lbl_regeo.pack(fill=tk.X, pady=8)

        # 状态
        self.var_status = tk.StringVar()
        ttk.Label(self, textvariable=self.var_status, foreground="#666").pack(
            anchor=tk.W, padx=8, pady=(0, 4)
        )

    # ------------------------------------------------------------------
    def _need_key(self):
        if not get_key():
            try:
                tkMessageBox.showerror(
                    u"天地图 Tools",
                    u"请先在设置中配置天地图 Key".encode("utf-8"),
                )
            except Exception:
                pass
            return True
        return False

    def _set_status(self, text):
        self.var_status.set(
            text.encode("utf-8") if isinstance(text, unicode) else text  # noqa: F821
        )

    # --- 地名搜索 ---
    def do_search(self):
        if self._need_key():
            return
        kw = self.var_kw.get().strip()
        if not kw:
            return
        if isinstance(kw, str):
            kw = kw.decode("utf-8", "ignore")
        self._set_status(u"搜索中…")
        self.tree.delete(*self.tree.get_children())
        self.update_idletasks()
        data = search_poi(kw)
        self._render_search(data)

    def _render_search(self, data):
        self._set_status(u"完成")
        if not data:
            self.tree.insert("", tk.END, values=(u"错误", u"请求失败", u""))
            return
        rtype = data.get("resultType")
        if rtype == 1:
            prompt = data.get("prompt") or []
            admin = u"全国"
            try:
                admin = prompt[0]["admins"][0]["adminName"]
            except (IndexError, KeyError, TypeError):
                pass
            if isinstance(admin, str):
                admin = admin.decode("utf-8", "ignore")
            root = self.tree.insert(
                "", tk.END, values=(admin, u"", u""), open=True
            )
            pois = data.get("pois")
            if not pois:
                self.tree.insert(
                    root, tk.END, values=("", u"无结果，请换关键词", u"")
                )
                return
            for i, poi in enumerate(pois):
                name = poi.get("name") or u""
                lonlat = poi.get("lonlat") or u""
                if isinstance(name, str):
                    name = name.decode("utf-8", "ignore")
                self.tree.insert(
                    root,
                    tk.END,
                    values=(str(i + 1), name, lonlat),
                )
        elif rtype == 2:
            stats = (data.get("statistics") or {}).get("allAdmins") or []
            for i, admins in enumerate(stats):
                an = admins.get("adminName") or u""
                if isinstance(an, str):
                    an = an.decode("utf-8", "ignore")
                cnt = admins.get("count")
                code = admins.get("adminCode") or u""
                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        u"%d %s" % (i + 1, an),
                        u"%s个结果" % cnt,
                        u"admin:%s" % code,
                    ),
                )
            self._search_kw = self.var_kw.get()
        elif rtype == 3:
            area = data.get("area") or {}
            name = area.get("name") or u""
            lonlat = area.get("lonlat") or u""
            if isinstance(name, str):
                name = name.decode("utf-8", "ignore")
            self.tree.insert("", tk.END, values=(u"行政区", name, lonlat))
        else:
            self.tree.insert("", tk.END, values=(u"未知", str(data), u""))

    def _on_tree_dbl(self, _evt):
        item = self.tree.selection()
        if not item:
            return
        vals = self.tree.item(item[0], "values")
        if not vals or len(vals) < 3:
            return
        admin, name, lonlat = vals[0], vals[1], vals[2]
        # 统计节点：admin:CODE
        if isinstance(lonlat, str) and lonlat.startswith("admin:"):
            code = lonlat.split(":", 1)[1]
            kw = self.var_kw.get().strip()
            if isinstance(kw, str):
                kw = kw.decode("utf-8", "ignore")
            self._set_status(u"在行政区内搜索…")
            data = search_poi(kw, admin_code=code)
            self._render_search(data)
            return
        if not lonlat or name in (u"无结果，请换关键词",):
            return
        try:
            lon_s, lat_s = lonlat.split(",")
            lon, lat = float(lon_s), float(lat_s)
        except (ValueError, AttributeError):
            return
        self._locate(name, lon, lat)

    def _locate(self, name, lon, lat):
        """只记录结果并关闭窗口。

        重要：**绝不能在对话框里直接调用 ArcMap API**（原实现 import
        layer_manager 并在 Tkinter 回调里加图层/缩放）——那正是让 ArcMap
        内部数据结构损坏并被强制中止的路径。这里改为把结果交给主进程，
        由主进程在 ArcMap 侧完成定位。
        """
        self._result = {
            "kind": "point",
            "name": _to_unicode(name),
            "lon": float(lon),
            "lat": float(lat),
        }
        self._set_status(u"已选择: %s（关闭窗口后在 ArcMap 中定位）" % _to_unicode(name))
        try:
            self.destroy()
        except Exception:
            pass

    # --- 地理编码 ---
    def do_geocode(self):
        if self._need_key():
            return
        addr = self.var_addr.get().strip()
        if not addr:
            return
        if isinstance(addr, str):
            addr = addr.decode("utf-8", "ignore")
        self._set_status(u"地理编码中…")
        self.update_idletasks()
        self._geo_lonlat = None
        data = geocode(addr)
        if not data:
            self.lbl_geo.configure(text=u"请求失败".encode("utf-8"))
            self._set_status(u"失败")
            return
        if str(data.get("msg")) == u"ok" or data.get("msg") == u"ok":
            loc = data.get("location") or {}
            try:
                lon = round(float(loc.get("lon")), 6)
                lat = round(float(loc.get("lat")), 6)
                self._geo_lonlat = (lon, lat)
                kw = loc.get("keyWord") or addr
                if isinstance(kw, str):
                    kw = kw.decode("utf-8", "ignore")
                score = loc.get("score")
                level = loc.get("level")
                text = u"关键词: %s\nScore: %s\n类别: %s\n经纬度: %s, %s" % (
                    kw, score, level, lon, lat,
                )
                self.lbl_geo.configure(
                    text=text.encode("utf-8"), justify=tk.LEFT, anchor=tk.W
                )
                self._geo_name = kw
            except (TypeError, ValueError):
                self.lbl_geo.configure(text=u"解析失败".encode("utf-8"))
            self._set_status(u"完成")
        elif data.get("msg") in (u"无结果", "无结果"):
            self.lbl_geo.configure(text=u"无结果".encode("utf-8"))
            self._set_status(u"无结果")
        else:
            self.lbl_geo.configure(
                text=str(data).encode("utf-8", "ignore")[:200]
            )
            self._set_status(u"完成")

    def _add_geo_point(self):
        if not self._geo_lonlat:
            return
        lon, lat = self._geo_lonlat
        name = getattr(self, "_geo_name", None) or self.var_addr.get()
        if isinstance(name, str):
            name = name.decode("utf-8", "ignore")
        self._locate(name, lon, lat)

    # --- 逆编码 ---
    def do_regeocode(self):
        if self._need_key():
            return
        raw = self.var_lonlat.get().strip()
        if not raw:
            return
        try:
            parts = raw.replace("，", ",").split(",")
            lon, lat = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            try:
                tkMessageBox.showerror(
                    u"天地图 Tools", u"经纬度格式不正确".encode("utf-8")
                )
            except Exception:
                pass
            return
        self._set_status(u"逆地理编码中…")
        self.update_idletasks()
        data = regeocode(lon, lat)
        if not data:
            self.lbl_regeo.configure(text=u"请求失败".encode("utf-8"))
            self._set_status(u"失败")
            return
        if str(data.get("status")) == "0":
            result = data.get("result") or {}
            addr = result.get("formatted_address") or u""
            if isinstance(addr, str):
                addr = addr.decode("utf-8", "ignore")
            if addr:
                self.lbl_regeo.configure(
                    text=addr.encode("utf-8"), justify=tk.LEFT, anchor=tk.W
                )
                self._set_status(u"完成")
            else:
                self.lbl_regeo.configure(text=u"无结果".encode("utf-8"))
                self._set_status(u"无结果")
        else:
            self.lbl_regeo.configure(
                text=str(data.get("msg") or data).encode("utf-8", "ignore")[:200]
            )
            self._set_status(u"完成")


# 单例，便于按钮切换显示
_search_dialog = None


def show_search(parent=None):
    global _search_dialog
    try:
        if _search_dialog is not None and _search_dialog.winfo_exists():
            _search_dialog.lift()
            _search_dialog.focus_set()
            return _search_dialog
    except Exception:
        _search_dialog = None
    _search_dialog = SearchDialog(parent)
    return _search_dialog


def run_standalone():
    """独立进程入口（由 ui_main.py 调用）。

    返回 {"kind":"point","name":…,"lon":…,"lat":…}；用户未选就关闭则返回 {}。
    """
    import Tkinter as tk

    root = tk.Tk()
    root.withdraw()
    dlg = SearchDialog(root)
    try:
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()
        dlg.attributes("-topmost", True)
        dlg.after(900, lambda: dlg.attributes("-topmost", False))
    except Exception:
        pass
    root.wait_window(dlg)
    try:
        root.destroy()
    except Exception:
        pass
    return dlg._result or {}
