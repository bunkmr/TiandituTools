# -*- coding: utf-8 -*-

"""设置对话框（Tkinter，Python 2.7）"""

from __future__ import print_function

import os as _os, sys as _sys
_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import ttk

import Tkinter as tk
import tkMessageBox

from config import load_config, save_config
from tianditu_api import check_key, _to_unicode


class SettingsDialog(tk.Toplevel):
    """天地图 Tools 设置"""

    def __init__(self, parent=None, tab=None):
        tk.Toplevel.__init__(self, parent)
        self.title(u"天地图 Tools - 设置".encode("utf-8"))
        self.resizable(False, False)
        self.conf = load_config()
        self._build_ui()
        self._load_values()
        self._select_tab(tab)
        # 这个窗口是 resizable(False, False) + grid 自然撑开的，
        # 所以量一次实际尺寸再夹进屏幕（225% 缩放下屏高只有 853 逻辑像素，
        # 控件一多就可能比屏幕还高，底部按钮会被挤出去）。
        try:
            import ui_util
            ui_util.fit(self)
        except Exception:
            pass
        # 在独立进程里 grab_set 才是安全的；包 try 以防窗口尚未 viewable
        try:
            self.update_idletasks()
            self.grab_set()
        except Exception:
            pass
        if parent is not None:
            try:
                self.transient(parent)
            except Exception:
                pass
        # 不要用 wait_visibility()：窗口若始终不可见会永久阻塞，
        # 而 ArcMap 此刻正阻塞等待本子进程返回 -> 会把 ArcMap 一起挂死。
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.focus_set()

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.nb = nb

        # ---- Tab: Key ----
        f_key = ttk.Frame(nb, padding=8)
        nb.add(f_key, text=u"Key 设置".encode("utf-8"))

        ttk.Label(f_key, text=u"当前 Key".encode("utf-8")).grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        self.var_key = tk.StringVar()
        ent = ttk.Entry(f_key, textvariable=self.var_key, width=40, show="*")
        ent.grid(row=0, column=1, sticky=tk.EW, pady=4, padx=6)
        self.btn_check = ttk.Button(
            f_key, text=u"校验并保存".encode("utf-8"), command=self.on_check_save
        )
        self.btn_check.grid(row=0, column=2, pady=4)

        ttk.Label(f_key, text=u"Key 列表".encode("utf-8")).grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self.lst_keys = tk.Listbox(f_key, height=4, width=40)
        self.lst_keys.grid(row=1, column=1, sticky=tk.EW, pady=4, padx=6)
        btns = ttk.Frame(f_key)
        btns.grid(row=1, column=2, sticky=tk.N)
        ttk.Button(btns, text=u"设为当前".encode("utf-8"), command=self.on_use_key).pack(
            fill=tk.X
        )
        ttk.Button(btns, text=u"删除".encode("utf-8"), command=self.on_del_key).pack(
            fill=tk.X, pady=2
        )
        ttk.Button(btns, text=u"复制".encode("utf-8"), command=self.on_copy_key).pack(
            fill=tk.X
        )

        self.var_rand_key = tk.BooleanVar()
        ttk.Checkbutton(
            f_key,
            text=u"随机使用 Key".encode("utf-8"),
            variable=self.var_rand_key,
            command=self.on_toggle_rand_key,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)

        ttk.Separator(f_key, orient=tk.HORIZONTAL).grid(
            row=3, column=0, columnspan=3, sticky=tk.EW, pady=8
        )

        ttk.Label(f_key, text=u"子域名".encode("utf-8")).grid(
            row=4, column=0, sticky=tk.W, pady=4
        )
        self.var_sub = tk.StringVar()
        self.cmb_sub = ttk.Combobox(
            f_key,
            textvariable=self.var_sub,
            values=[u"t%d" % i for i in range(8)],
            width=8,
            state="readonly",
        )
        self.cmb_sub.grid(row=4, column=1, sticky=tk.W, pady=4, padx=6)
        self.cmb_sub.bind("<<ComboboxSelected>>", self.on_sub_change)

        self.var_rand_sub = tk.BooleanVar()
        ttk.Checkbutton(
            f_key,
            text=u"随机子域名 t0–t7".encode("utf-8"),
            variable=self.var_rand_sub,
            command=self.on_toggle_rand_sub,
        ).grid(row=5, column=1, sticky=tk.W, pady=4)

        self.lbl_status = ttk.Label(f_key, text=u"", foreground="#0078d7")
        self.lbl_status.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=8)

        ttk.Label(
            f_key,
            text=u"Key 申请: https://console.tianditu.gov.cn/api/key （浏览器端）".encode("utf-8"),
            foreground="#666",
        ).grid(row=7, column=0, columnspan=3, sticky=tk.W)

        # ---- Tab: 图源 ----
        f_map = ttk.Frame(nb, padding=8)
        nb.add(f_map, text=u"图源管理".encode("utf-8"))
        ttk.Label(
            f_map,
            text=u"勾选 = 在底图窗口里隐藏该图源（全部底图都取消勾选则什么都不显示）"
                 .encode("utf-8"),
        ).pack(anchor=tk.W)
        self.lst_maps = tk.Listbox(f_map, height=12, selectmode=tk.MULTIPLE, width=50)
        self.lst_maps.pack(fill=tk.BOTH, expand=True, pady=6)
        self._map_rows = []  # (name, enabled_bool)
        self._fill_map_list()

        rowf = ttk.Frame(f_map)
        rowf.pack(fill=tk.X)
        ttk.Button(
            rowf,
            text=u"全部禁用".encode("utf-8"),
            command=lambda: self._maps_all(True),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            rowf,
            text=u"全部启用".encode("utf-8"),
            command=lambda: self._maps_all(False),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            rowf, text=u"重新载入清单".encode("utf-8"),
            command=self._fill_map_list,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            rowf, text=u"管理自定义图源…".encode("utf-8"),
            command=self.on_manage_xyz,
        ).pack(side=tk.LEFT, padx=12)
        ttk.Button(
            rowf, text=u"导入地图包(zip)".encode("utf-8"), command=self.on_import_zip
        ).pack(side=tk.RIGHT, padx=2)

        # ---- XYZ 取瓦片时的代理（对国内源默认直连，见下方说明） ----
        pf = ttk.LabelFrame(f_map, text=u"XYZ 图源代理".encode("utf-8"),
                            padding=(8, 6))
        pf.pack(fill=tk.X, pady=(8, 0))
        self.var_proxy = tk.StringVar()
        ttk.Entry(pf, textvariable=self.var_proxy, width=32).pack(side=tk.LEFT)
        ttk.Label(
            pf,
            text=(u"留空 = 直连（推荐）；auto = 读 http_proxy 环境变量或系统代理；"
                  u"也可以直接填 127.0.0.1:7890").encode("utf-8"),
            foreground="#666",
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(pf, text=u"应用".encode("utf-8"),
                   command=self.on_apply_proxy).pack(side=tk.RIGHT)

        # 底部
        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.lbl_global = ttk.Label(bf, text=u"", foreground="#0078d7")
        self.lbl_global.pack(side=tk.LEFT)
        ttk.Button(bf, text=u"保存".encode("utf-8"), command=self.on_save_all).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(bf, text=u"关闭".encode("utf-8"), command=self.destroy).pack(
            side=tk.RIGHT
        )

    def _select_tab(self, tab):
        """tab 可以是页签序号，也可以是页签标题（模糊匹配）"""
        if tab is None or tab == u"":
            return
        try:
            tabs = list(self.nb.tabs())
            idx = None
            if isinstance(tab, int):
                idx = tab
            else:
                want = _to_unicode(tab)
                for i, tid in enumerate(tabs):
                    if want in _to_unicode(self.nb.tab(tid, "text")):
                        idx = i
                        break
            if idx is not None and 0 <= idx < len(tabs):
                self.nb.select(tabs[idx])
        except Exception:
            pass

    def _add_map_row(self, prefix, name, disabled):
        """往列表里加一行；索引与 self._map_rows 一一对应（选中 = 禁用）"""
        if isinstance(name, str):
            name = name.decode("utf-8", "ignore")
        name = _to_unicode(name)
        full = prefix + name
        idx = len(self._map_rows)
        self._map_rows.append(name)
        self.lst_maps.insert(tk.END, full.encode("utf-8"))
        if name in disabled or full in disabled:
            self.lst_maps.selection_set(idx)

    def _fill_map_list(self):
        """列出所有可在底图窗口里出现的图源。

        三部分：省级节点（tianditu_province.json）、其他地图包
        （extra.json）、XYZ 瓦片源（内置 xyz.json + extra.json 里的模板
        + 用户自定义，统一由 xyz_sources 汇总）。
        """
        from tianditu_api import load_map_json

        self.lst_maps.delete(0, tk.END)
        self._map_rows = []
        self.conf = load_config()
        disabled = set(self.conf.get("disabledMaps") or [])

        for fname, prefix in (
            ("tianditu_province.json", u"[省] "),
            ("extra.json", u"[其他] "),
        ):
            data = load_map_json(fname)
            if not isinstance(data, dict):
                continue
            for group in data.keys():
                if _to_unicode(group).startswith(u"_"):
                    continue                     # _readme 之类的注释键，跳过
                for entry in data[group] or []:
                    if not isinstance(entry, dict):
                        continue
                    self._add_map_row(prefix, entry.get("name") or group,
                                      disabled)

        # XYZ 图源：名称与底图窗口里显示的完全一致，才能对上 disabledMaps
        try:
            import xyz_sources
            for gname, arr in xyz_sources.groups():
                for it in arr:
                    self._add_map_row(_to_unicode(gname) + u" · ",
                                      it.get("name") or it.get("id"),
                                      disabled)
        except Exception:
            pass

    def on_manage_xyz(self):
        """就地打开图源管理器，关掉后刷新列表"""
        try:
            import ui_xyz
            ui_xyz.show_manager(self)
        except Exception as e:
            self._status(self.lbl_global, u"打开图源管理器失败：%r" % e, err=True)
            return
        self._fill_map_list()
        self._status(self.lbl_global, u"图源清单已刷新")

    def on_apply_proxy(self):
        save_config({"xyzProxy": self.var_proxy.get().strip()})
        self.conf = load_config()
        self._status(self.lbl_global,
                     u"XYZ 代理已保存：%s" % (self.var_proxy.get().strip() or u"直连"))

    def _maps_all(self, disable):
        # 全选=全部禁用 / 全不选=全部启用
        if disable:
            self.lst_maps.select_set(0, tk.END)
        else:
            self.lst_maps.select_clear(0, tk.END)

    def _load_values(self):
        conf = self.conf
        self.var_key.set(conf.get("key") or u"")
        for k in conf.get("keyList") or []:
            ks = k if isinstance(k, unicode) else k.decode("utf-8", "ignore")  # noqa: F821
            self.lst_keys.insert(tk.END, ks.encode("utf-8"))
        self.var_rand_key.set(bool(conf.get("randomKey")))
        self.var_sub.set(conf.get("subdomain") or u"t0")
        self.var_rand_sub.set(bool(conf.get("randomSubdomain")))
        self.var_proxy.set(_to_unicode(conf.get("xyzProxy") or u""))
        self._sync_key_controls()
        self._sync_sub_controls()

    def _sync_key_controls(self):
        if self.var_rand_key.get():
            self.cmb_sub  # noop keep ref
            self.lst_keys.configure(state=tk.DISABLED)
            self.btn_check.configure(state=tk.DISABLED)
        else:
            self.lst_keys.configure(state=tk.NORMAL)
            self.btn_check.configure(state=tk.NORMAL)

    def _sync_sub_controls(self):
        if self.var_rand_sub.get():
            self.cmb_sub.configure(state=tk.DISABLED)
        else:
            self.cmb_sub.configure(state=tk.READONLY)

    def on_toggle_rand_key(self):
        save_config({"randomKey": self.var_rand_key.get()})
        self.conf = load_config()
        self._sync_key_controls()
        self._status(self.lbl_status, u"已保存随机 Key 设置")

    def on_toggle_rand_sub(self):
        save_config({"randomSubdomain": self.var_rand_sub.get()})
        self.conf = load_config()
        self._sync_sub_controls()
        self._status(self.lbl_status, u"已保存子域名设置")

    def on_sub_change(self, _evt=None):
        save_config({"subdomain": self.var_sub.get()})
        self._status(self.lbl_status, u"子域名 → %s" % self.var_sub.get())

    def on_check_save(self):
        key = self.var_key.get().strip()
        if not key:
            self._status(self.lbl_status, u"请输入 Key")
            return
        self._status(self.lbl_status, u"校验中…")
        self.update_idletasks()
        ok, msg = check_key(key)
        if not ok:
            self._status(self.lbl_status, msg, err=True)
            return
        conf = load_config()
        key_list = conf.get("keyList") or []
        if key not in key_list:
            key_list.append(key)
        save_config({"key": key, "keyList": key_list})
        self.conf = load_config()
        self.lst_keys.delete(0, tk.END)
        for k in self.conf.get("keyList") or []:
            ks = k if isinstance(k, unicode) else k.decode("utf-8", "ignore")  # noqa: F821
            self.lst_keys.insert(tk.END, ks.encode("utf-8"))
        self.var_key.set(u"")
        self._status(self.lbl_status, msg)

    def on_use_key(self):
        sel = self.lst_keys.curselection()
        if not sel:
            return
        # Listbox 存的是 bytes，需与 keyList 匹配
        raw = self.lst_keys.get(sel[0])
        if isinstance(raw, str):
            disp = raw.decode("utf-8", "ignore")
        else:
            disp = raw
        key_list = self.conf.get("keyList") or []
        # 优先完全匹配
        chosen = None
        for k in key_list:
            ks = k if isinstance(k, unicode) else k.decode("utf-8", "ignore")  # noqa: F821
            if ks == disp or k == raw:
                chosen = k
                break
        if chosen is None and sel[0] < len(key_list):
            chosen = key_list[sel[0]]
        if chosen is None:
            return
        save_config({"key": chosen})
        self.conf = load_config()
        self._status(self.lbl_status, u"已设为当前 Key: %s****" % disp[:8])

    def on_del_key(self):
        sel = self.lst_keys.curselection()
        if not sel:
            return
        idx = int(sel[0])
        conf = load_config()
        key_list = conf.get("keyList") or []
        if 0 <= idx < len(key_list):
            del key_list[idx]
            save_config({"keyList": key_list})
            self.conf = load_config()
            self.lst_keys.delete(0, tk.END)
            for k in self.conf.get("keyList") or []:
                ks = k if isinstance(k, unicode) else k.decode("utf-8", "ignore")  # noqa: F821
                self.lst_keys.insert(tk.END, ks.encode("utf-8"))
            self._status(self.lbl_status, u"已删除")

    def on_copy_key(self):
        sel = self.lst_keys.curselection()
        if not sel:
            return
        raw = self.lst_keys.get(sel[0])
        try:
            self.clipboard_clear()
            self.clipboard_append(raw)
            self._status(self.lbl_status, u"已复制到剪贴板")
        except Exception:
            self._status(self.lbl_status, u"复制失败", err=True)

    def on_import_zip(self):
        import zipfile

        from tkFileDialog import askopenfilename

        path = askopenfilename(
            title=u"选择地图包".encode("utf-8"),
            filetypes=[("ZIP", "*.zip"), ("All", "*.*")],
        )
        if not path:
            return
        import os
        import shutil

        import json as _json

        from tianditu_api import load_map_json  # noqa: F401

        maps_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")
        try:
            zf = zipfile.ZipFile(path, "r")
            names = [n for n in zf.namelist() if n.endswith(".json")]
            if not names:
                tkMessageBox.showwarning(
                    u"天地图 Tools", u"ZIP 中未找到 JSON 文件".encode("utf-8")
                )
                zf.close()
                return
            for n in names:
                base = os.path.basename(n)
                target = os.path.join(maps_dir, base)
                with zf.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            zf.close()
            self._fill_map_list()
            tkMessageBox.showinfo(
                u"天地图 Tools",
                (u"已导入:\n%s" % u"\n".join(names)).encode("utf-8"),
            )
        except Exception as e:
            tkMessageBox.showerror(
                u"天地图 Tools", (u"导入失败: %s" % e).encode("utf-8")
            )

    def on_save_all(self):
        disabled = []
        # 选中 = 禁用
        selected_idx = set(self.lst_maps.curselection())
        for i, name in enumerate(self._map_rows):
            if i in selected_idx:
                disabled.append(name)
        save_config(
            {
                "disabledMaps": disabled,
                "randomKey": self.var_rand_key.get(),
                "randomSubdomain": self.var_rand_sub.get(),
                "subdomain": self.var_sub.get(),
                "xyzProxy": self.var_proxy.get().strip(),
            }
        )
        self.conf = load_config()
        self._status(self.lbl_global, u"设置已保存")

    def _status(self, label, text, err=False):
        label.configure(
            text=text.encode("utf-8") if isinstance(text, unicode) else text,  # noqa: F821
            foreground="#c00" if err else "#0078d7",
        )


def show_settings(parent=None, tab=None):
    try:
        SettingsDialog(parent, tab)
    except Exception as e:
        try:
            tkMessageBox.showerror(
                u"天地图 Tools",
                (u"打开设置失败: %s" % e).encode("utf-8"),
            )
        except Exception:
            pass


def run_standalone(payload=None):
    """独立进程入口（由 ui_main.py 调用）。

    设置窗口自己负责读写 %APPDATA%\\TiandituTools\\config.json，
    因此不需要把结果回传主进程，返回空 dict 即可。
    payload 可带 {"tab": "图源管理"} 指定打开哪一页。
    """
    import Tkinter as tk

    root = tk.Tk()
    root.withdraw()
    dlg = SettingsDialog(root, (payload or {}).get("tab"))
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
    return {}
