# -*- coding: utf-8 -*-
"""帮助窗口（Tkinter，只在独立进程里跑）。

五个页签：快速上手 / 图源说明 / 自定义 XYZ / 常见问题 / 关于。

三个"踩过才知道"的约束，改这个文件前先看：
  1. 页眉图**必须是 GIF**：ArcMap 自带的 Tk 8.5，PhotoImage 不认 PNG
     （实测 TclError: couldn't recognize data）。所以页眉用
     images/help_logo.gif，不是 help_logo.png。
  2. 二维码位置是**预留的**：微信文章还没发布，config 里的
     wechatName / wechatArticleUrl 默认为空。空的时候界面显示占位提示 +
     一张占位二维码图（images/wechat_qr.gif），并且允许就地填写保存 ——
     这样文章发出来那天，用户自己贴一下链接就行，不用等插件升级。
     真二维码做好后，用同名文件覆盖 images/wechat_qr.gif 即可。
  3. 本模块只在独立进程里被 import（见 ui_main.py 的 mode="help"），
     绝不能出现在 ArcMap 进程里 —— Tkinter 进 ArcMap 进程会让它被
     CRT 强制中止。

本模块不 import arcpy、不 import layer_manager。
"""

from __future__ import print_function

import os as _os
import sys as _sys

_pkg = _os.path.dirname(_os.path.abspath(__file__))
if _pkg not in _sys.path:
    _sys.path.insert(0, _pkg)

import Tkinter as tk
import tkMessageBox
import ttk

from config import load_config, save_config
from tianditu_api import _to_unicode
import ui_util

try:
    import _build_info as _bi                     # 打包时由 build_addin.py 注入
    VERSION = _to_unicode(getattr(_bi, "VERSION", u"0.8.0"))
    BUILD_DATE = _to_unicode(getattr(_bi, "DATE", u""))
except Exception:
    VERSION = u"0.8.0"                            # 与 build_addin.py 的 VERSION 保持一致
    BUILD_DATE = u""

IMAGES = _os.path.join(_pkg, "images")
KEY_URL = u"https://console.tianditu.gov.cn/api/key"


def _u(v):
    return _to_unicode(v)


def _enc(v):
    """Tkinter(py2) 一律喂 utf-8 字节串 —— 与工程里其它 ui_* 的写法一致"""
    s = _u(v)
    return s.encode("utf-8")


def _img_path(name):
    return _os.path.join(IMAGES, name)


# ---------------------------------------------------------------------------
# 帮助正文。标记约定（_fill 解析）：
#     "#  " -> 大标题      "## " -> 小节标题
#     "!! " -> 警示（橙）   "++ " -> 成功/正面（绿）
#     ">  " -> 示例 / 代码（灰底等宽）   "·· " 普通条目
#     其余  -> 正文
# ---------------------------------------------------------------------------

HELP_QUICKSTART = u"""
# 四步就能用起来

一、填 Key（只需一次）
    点工具条上的「设置」→「Key 设置」里粘贴天地图 Key → 点「校验并保存」。
    没有 Key 的话去 https://console.tianditu.gov.cn/api/key 免费申请，
    类型记得选「浏览器端」。
++
    只用 Esri / 高德 / OSM 这些图源的话，Key 可以不填 —— 见「图源说明」。

二、让工具条露出来（只需一次）
    ArcMap 菜单「自定义(Customize)」→「工具条(Toolbars)」→ 勾选「天地图 Tools」。
    插件默认**不自动创建**工具条，原因写在「常见问题 Q3」里，不这样做
    ArcMap 会被强制中止。
    也可以走「自定义 → 自定义模式 → 命令 → 类别: 天地图」，
    把五个命令拖到任意工具条上。

三、加底图
    点「添加底图」→ 在窗口里双击想用的图源（或选中后点「添加」）。
    内置图源一百多条，窗口顶部有「筛选」框：输入「影像」「Esri」「腾讯」
    这类关键词就能立刻缩小范围。
    加完会自动缩放到全图，直接开始用。

四、找地方
    点「搜索」→ 输入地名 → 双击结果，地图落一个定位点并放大到该处。

## 工具条上的五个按钮

    添加底图    选择并添加在线底图（含自定义 XYZ 图源）
    搜索        天地图地名检索，结果落点并缩放
    设置        Key / 子域 / 图源可见性 / XYZ 代理
    图源管理    增删改自定义 XYZ 图源，可就地测试连通性
    帮助        就是本窗口

## 两个窗口的小技巧

    · 底图窗口里选中一条图源，下方会显示它的备注或坐标警告。
    · 「图源管理…」按钮就在底图窗口左下角，不用退出去再开。
    · 加完自定义图源**不必重启 ArcMap**：中转服务会按文件改动时间
      自动重读清单，下一张瓦片就生效。
"""

HELP_SOURCES = u"""
# 内置图源分五组

## 一、天地图（XYZ 接口）    5 条
    矢量底图 / 影像底图 / 地形晕渲 / 注记（中、英文各一套双拼）。
    走天地图官方 DataServer 接口，**需要 Key**；国内直连，不用代理。

## 二、Esri 在线地图    9 条
    影像、街道、地形、海洋、参考注记、地形底图、自然地理 ……
    来自 services.arcgisonline.com，直连可用、**不需要 Key**。
    没配天地图 Key 时，这组最省事。

## 三、国内图源（GCJ-02）    4 条
    高德影像 / 高德路网注记 / 高德矢量 / 腾讯矢量。
!!
    这一组是 GCJ-02（火星坐标）。瓦片本身挂在 WGS84 格网上，
    与 GPS 实测点、WGS84 矢量数据叠加会**整体偏移 300~600 米**。
    栅格瓦片没法在不重采样的前提下纠偏 —— 要精确套合请改用天地图
    或 Esri，或者自己先做一次坐标纠偏。
    选中这类图源时，窗口下方会显示这条警告；第一次加图层还会弹一次提示。

## 四、境外图源（需代理）    15 条
    Google（影像 / 街道 / 地形）、OSM（2 条）、OpenTopoMap、
    CARTO（3 条）、Wikimedia、USGS（2 条）、OpenRailwayMap（3 条）。
!!
    这些域名在国内直连不通，需要开代理，见下面「代理设置」。
    没开代理时它们会一直转圈或直接失败，这是预期行为，不是插件坏了。

## 五、专题 · 科研    2 条
    NASA Blue Marble（全球影像）、MODIS 真彩。

## 代理设置
    「设置 → 图源管理 → 代理」管的是 **XYZ 取瓦片**走不走代理：

    留空      直连（默认）。天地图 / Esri / 高德 / 腾讯都够用。
    auto      读环境变量 http_proxy / HTTP_PROXY；读不到就读 Windows
              「Internet 选项」里的代理设置。dev-sidecar 这类本机代理
              通常会把端口写在那里。
    host:port 固定走这个代理，例如 127.0.0.1:7890。

    单条图源还能在「图源管理」里覆盖全局：跟随全局 / 强制走代理 / 强制直连。
++
    默认是直连，这是有意的 —— 曾经把全局系统代理打开，本机中转取一张
    国内瓦片要 124 秒。国内源直连才是正常速度。

## 子域与缓存
    带 {s} 的源（Google、高德等）会让**同一张瓦片固定落在同一个子域**上，
    这样本机缓存才命中得上；只有第一次取失败时才换个子域重试一次。
"""

HELP_XYZ = u"""
# 把任意 XYZ 瓦片接进 ArcMap

「图源管理」窗口管的就是这件事。

## 为什么需要一个"翻译层"
    ArcMap 10.4 **没有** XYZ 图层类型：arcpy 里没有 MakeWMTSLayer，
    Layer(<URL>) 也读不了在线服务。
    插件走的路子是：在你本机起一个很小的中转服务，把这条 XYZ 模板
    **合成一份 WMTS 服务**交给 ArcMap；ArcMap 发来的 WMTS 请求再由中转
    反翻译成 XYZ 去取瓦片。
    对 ArcMap 来说它就是一个普通 WMTS 图层，所以缩放、拼接、缓存全部正常。

## URL 模板里的占位符

    {z}     层级          0 ~ 22
    {x}     列号          西起，0 ~ 2^z-1
    {y}     行号          北起
    {-y}    行号          南起（TMS 约定），插件自动换算
    {s}     子域          从该图源的「子域列表」里按瓦片位置固定取一个
    {tk}    天地图 Key    取自「设置 → Key 设置」
    {q}     quadkey       少数 Bing 风格的源用

!!
    {-y} 与 {y} 只能二选一。写错行号会让整幅图上下颠倒 ——
    表现为"能出图但内容对不上"，很难从画面上看出来。

## 几个能直接抄的例子

> 标准 XYZ
>     https://tile.openstreetmap.org/{z}/{x}/{y}.png

> 带子域（子域列表填 0,1,2,3）
>     https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}

> ArcGIS REST 切片（注意 y 在前）
>     https://server.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}

> TMS（行号南起）
>     https://a.tile.opentopomap.org/{z}/{x}/{-y}.png

> 天地图 DataServer
>     https://t{s}.tianditu.gov.cn/DataServer?T=img_w&x={x}&y={y}&l={z}&tk={tk}

## 各字段怎么填

    名称        在「添加底图」里显示的名字
    分组        归到哪一组；自定义源默认进「我的图源」
    zmin/zmax   该源**实际有数据**的层级范围。
                填大了：高缩小级会取到空白瓦片（不是错误，就是没图）；
                填小了：白白浪费清晰度。
    子域列表    逗号分隔；模板里用了 {s} 才需要，如 0,1,2,3 或 a,b,c
    Referer     源有防盗链时填它的站点首页，例如 https://map.qq.com/
    坐标系      wgs84（默认）/ gcj02 / bd09。选后两者时，添加图层会
                给一次偏移警告 —— 栅格瓦片纠不了偏，这个提示是认真的。
    代理        跟随全局 / 强制走代理 / 强制直连
    备注        自由文本；在底图窗口选中该源时会显示在下方

## 几点实操提醒

    · 「测试连通性」会真去拉一张北京上空的瓦片。
      取回**空白瓦片也算通过** —— 那说明服务是好的，只是那个位置没有
      要素，矢量图源很常见。
    · 内置清单在插件目录的 maps/xyz.json 里，**升级插件会被覆盖**。
      要改请用「复制为自定义」，改出来的那条存在你自己的 config.json。
    · 删掉一条自定义源，地图里已经加过的图层不会立刻消失，
      但重启 ArcMap 后就取不到瓦片了。
    · 层级范围改小了，已经加过的图层要重新加一次才生效
      （ArcMap 把格网信息记在图层里）。
"""

HELP_FAQ = u"""
# 常见问题

## Q1  图层在左侧列表里，画布却一片空白？
    多半是取不到瓦片。按顺序排查：
    · 天地图源先确认 Key 通过校验（「设置」里点一下就知道）；
    · 在「图源管理」里对这条源点「测试连通性」；
    · 若是 Google / OSM，检查代理开没开；
    · 也可能是当前比例尺超出了该源的 zmin~zmax，放大几级就有了。

## Q2  地图能显示，但一放大就白屏？
++
    这条已经修掉了（0.7 之前的老问题）。根因两条，都跟"一次解析、多次
    复用"有关：域名每张瓦片都重新解析会间歇性超时；以及 ArcMap 会把
    自己的请求参数**无分隔符**地粘到地址末尾，把参数粘坏。
    现在的做法是 DNS 只解析一次 + IP 直连 + 每线程 keep-alive，
    中转侧同时容忍粘连。若仍复现，把下面的日志发出来。

## Q3  启动 ArcMap 一段时间后被强制中止，弹
    「This application has requested the Runtime to terminate it in an
      unusual way.」
    这是 ArcMap 10.4 在 Windows 11 上自动创建 Python 加载项工具条时的
    已知问题（约 20~30 秒后 CRT 主动 abort）。所以本插件默认
    **不自动创建工具条**，你手动在「自定义 → 工具条」里勾选一次即可，
    ArcMap 会记住这个勾选。
    另外：插件里所有界面（设置 / 底图 / 搜索 / 图源管理 / 帮助）一律跑在
    **独立进程**里 —— 在 ArcMap 进程内直接调度 Tkinter 会破坏它内部的
    数据结构，触发同样的中止。

## Q4  弹「Visual Fortran run-time error / forrtl: severe (38)」？
    ArcMap 之外的进程里 import 了 arcpy，把 DFORRT.dll 拉了进来；而那个
    进程没有控制台，Fortran 运行时往 CONOUT$ 写诊断失败就弹模态框并永久
    卡死。插件已严格隔离：界面进程不碰 arcpy，造图层/加图层只回到 ArcMap
    进程内做。你自己写脚本调用时也请遵守这条。

## Q5  图层位置整体偏了几百米？
    那是 GCJ-02 源（高德 / 腾讯）。见「图源说明」第三条。
    要精确套合请换天地图或 Esri。

## Q6  重启 ArcMap 后图层不出图了？
    大概率那条自定义图源被删了，或者这份地图文档是在另一台机器/另一个
    用户下做的 —— 自定义图源存在**当前用户的** config.json 里，
    换机器需要重新导入。

## Q7  搜索没结果？
    天地图检索需要 Key；另外检索范围是全国，输入太笼统的名字会返回很多
    条，挑一条双击即可。

## Q8  日志在哪？
    %APPDATA%\\TiandituTools\\
        import_error.log   插件与界面进程的诊断日志
        ui_error.log       界面进程自身的异常
        config.json        Key、子域、图源开关、自定义 XYZ 源、代理
    另外，在本机中转服务的地址后面加 /stats，可以看到瓦片请求计数、
    缓存命中数、DNS 解析次数 —— 排障时很有用。
"""

HELP_ABOUT_TEXT = u"""
# 天地图 Tools

    ArcMap 10.4 Python Add-In
    在线底图 / 地名检索 / 自定义 XYZ 图源

## 版本
    %s

## 定位
    一个"够用就好"的小工具：把常见在线底图一键加进 ArcMap，
    并且把任意 {z}/{x}/{y} 瓦片源也接进来 —— 包括 ArcMap 原生
    不支持的 XYZ 格式。

## 感谢
    天地图（国家地理信息公共服务平台）提供基础底图服务；
    Esri、OpenStreetMap 及各家图源提供公开瓦片。

## 许可与免责
    本插件按"原样"提供。各图源的可用性、使用条款与配额由其提供方
    决定，请遵守相应服务条款；商用前请确认授权。
"""


# ---------------------------------------------------------------------------
# 正文渲染
# ---------------------------------------------------------------------------

def _fonts():
    try:
        import tkFont as tkfont
    except ImportError:
        import tkinter.font as tkfont
    try:
        base = tkfont.nametofont("TkDefaultFont")
        fam = base.actual("family")
        size = int(base.actual("size"))
    except Exception:
        fam, size = "Microsoft YaHei", 9
    size = max(8, min(14, size))
    return {
        "body": tkfont.Font(family=fam, size=size),
        "bold": tkfont.Font(family=fam, size=size, weight="bold"),
        "h1": tkfont.Font(family=fam, size=size + 4, weight="bold"),
        "h2": tkfont.Font(family=fam, size=size + 1, weight="bold"),
        "mono": tkfont.Font(family="Consolas", size=size),
        "small": tkfont.Font(family=fam, size=max(7, size - 1)),
    }


def _put(txt, text, tags):
    """按需带标签插入 —— 空标签必须**不传**第三个参数，
    Tkinter(py2) 传空 tuple 会被当成一个空标签名而报错。"""
    if tags:
        txt.insert(tk.END, text, tags)
    else:
        txt.insert(tk.END, text)


def _rich(txt, text, base=None):
    """插入一行文本，并把 **粗体** 标记转成 bold 标签（标记本身不显示）。

    注意不能用 "bold" + "h1" 两个标签叠加 —— Tk 的标签优先级按**创建顺序**，
    后建的 h1 会盖掉 bold 的字体，粗体就没了。所以粗体一律用**复合标签名**
    （bold_h1 / bold_warn …），在 _config_text_tags 里一次配好。
    """
    parts = _u(text).split(u"**")
    for i, p in enumerate(parts):
        if not p:
            continue
        if i % 2 == 1:
            tag = ("bold_" + base) if base else "bold"
            _put(txt, p, (tag,))
        else:
            _put(txt, p, (base,) if base else ())


def _fill(txt, content):
    """把标记文本灌进一个只读 Text 控件"""
    txt.configure(state=tk.NORMAL)
    txt.delete("1.0", tk.END)
    for raw in _u(content).split(u"\n"):
        line = raw.rstrip()
        if not line.strip():
            txt.insert(tk.END, u"\n")
            continue
        if line.startswith(u"# "):
            _rich(txt, line[2:].strip(), "h1")
            txt.insert(tk.END, u"\n")
        elif line.startswith(u"## "):
            _rich(txt, line[3:].strip(), "h2")
            txt.insert(tk.END, u"\n")
        elif line.startswith(u"!!"):
            _rich(txt, line[2:].strip(), "warn")
            txt.insert(tk.END, u"\n")
        elif line.startswith(u"++"):
            _rich(txt, line[2:].strip(), "ok")
            txt.insert(tk.END, u"\n")
        elif line.startswith(u">"):
            _rich(txt, line[1:].rstrip(), "code")
            txt.insert(tk.END, u"\n")
        else:
            _rich(txt, line)
            txt.insert(tk.END, u"\n")
    txt.configure(state=tk.DISABLED)
    txt.yview_moveto(0.0)


def _config_text_tags(txt, fonts):
    """各 Text 控件共用的标签集合。

    复合标签（bold_h1 / bold_warn …）必须**先配基础标签、后配复合标签**，
    让复合标签在 Tk 里优先级更高 —— 否则同一段文字同时带两个标签时，
    字体由先创建的那个决定，粗体就丢了。
    """
    txt.tag_configure("bold", font=fonts["bold"])
    txt.tag_configure("h1", font=fonts["h1"], foreground="#0E4C8C",
                      spacing1=2, spacing3=10)
    txt.tag_configure("h2", font=fonts["h2"], foreground="#1462B4",
                      spacing1=12, spacing3=6)
    txt.tag_configure("warn", foreground="#B0530A", lmargin1=16, lmargin2=16,
                      spacing1=4, spacing3=4)
    txt.tag_configure("ok", foreground="#0A7D28", lmargin1=16, lmargin2=16,
                      spacing1=4, spacing3=4)
    txt.tag_configure("code", font=fonts["mono"], foreground="#2F4F6F",
                      background="#F2F5F8", lmargin1=20, lmargin2=20,
                      spacing1=1, spacing3=1)
    txt.tag_configure("bold_h1", font=fonts["h1"], foreground="#0E4C8C")
    txt.tag_configure("bold_h2", font=fonts["h2"], foreground="#1462B4")
    txt.tag_configure("bold_warn", font=fonts["bold"], foreground="#B0530A",
                      lmargin1=16, lmargin2=16)
    txt.tag_configure("bold_ok", font=fonts["bold"], foreground="#0A7D28",
                      lmargin1=16, lmargin2=16)


def _text_tab(nb, title, content, fonts):
    frame = ttk.Frame(nb, padding=(8, 6))
    nb.add(frame, text=_enc(title))
    txt = tk.Text(frame, wrap=tk.WORD, relief=tk.FLAT, borderwidth=0,
                  padx=12, pady=8, font=fonts["body"], height=20,
                  background="#FDFDFE", highlightthickness=0)
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    _config_text_tags(txt, fonts)
    _fill(txt, content)

    # 只读但不影响滚动/复制；Ctrl+C 照常能用
    def _block_edit(evt):
        if evt.state & 0x4 and evt.keysym.lower() in ("c", "a"):
            return
        if evt.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next",
                          "Home", "End"):
            return
        return "break"

    txt.bind("<Key>", _block_edit)
    return txt


# ---------------------------------------------------------------------------
# 「关于」页：正文 + 微信公众号（预留）
# ---------------------------------------------------------------------------

class AboutTab(ttk.Frame):
    def __init__(self, master, fonts, nb):
        ttk.Frame.__init__(self, master, padding=(8, 6))
        nb.add(self, text=_enc(u"关于"))
        self.conf = load_config()
        self._qr_img = None

        txt = tk.Text(self, wrap=tk.WORD, relief=tk.FLAT, borderwidth=0,
                      padx=12, pady=8, font=fonts["body"], height=10,
                      background="#FDFDFE", highlightthickness=0)
        sb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        _config_text_tags(txt, fonts)
        _fill(txt, HELP_ABOUT_TEXT % VERSION)
        txt.configure(state=tk.DISABLED)

        self._build_wechat(fonts)

    # -- 微信公众号 --------------------------------------------------------
    def _build_wechat(self, fonts):
        box = ttk.LabelFrame(self, text=_enc(u"关注 / 微信公众号"), padding=10)
        box.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

        right = ttk.Frame(box)
        right.pack(side=tk.RIGHT, padx=(12, 0))
        self._qr(right, fonts)

        left = ttk.Frame(box)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.var_name = tk.StringVar()
        self.var_url = tk.StringVar()
        self.var_tip = tk.StringVar()

        rows = ((u"公众号名称", self.var_name, 30),
                (u"文章链接", self.var_url, 42),
                (u"一句话介绍", self.var_tip, 42))
        for i, (label, var, width) in enumerate(rows):
            ttk.Label(left, text=_enc(label), font=fonts["small"]).grid(
                row=i, column=0, sticky=tk.W, pady=3, padx=(0, 8))
            ttk.Entry(left, textvariable=var, width=width).grid(
                row=i, column=1, sticky=tk.EW, pady=3)
        left.columnconfigure(1, weight=1)

        bar = ttk.Frame(left)
        bar.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Button(bar, text=_enc(u"保存"), command=self.on_save).pack(side=tk.LEFT)
        self.btn_open = ttk.Button(bar, text=_enc(u"打开文章"),
                                   command=self.on_open)
        self.btn_open.pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text=_enc(u"复制链接"),
                   command=self.on_copy).pack(side=tk.LEFT)
        ttk.Button(bar, text=_enc(u"打开配置目录"),
                   command=self.on_open_dir).pack(side=tk.LEFT, padx=6)

        self.lbl_state = ttk.Label(left, text=u"", font=fonts["small"],
                                   foreground="#666", wraplength=430,
                                   justify=tk.LEFT)
        self.lbl_state.grid(row=4, column=0, columnspan=2, sticky=tk.W,
                            pady=(6, 0))

        self._load_wechat()

    def _qr(self, parent, fonts):
        """二维码位。图放在 images/wechat_qr.gif，用同名文件覆盖即换真图。"""
        path = _img_path("wechat_qr.gif")
        holder = ttk.Frame(parent)
        holder.pack()
        shown = False
        if _os.path.isfile(path):
            try:
                img = tk.PhotoImage(file=path)
                # Tk 8.5 **不能缩放**图片（只能整数倍抽取）。用户放进来的
                # 二维码可能上千像素，直接摆上去会把布局撑爆；这里按整数
                # 因子 subsample 到 150px 左右。
                # 抽取法会损失清晰度，所以另给了「查看原图」按钮——
                # 真要扫码就用原图。
                k = 1
                while img.width() // (k + 1) >= 150 and k < 8:
                    k += 1
                if k > 1:
                    img = img.subsample(k, k)
                self._qr_img = img
                tk.Label(holder, image=self._qr_img, borderwidth=0).pack()
                shown = True
            except Exception:
                self._qr_img = None
        if not shown:
            self._qr_placeholder(holder)
        ttk.Label(holder, text=_enc(u"公众号二维码"), font=fonts["small"],
                  foreground="#888").pack(pady=(2, 0))
        if _os.path.isfile(path):
            ttk.Button(holder, text=_enc(u"查看原图"), width=10,
                       command=lambda: self._open_file(path)).pack(pady=(2, 0))

    def _open_file(self, path):
        try:
            _os.startfile(path)                      # noqa: F821  (Windows/py2)
        except Exception:
            try:
                import subprocess
                subprocess.Popen(["explorer", path])
            except Exception:
                pass

    def _qr_placeholder(self, parent):
        """没有二维码图片时的占位框（虚线感用两层面板模拟）"""
        outer = tk.Frame(parent, background="#C8D0D8", padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, background="#F7F9FA", width=130, height=130)
        inner.pack()
        inner.pack_propagate(False)
        tk.Label(inner, text=_enc(u"二维码\n待放入\nwechat_qr.gif"),
                 background="#F7F9FA", foreground="#98A2AC",
                 font=("Microsoft YaHei", 8), justify=tk.CENTER).pack(
            expand=True)

    def _load_wechat(self):
        c = self.conf
        self.var_name.set(_u(c.get("wechatName") or u""))
        self.var_url.set(_u(c.get("wechatArticleUrl") or u""))
        self.var_tip.set(_u(c.get("wechatTip") or u""))
        self._sync_state()

    def _sync_state(self):
        name = self.var_name.get().strip()
        url = self.var_url.get().strip()
        if not name and not url:
            self.lbl_state.configure(
                text=_enc(u"（预留）公众号与文章还没发布，这里先空着。"
                          u"填好点「保存」即可 —— 不用等插件升级。"),
                foreground="#B0530A")
            self.btn_open.configure(state=tk.DISABLED)
        else:
            parts = []
            if name:
                parts.append(name)
            if not url:
                parts.append(u"文章链接为空，暂时无法打开")
            self.lbl_state.configure(text=_enc(u" · ".join(parts)),
                                     foreground="#0A7D28")
            self.btn_open.configure(state=(tk.NORMAL if url else tk.DISABLED))

    def on_save(self):
        save_config({
            "wechatName": self.var_name.get().strip(),
            "wechatArticleUrl": self.var_url.get().strip(),
            "wechatTip": self.var_tip.get().strip(),
        })
        self.conf = load_config()
        self._sync_state()

    def on_open(self):
        url = self.var_url.get().strip()
        if not url:
            return
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        try:
            import webbrowser
            webbrowser.open(url)
            self.lbl_state.configure(text=_enc(u"已交给系统浏览器打开"),
                                     foreground="#0A7D28")
        except Exception as e:
            tkMessageBox.showerror(u"天地图 Tools",
                                   _enc(u"打不开链接：%s" % e))

    def on_copy(self):
        url = self.var_url.get().strip()
        if not url:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.lbl_state.configure(text=_enc(u"链接已复制到剪贴板"),
                                     foreground="#0A7D28")
        except Exception:
            pass

    def on_open_dir(self):
        """在资源管理器里打开 %APPDATA%\\TiandituTools（放日志与 config.json）"""
        d = _build_info_dir()
        try:
            if not _os.path.isdir(d):
                _os.makedirs(d)
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(["explorer", d])
        except Exception as e:
            try:
                import os as _o
                _o.startfile(d)                      # noqa: F821  (py2/Windows)
            except Exception:
                tkMessageBox.showinfo(u"天地图 Tools", _enc(u"目录：%s\n(%s)" % (d, e)))


def _build_info_dir():
    """日志/配置目录（%APPDATA%\\TiandituTools）"""
    return _os.path.join(_os.environ.get("APPDATA") or _os.path.expanduser("~"),
                         u"TiandituTools")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class HelpWindow(tk.Toplevel):
    def __init__(self, parent=None, tab=None):
        tk.Toplevel.__init__(self, parent)
        self.title(_enc(u"天地图 Tools - 帮助"))
        # 尺寸走 ui_util：夹到屏幕内 + 居中靠上。直接 geometry() 的话，
        # 在 225% 缩放的机器上窗口会被 Tk 摆到屏幕下半截，
        # 右下角的「关闭」正好压到任务栏底下（实测过）。
        ui_util.place(self, 820, 660, min_width=640, min_height=480)
        self._logo_img = None
        self._tab_wanted = tab
        self._build()
        self._select_tab(tab)
        try:
            self.update_idletasks()
            self.focus_set()
        except Exception:
            pass

    def _build(self):
        fonts = _fonts()

        head = tk.Frame(self, background="#104A80")
        head.pack(fill=tk.X)
        self._banner(head, fonts)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.nb = nb
        _text_tab(nb, u"快速上手", HELP_QUICKSTART, fonts)
        _text_tab(nb, u"图源说明", HELP_SOURCES, fonts)
        _text_tab(nb, u"自定义 XYZ", HELP_XYZ, fonts)
        _text_tab(nb, u"常见问题", HELP_FAQ, fonts)
        AboutTab(nb, fonts, nb)

        bar = ttk.Frame(self, padding=(10, 0, 10, 10))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text=_enc(u"天地图 Tools v%s" % VERSION),
                  foreground="#888").pack(side=tk.LEFT)
        ttk.Button(bar, text=_enc(u"关闭"), command=self.destroy).pack(
            side=tk.RIGHT)

    def _select_tab(self, tab):
        """tab 可以是页签序号，也可以是页签标题（按标题模糊匹配）"""
        if tab is None or tab == u"":
            return
        try:
            tabs = list(self.nb.tabs())
            idx = None
            if isinstance(tab, int):
                idx = tab
            else:
                want = _u(tab)
                for i, tid in enumerate(tabs):
                    if want in _u(self.nb.tab(tid, "text")):
                        idx = i
                        break
            if idx is not None and 0 <= idx < len(tabs):
                self.nb.select(tabs[idx])
        except Exception:
            pass

    def _banner(self, parent, fonts):
        """页眉。优先用设计好的 GIF；找不到就退回纯文字条。"""
        path = _img_path("help_logo.gif")
        if _os.path.isfile(path):
            try:
                self._logo_img = tk.PhotoImage(file=path)
                tk.Label(parent, image=self._logo_img, background="#104A80",
                         borderwidth=0).pack(side=tk.LEFT, padx=(10, 6), pady=6)
                return
            except Exception:
                self._logo_img = None
        tk.Label(parent, text=_enc(u"天地图 Tools"), background="#104A80",
                 foreground="#FFFFFF", font=fonts["h1"]).pack(
            side=tk.LEFT, padx=14, pady=(10, 8))
        tk.Label(parent, text=_enc(u"ArcMap 在线底图 / 搜索 / 自定义图源"),
                 background="#104A80", foreground="#A8CEF0",
                 font=fonts["small"]).pack(side=tk.LEFT, padx=6, pady=(14, 8))


def show_help(parent=None, tab=None):
    """就地打开（例如从设置窗口调用）；返回窗口对象"""
    w = HelpWindow(parent, tab)
    try:
        w.lift()
        w.attributes("-topmost", True)
        w.after(900, lambda: w.attributes("-topmost", False))
    except Exception:
        pass
    if parent is not None:
        try:
            parent.wait_window(w)
        except Exception:
            pass
    return w


def run_standalone(payload=None):
    """独立进程入口（ui_main.py 的 mode="help"）

    payload 可带 {"tab": "常见问题"} —— 指定打开哪一页；不带就是第一页。
    """
    tab = (payload or {}).get("tab")
    root = tk.Tk()
    root.withdraw()
    w = HelpWindow(root, tab)
    try:
        w.deiconify()
        w.lift()
        w.focus_force()
        w.attributes("-topmost", True)
        w.after(900, lambda: w.attributes("-topmost", False))
    except Exception:
        pass
    root.wait_window(w)
    try:
        root.destroy()
    except Exception:
        pass
    return {}
