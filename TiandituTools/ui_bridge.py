# -*- coding: utf-8 -*-
"""ui_bridge —— 把 Tkinter 界面放到**独立进程**里运行（ArcMap 进程内不碰 Tkinter）。

为什么必须这样做（社区与官方 FAQ 实证）：
    ArcMap 内部有一段代码负责把 Tkinter 的消息循环并入主消息循环，另有一段
    代码（地理处理 Python 窗口）会覆盖同一数据结构（疑似 vtable 指针被破坏）。
    因此在 ArcMap **进程内**调度 Tkinter，会让 ArcMap 内部结构损坏并被 CRT
    强制中止（症状即 "This application has requested the Runtime to terminate
    it in an unusual way."）。
    通用解法：界面放进独立进程，ArcMap 进程只负责“起进程 / 等结果 / 应用结果”。

本模块**不 import Tkinter**，可以安全地在 ArcMap 进程内使用。

对外接口：
    find_python()                    -> 找到可用的 ArcGIS Python，失败返回 None
    run_ui(mode, payload=None)       -> 弹出界面并返回结果 dict；取消/失败返回 None
    ui_log(text)                     -> 写诊断日志
"""

from __future__ import print_function

import io
import json
import os
import subprocess
import sys
import tempfile
import time

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# 候选解释器：ArcGIS 自带 Python 2.7（保证带 Tkinter / ttk）。
# pythonw.exe 优先 —— 不闪控制台窗口。
_PY_CANDIDATES = [
    r"C:\Python27\ArcGIS10.10\pythonw.exe",
    r"C:\Python27\ArcGIS10.8\pythonw.exe",
    r"C:\Python27\ArcGIS10.7\pythonw.exe",
    r"C:\Python27\ArcGIS10.6\pythonw.exe",
    r"C:\Python27\ArcGIS10.5\pythonw.exe",
    r"C:\Python27\ArcGIS10.4\pythonw.exe",
    r"C:\Python27\ArcGIS10.3\pythonw.exe",
    r"C:\Python27\ArcGIS10.2\pythonw.exe",
    r"C:\Python27\ArcGIS10.1\pythonw.exe",
    r"C:\Python27\ArcGIS10.10\python.exe",
    r"C:\Python27\ArcGIS10.8\python.exe",
    r"C:\Python27\ArcGIS10.7\python.exe",
    r"C:\Python27\ArcGIS10.6\python.exe",
    r"C:\Python27\ArcGIS10.5\python.exe",
    r"C:\Python27\ArcGIS10.4\python.exe",
    r"C:\Python27\ArcGIS10.3\python.exe",
    r"C:\Python27\ArcGIS10.2\python.exe",
    r"C:\Python27\ArcGIS10.1\python.exe",
    r"C:\Python27\pythonw.exe",
    r"C:\Python27\python.exe",
]

PY2 = sys.version_info[0] == 2
CREATE_NO_WINDOW = 0x08000000     # Windows: 不创建控制台窗口
UI_TIMEOUT = 1800                 # 界面最长打开时间（秒）


def ui_log(text):
    """把诊断信息写到 %APPDATA%\\TiandituTools\\import_error.log"""
    try:
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                         "TiandituTools")
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(os.path.join(d, "import_error.log"), "ab") as f:
            f.write((u"%s\n" % text).encode("utf-8", "ignore"))
    except Exception:
        pass


def find_python():
    """返回一个存在的 ArcGIS Python 解释器路径；找不到返回 None

    优先用当前进程的解释器（ArcMap 内的 sys.executable 就是 ArcGIS 的
    python.exe），其次才回落到候选清单 —— 这样多版本/非默认安装路径也能命中。
    """
    exe = getattr(sys, "executable", "") or ""
    if exe:
        d = os.path.dirname(exe)
        for name in ("pythonw.exe", "python.exe"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    for p in _PY_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def _pump_until_exit(proc, timeout):
    """等待子进程结束。

    【不要在这里抽消息！】历史上这里调用过 pythoncom.PumpWaitingMessages()。
    实测（ArcMap 10.4.1 / Win11）：在加载项 onClick 回调里抽消息，会让 ArcMap
    重入自己的消息循环，约 20~30 秒后弹出「ArcGIS for Desktop 遇到严重的应用
    程序错误，无法继续」，随后进程以 0xFFFFFFFF 退出（CRT abort）。
    而且事件日志里**没有** Application Error 记录，说明是主动 abort。

    所以这里只做纯等待。真正避免「未响应」的办法见下面
    run_ui_detached()：让 ArcMap 主线程根本不等待。
    """
    deadline = time.time() + timeout if timeout else None
    while proc.poll() is None:
        if deadline is not None and time.time() > deadline:
            ui_log("ui_bridge: 界面运行超过 %ss，强制结束" % timeout)
            try:
                proc.kill()
            except Exception:
                pass
            return False
        time.sleep(0.05)
    return True


_running = False


def run_ui(mode, payload=None):
    """在独立进程中运行 Tkinter 界面。

    mode: "settings" | "basemap" | "search"
    返回：子进程写回的 dict；用户取消 / 出错 / 找不到解释器 -> None
    """
    global _running
    if _running:
        ui_log("ui_bridge: 已有一个界面在运行，忽略重复请求 mode=%s" % mode)
        return None

    py = find_python()
    if not py:
        ui_log("ui_bridge: 未找到 ArcGIS Python 2.7 解释器（无法运行界面）")
        return None

    main_py = os.path.join(_PKG_DIR, "ui_main.py")
    if not os.path.isfile(main_py):
        ui_log("ui_bridge: 缺少 ui_main.py")
        return None

    tmpd = tempfile.mkdtemp(prefix="tianditu_ui_")
    in_path = os.path.join(tmpd, "in.json")
    out_path = os.path.join(tmpd, "out.json")

    try:
        data = json.dumps(payload or {}, ensure_ascii=False)
        with io.open(in_path, "wb") as f:
            f.write(data.encode("utf-8"))
    except Exception as e:
        ui_log("ui_bridge: 写入参数失败 %s" % e)
        return None

    cmd = [py, main_py, mode, in_path, out_path]
    ui_log("ui_bridge: run %s" % " ".join(cmd))
    _running = True
    try:
        proc = subprocess.Popen(cmd, cwd=_PKG_DIR, creationflags=CREATE_NO_WINDOW)
        _pump_until_exit(proc, UI_TIMEOUT)
        rc = proc.poll()
        ui_log("ui_bridge: exit=%s" % rc)
    except Exception as e:
        ui_log("ui_bridge: 启动界面进程失败 %s" % e)
        return None
    finally:
        _running = False

    if not os.path.isfile(out_path):
        ui_log("ui_bridge: 界面未产生结果文件（用户取消或界面启动失败）")
        return None
    try:
        with io.open(out_path, "rb") as f:
            raw = f.read().decode("utf-8")
        result = json.loads(raw)
        ui_log("ui_bridge: result=%s" % raw[:400])
        return result
    except Exception as e:
        ui_log("ui_bridge: 解析结果失败 %s" % e)
        return None


def run_ui_detached(mode, payload=None):
    """**非阻塞**地弹出界面：起进程后立刻返回，ArcMap 主线程不等待。

    为什么这是首选
    --------------
    在 onClick 里长时间阻塞 ArcMap 主线程，会让窗口被 Windows 标成“未响应”，
    而一旦为了“保持响应”去抽消息，又会重入 ArcGIS 消息循环并让 ArcMap
    弹「遇到严重的应用程序错误」后中止（见 _pump_until_exit 的注释）。

    所以最稳的做法是：ArcMap 只负责“起进程”，剩下的事**全在界面进程里做完**。
    界面进程拿到的结果由 ui_main 自己应用（底图走 ArcObjects + AppROT，
    直接操作正在运行的 ArcMap，不需要 ArcMap 主线程参与）。

    返回 True 表示界面进程已成功启动。
    """
    py = find_python()
    if not py:
        ui_log("ui_bridge: 未找到 ArcGIS Python 2.7 解释器（无法运行界面）")
        _fallback_msgbox(u"未找到 ArcGIS Python 2.7 解释器，无法打开界面。")
        return False

    main_py = os.path.join(_PKG_DIR, "ui_main.py")
    if not os.path.isfile(main_py):
        ui_log("ui_bridge: 缺少 ui_main.py")
        _fallback_msgbox(u"缺少 ui_main.py，无法打开界面。")
        return False

    tmpd = tempfile.mkdtemp(prefix="tianditu_ui_")
    in_path = os.path.join(tmpd, "in.json")
    out_path = os.path.join(tmpd, "out.json")
    try:
        data = json.dumps(payload or {}, ensure_ascii=False)
        with io.open(in_path, "wb") as f:
            f.write(data.encode("utf-8"))
    except Exception as e:
        ui_log("ui_bridge: 写入参数失败 %s" % e)
        return False

    cmd = [py, main_py, mode, in_path, out_path]
    ui_log("ui_bridge: run(detached) %s" % " ".join(cmd))
    try:
        subprocess.Popen(cmd, cwd=_PKG_DIR, creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        ui_log("ui_bridge: 启动界面进程失败 %s" % e)
        _fallback_msgbox(u"启动界面进程失败：\n%s" % e)
        return False
    return True


def _fallback_msgbox(text):
    """ArcMap 进程内的兜底提示（官方 MessageBox，绝不 Tkinter）"""
    try:
        import pythonaddins
        pythonaddins.MessageBox(text, u"天地图 Tools", 48)
    except Exception:
        ui_log("ui_bridge: 无法提示: %s" % text)
