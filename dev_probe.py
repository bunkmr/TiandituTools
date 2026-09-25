# -*- coding: utf-8 -*-
"""开发期探针：安装指定变体的加载项 -> 启动 ArcMap -> 精确判定失败模式。

判定比"进程是否存活"更严格，会同时识别两种失败：
  * EXIT   进程退出（记录退出码与时刻）
  * ABORT  出现 CRT 中止对话框（"Microsoft Visual C++ Runtime Library" /
           "Runtime Error!"），这类对话框会让进程挂住，仅看进程存活会误判为"稳定"

用法:
    python dev_probe.py <variant|-> <seconds> [reset_normal]

    variant   TIANDITU_VARIANT 取值(default/hidden/none)；"-" 表示直接用现有包
    seconds   观测秒数
    reset_normal  传 1 时，先把 Normal.mxt 备份移走，让 ArcMap 重建模板
"""
from __future__ import print_function

import ctypes
import datetime
import os
import shutil
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
NORMAL = os.path.join(os.environ.get("APPDATA", ""),
                      r"ESRI\Desktop10.4\ArcMap\Templates\Normal.mxt")

u32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindows = u32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowThreadProcessId = u32.GetWindowThreadProcessId
GetWindowTextW = u32.GetWindowTextW
GetClassNameW = u32.GetClassNameW
IsWindowVisible = u32.IsWindowVisible
PostMessageW = u32.PostMessageW
WM_COMMAND = 0x0111
IDOK = 1
ABORT_KEYS = (u"Runtime Error", u"Microsoft Visual C++", u"Visual C++ Runtime")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True).stdout.decode("gbk", "replace")


def arcmap_pids():
    out = sh(["tasklist", "/FI", "IMAGENAME eq ArcMap.exe", "/FO", "CSV", "/NH"])
    pids = set()
    for line in out.strip().splitlines():
        parts = line.split('","')
        if len(parts) >= 2 and "ArcMap" in parts[0]:
            pids.add(parts[1].strip('"'))
    return pids


def scan_abort_dialog(pids):
    """返回 ArcMap 进程下 CRT 中止对话框的句柄列表"""
    hits = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if str(pid.value) not in pids:
            return True
        cls = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls, 256)
        if cls.value != "#32770":          # 标准对话框类
            return True
        title = ctypes.create_unicode_buffer(512)
        GetWindowTextW(hwnd, title, 512)
        if any(k in title.value for k in ABORT_KEYS):
            hits.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return hits


def prepare(variant):
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(3)
    if variant and variant != "-":
        env = dict(os.environ)
        env["TIANDITU_VARIANT"] = variant
        r = subprocess.run([sys.executable, "build_addin.py"], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr).strip().splitlines()
        print("    打包:", tail[-1] if tail else "(无输出)")
    stamp = time.strftime("%H%M%S")
    os.makedirs(BAK, exist_ok=True)
    for base in (ADDINS, CACHE):
        p = os.path.join(base, GUID)
        if os.path.exists(p):
            shutil.move(p, os.path.join(BAK, "%s_%s_%s_%s"
                                        % (os.path.basename(base), GUID, variant or "cur", stamp)))
    os.makedirs(os.path.join(ADDINS, GUID), exist_ok=True)
    shutil.copy2(OUT, os.path.join(ADDINS, GUID, "TiandituTools.esriaddin"))
    if os.path.exists(LOG):
        os.remove(LOG)
    print("    已安装:", os.path.join(ADDINS, GUID, "TiandituTools.esriaddin"))


def reset_normal():
    if os.path.exists(NORMAL):
        dst = os.path.join(BAK, "Normal_%s.mxt" % time.strftime("%H%M%S"))
        shutil.copy2(NORMAL, dst)        # 先备份
        os.remove(NORMAL)                # 再删除，让 ArcMap 重建
        print("    Normal.mxt 已备份到", dst, "并移除（ArcMap 将重建）")
    else:
        print("    Normal.mxt 不存在")


def observe(seconds):
    p = subprocess.Popen([ARCMAP], creationflags=0x00000008)
    abort_at = None
    exit_at = None
    rc = None
    t = 0
    while t < seconds:
        time.sleep(1)
        t += 1
        rc = p.poll()
        if rc is not None and exit_at is None:
            exit_at = t
            break
        dlg = scan_abort_dialog(arcmap_pids())
        if dlg and abort_at is None:
            abort_at = t
            print("      [%3ds] !! 检测到 CRT 中止对话框" % t)
            for h in dlg:
                PostMessageW(h, WM_COMMAND, IDOK, 0)
    if exit_at is None:
        f = scan_abort_dialog(arcmap_pids())
        print("      [%3ds] 仍在运行 (中止对话框=%d)" % (t, len(f)))
    return {"exit_at": exit_at, "rc": rc, "abort_at": abort_at}


def phase(name, variant, seconds, reset):
    print("\n================ 阶段: %s ================" % name)
    if reset:
        reset_normal()
    prepare(variant)
    t0 = datetime.datetime.now()
    print("    启动于", t0.strftime("%H:%M:%S"), " 观测", seconds, "秒")
    r = observe(seconds)
    if r["exit_at"] is not None:
        print("    => 结果: 退出 @%ds, 退出码=%s (0x%X)"
              % (r["exit_at"], r["rc"], r["rc"] & 0xFFFFFFFF))
    elif r["abort_at"] is not None:
        print("    => 结果: CRT 中止对话框 @%ds（进程未按时退出）" % r["abort_at"])
    else:
        print("    => 结果: 稳定（%ds 内无退出、无中止对话框）" % seconds)
    print("    插件日志:", "有" if os.path.exists(LOG) else "无")
    if os.path.exists(LOG):
        print("      ", open(LOG, "rb").read().decode("utf-8", "replace").strip())
    gc = os.path.join(CACHE, GUID)
    print("    缓存解包:", sorted(os.listdir(gc)) if os.path.isdir(gc) else "(无)")
    subprocess.run(["taskkill", "/F", "/IM", "ArcMap.exe"], capture_output=True)
    time.sleep(2)
    return r


if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else "-"
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    reset = len(sys.argv) > 3 and sys.argv[3] == "1"
    phase("variant=%s reset_normal=%s" % (variant, reset), variant, secs, reset)
