# -*- coding: utf-8 -*-
"""验证「运行时创建工具条」是否安全 —— 昨天只验证了「启动时不创建」。

背景：A/B 实测 showInitially="true"（启动即自动创建工具条）会让 ArcMap 被 CRT 中止；
      改成 showInitially="false" 后启动稳定。但**用户在 自定义->工具条 里手动勾选**
      时同样会创建工具条。如果那条路径也崩，插件等于不可用。本脚本就测这条路径。

做法（全自动，不改任何配置）：
  1. 用现有包安装加载项（可还原移动，不删除）
  2. 启动 ArcMap，先观测启动阶段是否稳定
  3. 在工具条空白区右键 -> 弹出工具条列表 -> 递归 dump 所有菜单项（含子菜单）
  4. 找到名称含「天地图」的那一项，用真实鼠标点击启用
  5. 再观测 60 秒：是否出现 CRT 中止对话框 / 进程退出
  6. 截图存档

用法（ArcGIS 自带 Python 2.7 运行）:
    python dev_toolbar_test.py dump     只启动 + dump 菜单（不点击）
    python dev_toolbar_test.py click    启动 + dump + 点击启用 + 观测
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "TiandituTools.esriaddin")
GUID = "{A1B2C3D4-1234-5678-9ABC-DEF012345678}"
ADDINS = r"C:\Users\bunkr\Documents\ArcGIS\AddIns\Desktop10.4"
CACHE = r"C:\Users\bunkr\AppData\Local\ESRI\Desktop10.4\AssemblyCache"
BAK = os.path.join(ROOT, "_addin_removed_backup")
ARCMAP = r"C:\Program Files (x86)\ArcGIS\Desktop10.4\bin\ArcMap.exe"
LOG = os.path.join(os.environ.get("APPDATA", ""), "TiandituTools", "import_error.log")
SHOT = os.path.join(ROOT, "_tb_test.png")

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
u32.SetProcessDPIAware()      # 本机 3072x1920 @225%，不做 DPI 感知坐标会差 2 倍多

EnumWindows = u32.EnumWindows
EnumChildWindows = u32.EnumChildWindows
CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

ABORT_KEYS = (u"Runtime Error", u"Microsoft Visual C++", u"Visual C++ Runtime")
TARGET_KEY = u"\u5929\u5730\u56fe"          # 天地图


# --------------------------------------------------------------------------- utils
def mkdirp(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def run_cmd(cmd):
    """Py2.7 没有 subprocess.run"""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return (p.communicate()[0] or b"").decode("gbk", "replace")


def sh(cmd):
    return run_cmd(cmd)


def out(s):
    if isinstance(s, unicode):        # noqa: F821
        s = s.encode("utf-8")
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def pids_of(image="ArcMap.exe"):
    txt = sh(["tasklist", "/FI", "IMAGENAME eq %s" % image, "/FO", "CSV", "/NH"])
    res = set()
    for line in txt.strip().splitlines():
        parts = line.split('","')
        if len(parts) >= 2 and "ArcMap" in parts[0]:
            res.add(int(parts[1].strip('"')))
    return res


def wtext(hwnd):
    b = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, b, 512)
    return b.value


def wclass(hwnd):
    b = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, b, 256)
    return b.value


def wrect(hwnd):
    r = wintypes.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def find_windows(pid, cls=None, visible=True):
    res = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid:
            return True
        if visible and not u32.IsWindowVisible(hwnd):
            return True
        if cls and wclass(hwnd) != cls:
            return True
        res.append(hwnd)
        return True

    EnumWindows(CB(cb), 0)
    return res


def main_window(pid):
    """面积最大的可见顶层窗口 = ArcMap 主窗口"""
    best, area = None, 0
    for h in find_windows(pid):
        r = wrect(h)
        a = (r.right - r.left) * (r.bottom - r.top)
        if a > area:
            best, area = h, a
    return best


def scan_abort(pid):
    hits = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid:
            return True
        if wclass(hwnd) != "#32770":
            return True
        if any(k in wtext(hwnd) for k in ABORT_KEYS):
            hits.append(hwnd)
        return True

    EnumWindows(CB(cb), 0)
    return hits


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BI(ctypes.Structure):
    _fields_ = [("bmiHeader", BIH), ("bmiColors", wintypes.DWORD * 3)]


def ps_shot(path):
    """ArcGIS 的 Python 2.7 没装 PIL —— 用 .NET 截整个虚拟屏兜底"""
    ps1 = os.path.join(ROOT, "_ps_shot.ps1")
    if not os.path.isfile(ps1):
        return False
    r = run_cmd(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ps1, path])
    return os.path.isfile(path)


def screenshot(hwnd, path):
    try:
        from PIL import Image
    except ImportError:
        ok = ps_shot(path)
        out("    (无 PIL，改用 .NET 截屏: %s)" % ("成功" if ok else "失败"))
        return None
    r = wrect(hwnd)
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None
    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 2)
    bi = BI()
    bi.bmiHeader.biSize = ctypes.sizeof(BIH)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    return (w, h)


# --------------------------------------------------------------------------- install
def install():
    run_cmd(["taskkill", "/F", "/IM", "ArcMap.exe"])
    time.sleep(3)
    stamp = time.strftime("%H%M%S")
    mkdirp(BAK)
    for base in (ADDINS, CACHE):
        p = os.path.join(base, GUID)
        if os.path.exists(p):
            import shutil
            shutil.move(p, os.path.join(BAK, "%s_%s_tbtest_%s"
                                        % (os.path.basename(base), GUID, stamp)))
    import shutil
    mkdirp(os.path.join(ADDINS, GUID))
    shutil.copy2(OUT, os.path.join(ADDINS, GUID, "TiandituTools.esriaddin"))
    if os.path.exists(LOG):
        os.remove(LOG)
    out("    已安装 %s" % os.path.join(ADDINS, GUID, "TiandituTools.esriaddin"))


def descendants(root):
    rows = []

    def walk(h):
        kids = []

        def cb(c, _):
            kids.append(c)
            return True

        EnumChildWindows(h, CB(cb), 0)
        for c in kids:
            rows.append(c)
            walk(c)

    walk(root)
    return rows


def find_toolbars(hwnd):
    """ArcMap 的工具条是 XTPToolBar（MFC/Codejock）。返回 [(hwnd, title, rect)]"""
    res = []
    for c in descendants(hwnd):
        if wclass(c) == "XTPToolBar":
            r = wrect(c)
            if r.right - r.left > 10:
                res.append((c, wtext(c), r))
    return res


def close_popups(pid):
    for h in find_windows(pid, cls="#32768", visible=False):
        u32.PostMessageW(h, 0x0010, 0, 0)          # WM_CLOSE
    u32.keybd_event(0x1B, 0, 0, 0)                 # ESC
    u32.keybd_event(0x1B, 0, 2, 0)
    time.sleep(0.4)


# --------------------------------------------------------------------------- menu
MIIM_ID = 0x00000002
MIIM_SUBMENU = 0x00000004
MIIM_STRING = 0x00000040
MIIM_FTYPE = 0x00000100


class MENUITEMINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("fMask", wintypes.UINT),
                ("fType", wintypes.UINT), ("fState", wintypes.UINT),
                ("wID", wintypes.UINT), ("hSubMenu", wintypes.HMENU),
                ("hbmpChecked", wintypes.HBITMAP), ("hbmpUnchecked", wintypes.HBITMAP),
                ("dwItemData", ctypes.POINTER(wintypes.ULONG)),
                ("dwTypeData", wintypes.LPWSTR), ("cch", wintypes.UINT),
                ("hbmpItem", wintypes.HBITMAP)]


def menu_items(hmenu):
    """返回 [(idx, id, text, hsub)]"""
    u32.GetMenuItemCount.restype = ctypes.c_int
    n = u32.GetMenuItemCount(hmenu)
    res = []
    for i in range(n):
        mii = MENUITEMINFOW()
        mii.cbSize = ctypes.sizeof(MENUITEMINFOW)
        mii.fMask = MIIM_ID | MIIM_STRING | MIIM_SUBMENU | MIIM_FTYPE
        buf = ctypes.create_unicode_buffer(256)
        mii.dwTypeData = ctypes.cast(buf, wintypes.LPWSTR)
        mii.cch = 256
        if not u32.GetMenuItemInfoW(hmenu, i, True, ctypes.byref(mii)):
            continue
        res.append((i, mii.wID, buf.value, mii.hSubMenu))
    return res


def dump_menu(hmenu, depth=0, path=()):
    """递归 dump；返回 [(path, text, hsub)] 便于后续按路径点击"""
    rows = []
    for idx, mid, text, hsub in menu_items(hmenu):
        clean = text.replace(u"&", u"")
        rows.append((path + (idx,), clean, hsub))
        out("      " + "  " * depth + "[%d] id=%-6d %r%s"
            % (idx, mid, clean, "  <submenu>" if hsub else ""))
        if hsub:
            rows.extend(dump_menu(hsub, depth + 1, path + (idx,)))
    return rows


def right_click(hwnd, x, y):
    u32.ShowWindow(hwnd, 9)          # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    u32.SetCursorPos(x, y)
    time.sleep(0.2)
    u32.mouse_event(0x0008, 0, 0, 0, 0)      # RIGHTDOWN
    u32.mouse_event(0x0010, 0, 0, 0, 0)      # RIGHTUP


def left_click(x, y):
    u32.SetCursorPos(x, y)
    time.sleep(0.15)
    u32.mouse_event(0x0002, 0, 0, 0, 0)      # LEFTDOWN
    u32.mouse_event(0x0004, 0, 0, 0, 0)      # LEFTUP


def move_to(x, y):
    u32.SetCursorPos(x, y)


def click_menu_path(popup, path):
    """按索引路径依次展开子菜单并点击最后一项"""
    for k, idx in enumerate(path):
        hmenu = u32.GetMenu(popup) if k == 0 else None
        if hmenu is None:
            return False
        # 逐级取子菜单
        cur = u32.GetMenu(popup)
        for j in range(k):
            items = menu_items(cur)
            if path[j] >= len(items):
                return False
            cur = items[path[j]][3]
            if not cur:
                return False
        items = menu_items(cur)
        if idx >= len(items):
            return False
        r = wintypes.RECT()
        u32.GetMenuItemRect(popup, cur, idx, ctypes.byref(r))
        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        move_to(cx, cy)
        if k < len(path) - 1:
            time.sleep(0.9)              # 等子菜单展开
        else:
            time.sleep(0.3)
            left_click(cx, cy)
    return True


# --------------------------------------------------------------------------- observe
def observe(pid, seconds, label):
    t = 0
    abort_at = exit_at = rc = None
    while t < seconds:
        time.sleep(1)
        t += 1
        rc = None
        if pid not in pids_of():
            exit_at = t
            break
        hits = scan_abort(pid)
        if hits and abort_at is None:
            abort_at = t
            out("      [%3ds] !! CRT 中止对话框" % t)
            for h in hits:
                u32.PostMessageW(h, 0x0111, 1, 0)     # WM_COMMAND IDOK
    if exit_at is not None:
        out("    %s => 进程消失 @%ds" % (label, exit_at))
    elif abort_at is not None:
        out("    %s => CRT 中止 @%ds" % (label, abort_at))
    else:
        out("    %s => 稳定 %ds（无退出、无中止）" % (label, t))
    return {"exit_at": exit_at, "abort_at": abort_at}


# --------------------------------------------------------------------------- main
def _run():
    mode = sys.argv[1] if len(sys.argv) > 1 else "dump"
    out("===== 工具条启用测试 mode=%s =====" % mode)
    install()

    out("\n-- 启动 ArcMap --")
    p = subprocess.Popen([ARCMAP], creationflags=0x00000008)
    r1 = observe(p.pid, 45, "启动阶段")
    if r1["exit_at"] or r1["abort_at"]:
        out("启动阶段就失败，测试终止")
        return 1

    hwnd = main_window(p.pid)
    if not hwnd:
        out("!! 找不到 ArcMap 主窗口")
        return 1
    r = wrect(hwnd)
    out("    主窗口 hwnd=%s title=%r rect=%s" % (hwnd, wtext(hwnd), (r.left, r.top, r.right, r.bottom)))
    screenshot(hwnd, os.path.join(ROOT, "_tb_before.png"))
    if mode == "probe":
        r2 = observe(p.pid, 60, "续观")
        out("\n-- 工具条 --")
        for h, t, rr in find_toolbars(hwnd):
            if t not in (u"\u4e3b\u83dc\u5355",):
                out("    %r %dx%d @(%d,%d)" % (t, rr.right - rr.left,
                                               rr.bottom - rr.top, rr.left, rr.top))
        screenshot(hwnd, os.path.join(ROOT, "_tb_final.png"))
        out("\n-- 插件日志 --")
        if os.path.exists(LOG):
            out(open(LOG, "rb").read().decode("utf-8", "replace").strip())
        else:
            out("    (无)")
        return 0

    # 从真实工具条几何推导"空白区"候选点（比猜坐标可靠）
    tb = find_toolbars(hwnd)
    out("\n-- 发现的工具条 --")
    for h, t, rr in tb:
        out("    cls=XTPToolBar title=%-12r rect=(%d,%d,%d,%d) size=%dx%d"
            % (t, rr.left, rr.top, rr.right, rr.bottom,
               rr.right - rr.left, rr.bottom - rr.top))
    cands = []
    for h, t, rr in tb:
        if t in (u"\u5de5\u5177", u"\u6807\u51c6\u5de5\u5177"):      # 工具 / 标准工具
            cands.append((rr.right - 40, (rr.top + rr.bottom) // 2))
    # 兜底：主窗口顶部逐行扫
    for dy in (40, 60, 80, 100, 120):
        cands.append((r.right - 120, r.top + dy))

    popup = None
    for (x, y) in cands:
        out("\n-- 右键 (%d,%d) --" % (x, y))
        right_click(hwnd, x, y)
        time.sleep(1.5)
        popups = find_windows(p.pid, cls="#32768", visible=False)
        if popups:
            popup = popups[0]
            out("    弹出菜单 hwnd=%s" % popup)
            break
        out("    没弹出，换下一个点")
    if popup is None:
        out("!! 所有候选点都没弹出菜单")
        screenshot(hwnd, os.path.join(ROOT, "_tb_nomenu.png"))
        return 1
    rows = dump_menu(u32.GetMenu(popup))
    if not rows:
        # GetMenu 对 track popup 可能返回空，改用 hwnd 作为 hmenu
        rows = dump_menu(popup)

    target = None
    for path, text, hsub in rows:
        if TARGET_KEY in text:
            target = (path, text)
            break
    if not target:
        out("!! 菜单里没找到含「天地图」的项")
        u32.PostMessageW(popup, 0x0010, 0, 0)
        run_cmd(["taskkill", "/F", "/PID", str(p.pid)])
        return 1
    out("    目标项: %r  path=%s" % (target[1], target[0]))

    if mode == "dump":
        out("\n(dump 模式，不点击)")
        u32.PostMessageW(popup, 0x0010, 0, 0)
        run_cmd(["taskkill", "/F", "/PID", str(p.pid)])
        return 0

    out("\n-- 点击启用 --")
    click_menu_path(popup, target[0])
    time.sleep(3)
    out("    点击后截图")
    screenshot(hwnd, os.path.join(ROOT, "_tb_after.png"))

    r2 = observe(p.pid, 60, "启用工具条后")

    gc = os.path.join(CACHE, GUID)
    out("    缓存解包: %s" % (sorted(os.listdir(gc)) if os.path.isdir(gc) else "(无)"))
    out("    插件日志: %s" % ("有" if os.path.exists(LOG) else "无"))
    if os.path.exists(LOG):
        out(open(LOG, "rb").read().decode("utf-8", "replace").strip())

    screenshot(hwnd, os.path.join(ROOT, "_tb_final.png"))
    run_cmd(["taskkill", "/F", "/IM", "ArcMap.exe"])
    return 0


def main():
    """无论如何都要收尾：测试结束必杀 ArcMap，避免留下挂住的进程"""
    try:
        return _run()
    finally:
        run_cmd(["taskkill", "/F", "/IM", "ArcMap.exe"])
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
