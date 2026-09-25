# -*- coding: utf-8 -*-

"""配置读写：JSON 存储于 %APPDATA%\\TiandituTools\\config.json"""

from __future__ import print_function

import os as _os, sys as _sys
_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import io
import json
import os

try:
    import random
except ImportError:
    random = None


DEFAULTS = {
    "key": u"",
    "keyList": [],
    "randomKey": False,
    "subdomain": u"t0",
    "randomSubdomain": True,
    "disabledMaps": [],
    "sd_tk": u"",
    # ---- 自定义 XYZ 图源 ----
    #: 用户自己添加的 XYZ 瓦片源（结构见 xyz_sources.normalize）
    "xyzSources": [],
    #: XYZ 取瓦片时是否走系统代理。空 = 直连（默认，天地图/高德/Esri 都不需要代理）；
    #: "auto" = 读 http_proxy / HTTP_PROXY 环境变量（dev-sidecar 这类本机代理
    #: 通常会把端口写在那里）；也可以直接填 "127.0.0.1:56991"。
    "xyzProxy": u"",
    # ---- 微信公众号（帮助页「关于」区）。已上线，可在界面里就地改 ----
    "wechatName": u"bunkr",
    "wechatArticleUrl": u"https://mp.weixin.qq.com/s/robaTWwtKVXDMGTgr5GCug",
    "wechatTip": u"",
}


def _config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, u"TiandituTools")
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def config_path():
    return os.path.join(_config_dir(), u"config.json")


def load_config():
    data = dict(DEFAULTS)
    path = config_path()
    if os.path.isfile(path):
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    data[k] = v
        except (ValueError, IOError, OSError):
            pass
    if not isinstance(data.get("keyList"), list):
        data["keyList"] = []
    if not isinstance(data.get("disabledMaps"), list):
        data["disabledMaps"] = []
    return data


def save_config(data):
    path = config_path()
    merged = load_config()
    merged.update(data)
    with io.open(path, "w", encoding="utf-8") as f:
        text = json.dumps(merged, ensure_ascii=False, indent=2)
        if not isinstance(text, unicode):  # noqa: F821 — py2 only
            text = text.decode("utf-8")
        f.write(text)
    return merged


def get_key():
    """返回当前使用的 Key（支持随机多 Key）"""
    conf = load_config()
    key_list = [k for k in conf.get("keyList") or [] if k]
    if conf.get("randomKey") and key_list and random is not None:
        return random.choice(key_list)
    key = conf.get("key") or u""
    if not key and key_list:
        key = key_list[0]
    return key


def get_subdomain():
    conf = load_config()
    if conf.get("randomSubdomain") and random is not None:
        return u"t%d" % random.randint(0, 7)
    sub = conf.get("subdomain") or u"t0"
    if sub not in [u"t%d" % i for i in range(8)]:
        sub = u"t0"
    return sub


def map_enabled(map_name):
    conf = load_config()
    return map_name not in (conf.get("disabledMaps") or [])
