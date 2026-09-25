# -*- coding: utf-8 -*-
"""最小验证：`import arcpy` + 无控制台 → 是否必然触发 DFORRT 的
"Visual Fortran run-time error" 模态对话框（进程随即卡死）。

假设
----
helper 进程用 CREATE_NO_WINDOW 起（**没有控制台**）：
  * import arcpy 会加载 arcgisscripting -> Geoprocessing/Raster 栈 -> DFORRT.dll
  * DFORRT 想往 unit 0 (CONOUT$) 写一条诊断 —— 但没有控制台，写失败
  * 于是 severe(38) 弹模态对话框，进程永久卡住（正是我们看到的孤儿窗口）

对照组：给同一条命令一个真控制台（CREATE_NEW_CONSOLE），写入成功，
诊断被打印出来但不再中止。

用法：python dev_arcpy_fortran_test.py
"""
from __future__ import print_function

import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime

PYW = r"C:\Python27\ArcGIS10.4\pythonw.exe"
PY = r"C:\Python27\ArcGIS10.4\python.exe"
TMP = r"D:\Work\projects\arcmap\_fortran"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32


def log(*a):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"),
                       " ".join(str(x) for x in a)))
    sys.stdout.flush()


def alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def fortran_dialog_pids():
    """返回所有标题含 Fortran 的窗口所属 pid"""
    out = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, l):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, buf, n + 1)
                if "Fortran" in buf.value:
                    pid = ctypes.c_ulong()
                    u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    out.append((pid.value, buf.value))
        return True

    u32.EnumWindows(CB(cb), 0)
    return out


def case(tag, exe, source, flags):
    script = os.path.join(TMP, "%s.py" % tag)
    with open(script, "w") as f:
        f.write(source)
    log("---- 用例 %s：%s flags=0x%X" % (tag, os.path.basename(exe), flags))
    p = subprocess.Popen([exe, script], creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("     pid=%d" % p.pid)
    hit = None
    for i in range(40):
        time.sleep(1)
        for pid, title in fortran_dialog_pids():
            if pid == p.pid:
                hit = title
                break
        if hit:
            break
        if not alive(p.pid):
            break
    up = alive(p.pid)
    dlgs = [t for pid, t in fortran_dialog_pids() if pid == p.pid]
    log("     结果: alive=%-5s Fortran对话框=%s" % (up, dlgs or "无"))
    try:
        subprocess.call(["taskkill", "/F", "/PID", str(p.pid)],
                        creationflags=CREATE_NO_WINDOW,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return bool(dlgs)


def main():
    if not os.path.isdir(TMP):
        os.makedirs(TMP)

    src_arcpy = ("import sys, time\n"
                 "open(r'%s\\arcpy_ran.txt','w').write('import arcpy ok\\n')\n"
                 "import arcpy\n"
                 "open(r'%s\\arcpy_ran.txt','a').write('arcpy imported\\n')\n"
                 "time.sleep(120)\n" % (TMP, TMP))
    src_sleep = ("import time\n"
                 "open(r'%s\\sleep_ran.txt','w').write('no arcpy\\n')\n"
                 "time.sleep(120)\n" % TMP)

    results = {}
    results["A pythonw + 无控制台 + import arcpy"] = case(
        "a_arcpy_nowin", PYW, src_arcpy, CREATE_NO_WINDOW)
    results["B pythonw + 无控制台 + 不 import arcpy"] = case(
        "b_sleep_nowin", PYW, src_sleep, CREATE_NO_WINDOW)
    results["C pythonw + 新控制台 + import arcpy"] = case(
        "c_arcpy_console", PYW, src_arcpy, CREATE_NEW_CONSOLE)
    results["D python.exe + 无控制台 + import arcpy"] = case(
        "d_arcpy_nowin_exe", PY, src_arcpy, CREATE_NO_WINDOW)

    log("")
    log("=== 结论 ===")
    for k, v in results.items():
        log("   %-42s 触发 Fortran 对话框: %s" % (k, "是" if v else "否"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
