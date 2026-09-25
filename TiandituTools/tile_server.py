# -*- coding: utf-8 -*-
"""独立进程的天地图 WMTS 中转服务。

为什么要独立进程（实测踩出来的）
================================
一开始中转是跑在 **ArcMap 进程内的守护线程** 里的，前 8 张瓦片一切正常，
然后就出事：

    绘制几秒后，ArcMap 主线程不再响应；
    netstat 显示 ArcMap 自己连着 127.0.0.1:<中转端口>，状态永远停在 SYN_SENT；
    中转端口仍是 LISTENING，但 accept 队列满了、新 SYN 被内核静默丢弃 ——
    也就是说**中转的 accept 循环不再运行了**。

ArcMap 的瓦片请求因此永远等不到应答，绘制线程卡死，主线程跟着假死，
再往后进程被杀 —— 用户看到的正是「能加载、但不能放大」。

把服务器放到独立进程后：
  * ArcMap 进程里再也不跑 HTTP 服务器线程，不碰它的消息循环和 GIL；
  * 端口固定（默认 17817），**重启 ArcMap 后旧文档里的图层依然能出图**
    （以前端口每次随机，重启后图层连的还是老端口，必然全白）；
  * 服务器万一挂了，ArcMap 得到的是「连接被拒绝」这种**快速失败**，
    不会像 SYN_SENT 那样无限等待。

端口约定
--------
* 默认 17817，被占用就依次试 17818..17827；
* 实际端口写在 ``%APPDATA%\\TiandituTools\\tile_proxy.port``；启动前先 ping
  该端口，是本服务的实例就直接复用，避免重复起进程。

用法
----
    <ArcGIS pythonw.exe> tile_server.py [起始端口]

不 import arcpy、不 import Tkinter，纯标准库。
"""
from __future__ import print_function

import io
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import tile_proxy                                          # noqa: E402

_LOG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                        "TiandituTools")
_PORT_FILE = os.path.join(_LOG_DIR, "tile_proxy.port")
_HEARTBEAT = os.path.join(_LOG_DIR, "tile_server_hb.log")

DEFAULT_PORTS = list(range(17817, 17828))


def _write_port(port):
    try:
        if not os.path.isdir(_LOG_DIR):
            os.makedirs(_LOG_DIR)
        with io.open(_PORT_FILE, "w", encoding="utf-8") as f:
            f.write(u"%d %d\n" % (port, os.getpid()))
    except Exception:
        pass


def _key_from_config():
    """直接从 config.json 读 tk（服务器进程自己读，不用 ArcMap 传）"""
    try:
        import json
        p = os.path.join(_LOG_DIR, "config.json")
        if os.path.isfile(p):
            with io.open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (data.get("key") or u"").strip()
    except Exception:
        pass
    return u""


def _heartbeat_loop():
    """每 10 秒写一次心跳 —— 事后能判断「服务器到底还在不在」"""
    while True:
        time.sleep(10)
        try:
            st = tile_proxy.stats()
            with io.open(_HEARTBEAT, "a", encoding="utf-8") as f:
                f.write(u"[%s] alive port=%s tiles=%s cached=%s err=%s\n"
                        % (time.strftime("%H:%M:%S"), st["port"], st["tiles"],
                           st["cached"], st["errors"]))
        except Exception:
            pass


def main():
    # **不要**在这里碰 sys.stdout：正式路径是用 pythonw.exe 起的，没有控制台，
    # `io.open(1, ...)` 会抛 IOError(Bad file descriptor) 让进程秒退 ——
    # 结果就是"独立中转起不来，悄悄退回进程内中转"，然后照样卡死。
    # 所以只在真有控制台时才接管 stdout，失败一律忽略。
    try:
        sys.stdout = io.open(1, "w", encoding="utf-8", closefd=False)
    except Exception:
        pass

    start_port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORTS[0]
    ports = [start_port] + [p for p in DEFAULT_PORTS if p != start_port]

    key = _key_from_config()
    port = 0
    for p in ports:
        port = tile_proxy.start(key=key, prefer_port=p)
        if port:
            break
    if not port:
        tile_proxy.log(u"!!! 中转服务起不来（端口全被占）")
        return 1

    _write_port(port)
    tile_proxy.log(u"=== 独立中转进程已就绪 pid=%s key=%s"
                   % (os.getpid(), u"有" if key else u"无"))
    try:
        import threading
        th = threading.Thread(target=_heartbeat_loop, name="TileProxyHeartbeat")
        th.daemon = True
        th.start()
    except Exception:
        pass

    # 阻塞在这里直到被杀。用 tile_proxy 里的 serve_forever。
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        tile_proxy.stop()
        try:
            os.remove(_PORT_FILE)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    # pythonw.exe 下没有控制台，异常会**静默**吞掉、进程直接消失，事后完全查不到。
    # 所以这里兜一层，把 traceback 写进文件。
    try:
        _rc = main()
    except Exception:
        import traceback
        try:
            tb = traceback.format_exc()
            if isinstance(tb, bytes):
                tb = tb.decode("utf-8", "replace")
            if not os.path.isdir(_LOG_DIR):
                os.makedirs(_LOG_DIR)
            with io.open(os.path.join(_LOG_DIR, "tile_server_err.log"),
                         "a", encoding="utf-8") as f:
                f.write(u"%s\n%s\n" % (time.strftime("%H:%M:%S"), tb))
        except Exception:
            pass
        _rc = 1
    sys.exit(_rc)
