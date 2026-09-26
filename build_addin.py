# -*- coding: utf-8 -*-
"""打包 TiandituTools -> TiandituTools.esriaddin

严格遵循 ArcGIS Desktop 官方 Python Add-In 规范
（对照 Python Add-In Wizard 生成的 makeaddin.py 与真实工程 config.xml）。

官方规范（逐条依据，勿凭感觉改）：
  1) .esriaddin 就是"把工作目录压缩成 ZIP"，根目录平铺：
        config.xml           插件元数据 + 组件声明（必须在根）
        Install/             Python 脚本与运行期数据（官方叫"活动部分"）
        Images/              所有界面图形（config.xml 引用的图标）
        README.txt           可选说明（向导也会打包）
     参见 doc: essential-python-add-in-concepts#File and folder structure
  2) 入口模块名为 <ProjectName>_addin.py，config.xml 里：
        library="TiandituTools_addin.py"  namespace="TiandituTools_addin"
     即 library 是**文件名**（框架按文件加载），namespace 与文件同名。
     真实样例：library="Elevation_Profile_addin.py" namespace="Elevation_Profile_addin"
  3) <ArcMap> 子元素顺序（XSD 为 xs:sequence）：
        Commands -> Extensions -> Toolbars -> Menus
  4) <Toolbar> 属性只有 id / caption / category / showInitially。
     **Python 加载项的工具栏没有 class 属性**（不存在 Python 的 Toolbar 类；
      官方 add-in 类只有 Button / Tool / ComboBox / Menu / Extension）。
      给 Toolbar 写 class=... 会让工厂去解析一个不存在的类 -> 初始化异常。
  5) 命令的 id 约定为 "<namespace>.<shortId>"，<Items> 里的 refID 必须与之完全一致。
     真实样例：id="Elevation_Profile_addin.reset" / refID="Elevation_Profile_addin.reset"
  6) language 必须是全大写 "PYTHON"
     （见 bin/AddInSettings.xml：<Factory name="pythonaddins.pyd" language="PYTHON"/>）
  7) 图形路径用反斜杠，如 Images\\add16.png（与向导输出一致）

安装位置（官方 well-known folder）：
    C:\\Users\\<user>\\Documents\\ArcGIS\\AddIns\\Desktop10.4\\<AddInID GUID>\\
加载时 Install/ 的内容会被解包到：
    C:\\Users\\<user>\\AppData\\Local\\ESRI\\Desktop10.4\\AssemblyCache\\<AddInID GUID>\\

用法（任意 Python 2.7 / 3 均可）:
    python build_addin.py
"""

from __future__ import print_function

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, "TiandituTools")
OUT = os.path.join(ROOT, "TiandituTools.esriaddin")

# 入口模块：源码里的 __init__.py 打包时改名为 TiandituTools_addin.py
ENTRY_SRC = "__init__.py"
ENTRY_NAME = "TiandituTools_addin.py"
NS = "TiandituTools_addin"

# 稳定 AddInID（更换会让 ArcMap 视为不同插件，勿随意改）
ADDIN_ID = "{A1B2C3D4-1234-5678-9ABC-DEF012345678}"

SKIP_DIRS = {".git", "__pycache__", ".DS_Store"}
SKIP_PREFIXES = ("._",)

#: 是否把 dev_*.py（自检等调试模块）也打进包里。
#: 正式发布包**不含**；端到端测试用 TIANDITU_BUILD_DEV=1 打临时测试包。
INCLUDE_DEV = os.environ.get("TIANDITU_BUILD_DEV") == "1"

# ---------------------------------------------------------------------------
# config.xml
# ---------------------------------------------------------------------------
# 中文一律用数字字符引用（&#xxxx;），在中文 Windows 上不受解析编码影响。
# 天地图 = &#22825;&#22320;&#22270;
#
# 自定义内容请只改下面这几个常量。
NAME = "TiandituTools"
VERSION = "0.8.2"
DESCRIPTION = "天地图底图与搜索工具 (ArcMap Python Add-In)"
AUTHOR = "WorkBuddy"
COMPANY = "TiandituTools"
DATE = "2026-09-25"
TARGET_VERSION = "10.4"

# 按钮：shortId, class, caption, image, tip, message
BUTTONS = [
    ("addBasemap", "AddBasemapButton",
     "&#28155;&#21152;&#24213;&#22270;", "add16.png",           # 添加底图 / 添加底图
     "&#28155;&#21152;&#24213;&#22270;", "&#36873;&#25321;&#24182;&#28155;&#21152;&#22312;&#32447;&#24213;&#22270;"),
    ("search", "SearchButton",
     "&#25628;&#32034;", "search16.png",                        # 搜索 / 搜索
     "&#25628;&#32034;", "&#25171;&#24320;&#22825;&#22320;&#22270;&#25628;&#32034;"),
    ("xyz", "XyzManagerButton",
     "&#22270;&#28304;&#31649;&#29702;", "xyz16.png",           # 图源管理 / 图源管理
     "&#22270;&#28304;&#31649;&#29702;", "&#22686;&#21024;&#25913;&#33258;&#23450;&#20041; XYZ &#29926;&#29255;&#22270;&#28304;"),
    ("settings", "SettingsButton",
     "&#35774;&#32622;", "setting16.png",                       # 设置 / 设置
     "&#35774;&#32622;", "&#25171;&#24320;&#22825;&#22320;&#22270; Tools &#35774;&#32622;"),
    ("help", "HelpButton",
     "&#24110;&#21161;", "help16.png",                          # 帮助 / 帮助
     "&#24110;&#21161;", "&#25171;&#24320;&#24110;&#21161;&#19982;&#24555;&#36895;&#19978;&#25163;"),
]

# 工具栏：id 后缀、标题、是否启动即显示
TOOLBAR_ID = "toolbar"
TOOLBAR_CAPTION = "&#22825;&#22320;&#22270; Tools"   # 天地图 Tools
TOOLBAR_CATEGORY = "&#22825;&#22320;&#22270;"        # 天地图

# 变体开关（仅用于排障对比，正式发布用默认值）：
#   TIANDITU_VARIANT=default -> 声明 Toolbars，showInitially="true"（启动即自动创建工具条）
#   TIANDITU_VARIANT=hidden  -> 声明 Toolbars，showInitially="false"（不自动创建）【默认】
#   TIANDITU_VARIANT=none    -> 完全不声明 Toolbars（按钮仅在 自定义->命令 里）
#
# 【为什么默认 hidden】本机实测（ArcMap 10.4.1 / Windows 11 25H2）：
#   showInitially="true" 时，ArcMap 在启动序列里自动创建该 Python 加载项工具条，
#   约 20~30 秒后被 MSVCR 强制中止，弹出
#     "Microsoft Visual C++ Runtime Library — Runtime Error!
#      This application has requested the Runtime to terminate it in an unusual way."
#   进程退出码 = -1 (0xFFFFFFFF)，且事件日志中**没有** Application Error 记录
#   （说明不是堆损坏式崩溃，而是 CRT abort 主动退出）。
#   把同一份包改成 showInitially="false" 后，用探针（同时检测进程存活与 CRT 中止
#   对话框）连续观测 100 秒：一直运行、无中止对话框、插件模块正常导入。
#   对照：不装插件时同样稳定。
#   因此默认采用 showInitially="false"（官方文档亦说明该选项可取消勾选），
#   用户在「自定义 -> 工具条」里勾选一次「天地图 Tools」即可，之后 ArcMap 会记住。
VARIANT = os.environ.get("TIANDITU_VARIANT", "hidden").strip().lower()
TOOLBAR_SHOW_INITIALLY = "false" if VARIANT in ("hidden", "none") else "true"


def _commands_xml():
    out = []
    for sid, cls, caption, image, tip, message in BUTTONS:
        out.append(
            '        <Button id="%s.%s" class="%s" caption="%s" category="%s"'
            ' image="Images\\%s" tip="%s" message="%s">'
            % (NS, sid, cls, caption, TOOLBAR_CATEGORY, image, tip, message)
        )
        out.append('          <Help heading="%s">%s</Help>' % (message, message))
        out.append('        </Button>')
    return "\n".join(out)


def _items_xml():
    return "\n".join(
        '            <Button refID="%s.%s" />' % (NS, sid) for sid, _c, _a, _i, _t, _m in BUTTONS
    )


def _toolbars_xml():
    if VARIANT == "none":
        return ""
    return """
      <Toolbars>
        <Toolbar id="%(ns)s.%(tbid)s" caption="%(tbcaption)s" category="%(tbcategory)s" showInitially="%(tbshow)s">
          <Items>
%(items)s
          </Items>
        </Toolbar>
      </Toolbars>""" % {
        "ns": NS,
        "tbid": TOOLBAR_ID,
        "tbcaption": TOOLBAR_CAPTION,
        "tbcategory": TOOLBAR_CATEGORY,
        "tbshow": TOOLBAR_SHOW_INITIALLY,
        "items": _items_xml(),
    }


CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ESRI.Configuration xmlns="http://schemas.esri.com/Desktop/AddIns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://schemas.esri.com/Desktop/AddIns http://schemas.esri.com/Desktop/AddIns/ArcMapAddIns.xsd">
  <Name>%(name)s</Name>
  <AddInID>%(addin_id)s</AddInID>
  <Description>%(desc)s</Description>
  <Version>%(version)s</Version>
  <Image>Images\\toolbar32.png</Image>
  <Author>%(author)s</Author>
  <Company>%(company)s</Company>
  <Date>%(date)s</Date>
  <Targets>
    <Target name="Desktop" version="%(target)s" />
  </Targets>
  <AddIn language="PYTHON" library="%(entry)s" namespace="%(ns)s">
    <ArcMap>
      <Commands>
%(commands)s
      </Commands>
      <Extensions>
      </Extensions>%(toolbars)s
      <Menus>
      </Menus>
    </ArcMap>
  </AddIn>
</ESRI.Configuration>
""" % {
    "name": NAME,
    "addin_id": ADDIN_ID,
    "desc": DESCRIPTION,
    "version": VERSION,
    "author": AUTHOR,
    "company": COMPANY,
    "date": DATE,
    "target": TARGET_VERSION,
    "entry": ENTRY_NAME,
    "ns": NS,
    "commands": _commands_xml(),
    "toolbars": _toolbars_xml(),
}

# 版本信息注入 Install/_build_info.py。
#
# 为什么不把 VERSION 直接写进某个 ui_*.py：运行时拿不到 build_addin.py，
# 也拿不到 config.xml（config.xml 留在 .esriaddin 压缩包里，只有 Install/
# 会被解包到 AssemblyCache）。所以打包时把版本号"烧"进一个极小的模块，
# 帮助页的「关于」直接读它 —— 单一事实来源仍然是本文件的 VERSION 常量。
BUILD_INFO_PY = '''# -*- coding: utf-8 -*-
"""由 build_addin.py 自动生成，请勿手工修改。"""

NAME = %(name)r
VERSION = %(version)r
DATE = %(date)r
ADDIN_ID = %(addin_id)r
TARGET = %(target)r
''' % {
    "name": NAME,
    "version": VERSION,
    "date": DATE,
    "addin_id": ADDIN_ID,
    "target": TARGET_VERSION,
}


README_TXT = """%(name)s %(version)s  (ArcMap Python Add-In)

安装：
  1. 关闭 ArcMap
  2. 双击 %(name)s.esriaddin，点 Install Add-In
  3. 启动 ArcMap

首次启用工具条（本包默认不自动创建工具条，避免 ArcMap 启动时被中断）：
  菜单「自定义(Customize)」->「工具条(Toolbars)」-> 勾选「天地图 Tools」
  （只需勾一次，ArcMap 会记住；也可在「自定义 -> 自定义模式 -> 命令 ->
   类别: 天地图」里把五个命令拖到任意工具条上）

使用前需在「设置」中填入天地图 Key（浏览器端类型，32 位）。
申请地址：https://console.tianditu.gov.cn/api/key
（只用 Esri / 高德 / OSM 这类图源的话可以不填 Key。）

五个按钮：
  · 添加底图  —— 选择并添加在线底图（内置五组、100+ 条图源）
  · 搜索      —— 天地图地名检索，结果落点并缩放
  · 图源管理  —— 增删改自定义 XYZ 瓦片源，可就地测试连通性
  · 设置      —— Key、子域、图源可见性、XYZ 代理
  · 帮助      —— 快速上手 / 图源说明 / 自定义 XYZ / 常见问题 / 关于

内置图源分五组：
  · 天地图（XYZ 接口）5 条：矢量 / 影像 / 地形 / 注记，需要 Key，直连
  · Esri 在线地图 9 条：影像 / 街道 / 地形 / 海洋 / 注记，不需要 Key，直连
  · 国内图源 4 条：高德影像 / 高德路网注记 / 高德矢量 / 腾讯矢量
    ⚠ 这一组是 GCJ-02（火星坐标），与 GPS、WGS84 数据叠加会偏移 300~600 米。
      栅格瓦片没法在不重采样的前提下纠偏，要精确套合请用天地图或 Esri。
  · 境外图源 15 条：Google / OSM / OpenTopoMap / CARTO / Wikimedia /
    USGS / OpenRailwayMap —— 需要代理才能连通。
  · 专题 · 科研 2 条：NASA Blue Marble、MODIS 真彩。

自定义 XYZ 图源（本版新增）
  ArcMap 10.4 没有 XYZ 图层类型，arcpy 也没有 MakeWMTSLayer。
  插件在本机起一个很小的中转服务，把任意 {z}/{x}/{y} 模板**合成一份 WMTS
  服务**交给 ArcMap；ArcMap 发来的 WMTS 请求再由中转反翻译成 XYZ 去取瓦片。
  ArcMap 侧走的仍是与天地图完全相同的那条已验证通道，因此缩放、拼接、
  缓存全部正常。
  模板占位符：{z} {x} {y} {-y}(TMS 南起) {s}(子域) {tk}(天地图 Key) {q}(quadkey)
  入口：「图源管理」按钮，或在「添加底图」窗口左下角的「管理图源…」。
  内置清单在 Install/maps/xyz.json（只读，升级会覆盖），
  自定义源存 %%APPDATA%%\\TiandituTools\\config.json，可「复制为自定义」后再改。

代理（只影响 XYZ 取瓦片）
  「设置 -> 图源管理 -> XYZ 图源代理」：
    留空 = 直连（默认，天地图/Esri/高德/腾讯都够用）
    auto = 读 http_proxy 环境变量，读不到就读系统「Internet 选项」代理
    host:port = 固定走该代理
  单条图源还能在「图源管理」里覆盖全局（跟随 / 强制走 / 强制直连）。
  默认直连是有意的：曾经开着全局系统代理，本机中转取一张国内瓦片要 124 秒。

帮助与微信公众号
  「帮助」按钮打开一个五页签窗口。其中「关于」页预留了微信公众号区：
  公众号名称 / 文章链接 / 一句话介绍 + 二维码位。文章未发布时显示占位，
  填好点「保存」即可生效（不需要等插件升级）。
  二维码图片放在 Install/images/wechat_qr.gif，用同名文件覆盖即可换成真图。

关于「添加底图」如何做到真正一键自动添加：
  插件走 **ArcObjects COM 桥**（Install/arcobjects.py）创建「天地图 WMTS 图层」
  并 `IMap.AddLayer` 进当前地图，加完自动缩放到全图，一键到位。
  （原理：esriFramework.esriAppROT -> IApplication -> IMxDocument -> FocusMap，
  再用 esriGISClient.WMTSConnectionName + esriCarto.WMTSLayer 造图层。）
  为什么不用 arcpy：ArcMap 10.4 的 arcpy **没有** MakeWMTSLayer/MakeWMSLayer，
  且 `arcpy.mapping.Layer(<URL>)` 读不了在线服务，纯 arcpy 造不出在线图层。

两条「反直觉但必须遵守」的硬约束（都是实测踩出来的，改动前请先读 Install
目录下 layer_manager.py / arcobjects.py 顶部的说明）：

  一、造图层必须在 ArcMap 进程内做。
      esriCarto.WMTSLayer 是 in-proc 组件；如果在独立进程里 new 出来再交给
      ArcMap，ArcMap 拿到的只是**跨进程代理** —— 表现为图层在左侧列表里、
      画布却一片空白；而那个进程一退出，ArcMap 会在几秒内直接崩掉。

  二、ArcMap 之外的进程里绝不 import arcpy。
      ArcMap 外 import arcpy 会拉进 arcgisscripting -> Geoprocessing ->
      RasterCore/RasterEngine -> DFORRT.dll（Fortran 运行时）。这些辅助进程
      没有控制台，DFORRT 往 unit 0（CONOUT$）写诊断会失败，弹出模态框
      「Visual Fortran run-time error / forrtl: severe (38): error during
       write, unit 0, file CONOUT$」并把该进程**永久卡死**。

  所以分工是：界面（Tkinter）跑在独立进程；造图层/加图层/缩放回到 ArcMap
  进程内做；主线程等待界面时只等待、不抽消息（抽消息会重入 ArcGIS 消息循环
  并导致「遇到严重的应用程序错误」）。

  依赖：ArcGIS 自带 Python 2.7（C:\\Python27\\ArcGIS10.4）里的 **comtypes**
  （纯 Python 包）。首次点击若尚未生成 ArcGIS 类型库，会先弹提示
  「约 1~2 分钟」，这期间 ArcMap 会短暂无响应；生成一次后永久缓存，之后秒开。

说明：设置/搜索/底图选择界面全部运行在**独立进程**中（ArcMap 进程内直接
调度 Tkinter 会破坏 ArcMap 内部数据结构并导致其被强制中止）；ArcMap 进程
内的提示一律使用官方的 MessageBox。
""" % {"name": NAME, "version": VERSION}


def should_skip(name):
    base = os.path.basename(name)
    if base.startswith(SKIP_PREFIXES):
        return True
    if base in (".DS_Store",):
        return True
    if base.endswith(".pyc"):
        return True
    if base == "__pycache__":
        return True
    # 开发调试用的模块（dev_selftest ...）绝不随插件发布：它们只在环境变量
    # TIANDITU_SELFTEST 打开时才跑，但没必要发给用户。
    # 端到端测试需要它们时，用 TIANDITU_BUILD_DEV=1 打一个临时测试包。
    if base.startswith("dev_") and not INCLUDE_DEV:
        return True
    return False


def build():
    init = os.path.join(PKG, ENTRY_SRC)
    if not os.path.isfile(init):
        print("ERROR: missing %s" % init, file=sys.stderr)
        return 1
    if os.path.exists(OUT):
        os.remove(OUT)

    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) 根目录：config.xml + README.txt（官方向导同样是平铺在根）
        zf.writestr("config.xml", CONFIG_XML)
        zf.writestr("README.txt", README_TXT)
        # 版本信息（帮助页「关于」读它；运行期拿不到 config.xml）
        zf.writestr("Install/_build_info.py", BUILD_INFO_PY)
        count += 3
        print("  + config.xml")
        print("  + README.txt")
        print("  + Install/_build_info.py")

        # 2) 扁平 Install/：__init__.py -> TiandituTools_addin.py，其余模块保持原名
        for dirpath, dirnames, filenames in os.walk(PKG):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_dir = os.path.relpath(dirpath, PKG)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            for fn in sorted(filenames):
                if should_skip(fn):
                    continue
                full = os.path.join(dirpath, fn)
                if rel_dir == "" and fn == ENTRY_SRC:
                    arc = "Install/" + ENTRY_NAME
                else:
                    arc = "Install/" + (rel_dir + "/" if rel_dir else "") + fn
                zf.write(full, arc)
                count += 1
                print("  +", arc)

        # 3) 图标 -> 根 Images/（config.xml 引用；向导也是复制到根 Images/）
        imgdir = os.path.join(PKG, "images")
        if os.path.isdir(imgdir):
            for fn in sorted(os.listdir(imgdir)):
                full = os.path.join(imgdir, fn)
                if os.path.isfile(full) and not should_skip(fn):
                    zf.write(full, "Images/" + fn)
                    count += 1
                    print("  + Images/%s" % fn)

    size = os.path.getsize(OUT)
    print("Built: %s (%d entries, %d bytes)" % (OUT, count, size))
    return 0


if __name__ == "__main__":
    sys.exit(build())
