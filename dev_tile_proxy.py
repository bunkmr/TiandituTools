# -*- coding: utf-8 -*-
"""本地日志代理：把 ArcMap 请求天地图时**真正发出的 URL** 记下来。

为什么需要它
------------
天地图的 GetCapabilities 里**没有** <ResourceURL /> 瓦片模板，所以 ArcMap 得
自己拼 GetTile 请求。我们怀疑它把连接串里的 `tk=KEY` 丢了（实测：带 tk 的
GetTile 返回 200 image/jpg；不带 tk 直接 403），于是图层在、画布空白。

这个代理把 ArcMap 的请求原样转发给天地图，并把 URL 全量记到 _tile_proxy.log。
如果日志里的 GetTile 没有 tk —— 病因就坐实了。

用法：python dev_tile_proxy.py [端口] [秒数]
"""
from __future__ import print_function

import io
import os
import sys
import time
import urllib
import urllib2
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

UPSTREAM = "https://t3.tianditu.gov.cn"
KEY = "215a6b9d9f7cba63e8e128dfb4042419"
LOG = r"D:\Work\projects\arcmap\_tile_proxy.log"

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 180


def log(text):
    try:
        with io.open(LOG, "ab") as f:
            f.write((u"%s\n" % text).encode("utf-8", "ignore"))
    except Exception:
        pass
    try:
        print(u"%s" % text)
        sys.stdout.flush()
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass                     # 关掉默认的 stderr 噪音

    def _serve(self, body=None):
        if body is None:
            body = b""
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        ctype = getattr(self, "_ctype", "text/xml; charset=UTF-8")
        self.send_header("Content-Type", ctype)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        raw_path = self.path                      # bytes（转发用）
        path = raw_path.decode("utf-8", "replace")  # unicode（打日志用）
        low = path.lower()
        kind = ("GetCapabilities" if "getcapabilities" in low else
                "GetTile" if "gettile" in low else "other")
        has_tk = "tk=" in low
        tkval = path.split("tk=")[1].split("&")[0] if has_tk else u"-"
        log(u"[%s] %s   tk=%s\n     %s"
            % (kind, u"有 tk" if has_tk else u"**没有 tk**", tkval, path))

        url = UPSTREAM + raw_path
        if "tk=" not in url.lower():
            url += "&tk=" + KEY
        data = None
        try:
            req = urllib2.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.tianditu.gov.cn/"})
            r = urllib2.urlopen(req, timeout=25)
            data = r.read()
            self._ctype = r.headers.get("Content-Type") or "application/octet-stream"
            if kind == "GetTile":
                log(u"     -> 上游 %s  %s  %d bytes"
                    % (r.getcode(), self._ctype, len(data)))
        except Exception as e:
            log(u"     -> 上游失败 %r" % (e,))
            try:
                self.send_error(502, "upstream %r" % (e,))
            except Exception:
                pass
            return
        self._serve(data)

    def do_POST(self):
        self.do_GET()


def main():
    if os.path.isfile(LOG):
        try:
            os.remove(LOG)
        except Exception:
            pass
    log(u"=== 代理启动 127.0.0.1:%d -> %s （%ds）===" % (PORT, UPSTREAM, SECONDS))
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    srv.timeout = 1
    t0 = time.time()
    while time.time() - t0 < SECONDS:
        srv.handle_request()
    log(u"=== 代理结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
