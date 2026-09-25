# ArcMap 10.2 天地图影响底图插件 — 开发思路文档

> **先看第 9 节。** 第 1~8 节是动工前的规划（按 ArcMap 10.2 写），
> 第 9 节记录**实际落地**的架构（ArcMap 10.4 / Win11 / v0.8.0）与踩过的坑。
> 两者冲突时以第 9 节为准。

> 源插件：`tianditu-tools-0.6.0.zip`（QGIS 天地图 Tools v0.6.0）  
> 目标：ArcMap 10.2 类似的「天地图 / 影像 / 第三方」在线底图加载与地名检索插件  
> 文档日期：2026-09-24

---

## 1. 源插件（QGIS）功能梳理

### 1.1 定位

QGIS 开源插件 **TianDiTu Tools**：一键添加天地图瓦片底图，封装部分天地图 Web API，并内置第三方在线图源。

### 1.2 功能清单

| 模块 | 功能 | 说明 |
|------|------|------|
| 工具栏 | 专属工具栏 | 底图下拉 + 搜索 + 设置 |
| 底图 | 天地图官方 8 种 | vec/cva/img/cia/ter/cta/ibo/terrain-rgb |
| 底图 | 含注记图层组 | 矢量+注记、影像+注记、地形+注记（组内双图层） |
| 底图 | 省级节点/历史影像 | 江苏、广东、北京、上海等；山东历史影像 dock |
| 底图 | 第三方地图 | Google、ESRI、高德、Stamen、OpenRailwayMap |
| 搜索 | 地名搜索 V2 | 关键词检索，结果树，双击定位 |
| 搜索 | 地理编码 / 逆地理编码 | 地址↔坐标；地图取点反查 |
| 搜索 | 结果定位 | 在「地名搜索结果」图层组添加标记点并缩放 |
| 设置 | 天地图 Key | 多 Key、随机 Key、格式校验、瓦片连通性验证 |
| 设置 | 子域名 | t0–t7 或随机 |
| 设置 | 图源启停 | 省级/第三方图源勾选启停；支持 zip 地图包导入 |
| 定位器 | QGIS Locator | `tdt` 地名搜索、`tdt-adm` 行政区划（QGIS 专有） |

### 1.3 关键实现要点（QGIS）

- 瓦片以 **XYZ URI**（`type=xyz&url=...`）经 `QgsRasterLayer` 加载；天地图走 WMTS 模板 URL + `tk`。
- 配置存 `QgsSettings`（key、keyList、random、subdomain、extramap_status）。
- 网络：`QNetworkAccessManager` / `requests`。
- UI：Qt（Dock、Dialog、Menu）。
- 生命周期：`classFactory(iface)` → `initGui` / `unload`。

### 1.4 图源数据

- `maps/extra.json`：谷歌 3、ESRI 5、高德 5、Stamen 8、铁路 5。
- `maps/tianditu_province.json`：江苏 22、广东 13、北京 11、上海 13（历史/专题 WMTS，经 `wmts.liuxs.pro` 代理）。

---

## 2. 目标环境约束（ArcMap 10.2）

| 约束 | 影响 |
|------|------|
| **Python 2.7** | 无 f-string / pathlib / `urllib.request`；须 `# -*- coding: utf-8 -*-` |
| **Python Add-In (.esriaddin)** | ZIP 包；入口为包内 `__init__.py` 中的组件类（非 QGIS `classFactory`） |
| **无原生 XYZ 栅格类型** | QGIS 的 `type=xyz` **不能直接搬**；天地图须走 **WMTS** |
| **arcpy 10.2 无 WMTS/XYZ 添加 API** | 在线底图需 **ArcObjects COM** 或 **引导手动「Add Data From Web」** |
| **无 QGIS Locator** | 全局搜索定位器不移植；并入搜索窗口 |
| **无 QgsDockWidget** | 用 **Tkinter 无模式对话框**（ArcMap 自带 Python 2.7 Tk） |
| **pywin32 可用** | ArcMap 安装环境自带，用于 ArcObjects |
| **网络 API 可用** | `urllib2` 调天地图搜索/编码 API |

### 2.1 天地图在 ArcMap 中的正确接入方式

天地图官方提供标准 **WMTS**（与 QGIS 版同一服务族）：

```
https://{t0-t7}.tianditu.gov.cn/{layer}_w/wmts
  ?SERVICE=WMTS&REQUEST=GetCapabilities&tk={key}
```

- 添加图层时使用 **GetCapabilities 地址**（ArcMap「Add Data From Web → WMTS」原生支持）。
- 瓦片模板（GetTile）仍可作为备用/校验，但 ArcMap 10.2 **无 XYZ provider**，不能当 QGIS URI 用。

---

## 3. 功能映射：QGIS → ArcMap 10.2

| 优先级 | QGIS 功能 | ArcMap 方案 | 状态 |
|--------|-----------|-------------|------|
| P0 | 天地图官方底图 + 含注记组 | WMTS GetCapabilities；ArcObjects 自动加 / 失败则一键复制 URL + 操作指引 | 实现 |
| P0 | 设置 Key / 子域名 / 多 Key | Tkinter 设置对话框；JSON 配置存 `%APPDATA%` | 实现 |
| P0 | 地名搜索 + 结果打点缩放 | Tkinter 搜索窗；点结果写入临时 CSV/图层后 `arcpy.mapping.AddData` 并缩放 | 实现 |
| P0 | 地理编码 / 逆地理编码 | 同搜索窗 Tab；逆地理支持「地图取点」（简化：输入经纬度） | 实现 |
| P1 | 第三方 ESRI | ESRI 为 ArcGIS REST，优先尝试自动添加；否则同 WMTS 引导 | 实现 |
| P1 | 第三方 Google/高德（XYZ） | ArcMap 10.2 **无 XYZ**；列菜单但走「复制模板说明」或标注受限 | 受限实现 |
| P1 | 省级历史/专题 WMTS | `wmts.liuxs.pro` 的 GetCapabilities，同天地图 WMTS 路径 | 实现 |
| P2 | 地图启停 / 地图包 zip | 设置窗「图源」勾选 + 导入 zip JSON | 实现（简化） |
| P2 | 山东历史影像 dock | 依赖第三方 tk 与专用 WMTS；二期 | 暂缓 |
| P3 | QGIS Locator | 无对应扩展点 | 不做 |
| P3 | FitZoom 专用按钮 | ArcMap 本有全图/缩放，价值低 | 不做 |

---

## 4. 技术方案

### 4.1 插件包结构（.esriaddin）

```
TiandituTools.esriaddin          # ZIP
└── TiandituTools/               # 包名 = 根文件夹名
    ├── __init__.py              # 工具栏 + 按钮/组合框组件类（ArcMap 发现入口）
    ├── config.py                # 配置读写（JSON @ %APPDATA%\TiandituTools）
    ├── tianditu_api.py          # Key、WMTS URL、搜索/编码 HTTP
    ├── layer_manager.py         # 底图/点图层添加（ArcObjects → 回退指引）
    ├── ui_settings.py           # Tkinter 设置对话框
    ├── ui_search.py             # Tkinter 搜索对话框
    ├── ui_menus.py              # 底图分级菜单（Tkinter popup）
    ├── maps/
    │   ├── extra.json
    │   └── tianditu_province.json
    └── images/                  # 16/32 png
```

组件类全部在 `__init__.py` 导出/定义，保证 Add-In 加载器能扫描到。

### 4.2 Add-In 组件约定

- 按钮：`onClick(self)` + 类属性 `caption` / `category` / `tooltip` / `image` 等。
- 下拉：`ComboBox` 或按钮弹出 **Tkinter 菜单**（本方案用按钮+菜单，便于多级：官方/省级/第三方）。
- 工具栏：显式 Toolbar 类，按钮通过类别归属到「天地图」工具栏。
- 无 `classFactory`；打包为 ZIP 即 `.esriaddin`。

### 4.3 底图添加策略链（layer_manager）

```
add_basemap(name, caps_url | xyz_url)
        │
        ├─ 1) ArcObjects：ROT/ProgID 获取 IApplication
        │      → GxDialog(WMTS) / LayerFactory 添加图层
        │      成功 → 刷新 TOC，返回
        │
        └─ 2) 失败回退（保证可用）
               → 复制 GetCapabilities URL 到剪贴板
               → 弹出分步指引：
                  添加数据 → 从易访问的服务器添加数据 → WMTS → 粘贴 URL
```

- **含注记组**：连续添加「底图」「注记」两个 WMTS，注记层置顶。
- **点结果（搜索）**：不走 WMTS，直接 `CSV→XY图层或内存点` + `AddData` + `zoomToExtent`（arcpy 路径，稳定）。

### 4.4 配置存储

路径：`%APPDATA%\TiandituTools\config.json`

```json
{
  "key": "",
  "keyList": [],
  "randomKey": false,
  "subdomain": "t0",
  "randomSubdomain": true,
  "disabledMaps": [],
  "sd_tk": ""
}
```

默认与 QGIS 版字段语义对齐，便于用户迁移心智。

### 4.5 天地图 API（与 QGIS 版一致）

| 用途 | URL |
|------|-----|
| 地名搜索 | `https://api.tianditu.gov.cn/v2/search`（GET，`postStr`/`tk`） |
| 地理编码 | `https://api.tianditu.gov.cn/geocoder?ds=...&tk=` |
| 逆地理编码 | `https://api.tianditu.gov.cn/geocoder?type=geocode&postStr=...&tk=` |
| WMTS 模板 | `https://{sub}.tianditu.gov.cn/{layer}_w/wmts` |

请求头：`User-Agent`、`Referer: https://www.tianditu.gov.cn/`。

### 4.6 UI 布局（Tkinter）

**设置窗（560×420）**  
- Tab1 Key：当前 Key、Key 列表、随机 Key、随机子域、t0–t7、保存/校验  
- Tab2 图源：省节点与第三方勾选列表 + 导入地图包  

**搜索窗（460×340，无模式）**  
- Tab 地名：输入 + 搜索 + 结果列表（双击定位）  
- Tab 地理编码：地址 → 坐标，一键上图  
- Tab 逆编码：`lon,lat` → 地址  

**底图菜单**  
- 天地图官方（单层 + 含注记组）  
- 省级节点子菜单  
- 其他地图子菜单  

### 4.7 Python 2.7 编码规范

- 文件头 `# -*- coding: utf-8 -*-`
- 中文字符串统一 `u""`
- `urllib` + `urllib2` + `json`
- `Tkinter` / `ttk`
- 禁用：f-string、`pathlib`、`print()` 无 future 时的误用（可用 `from __future__ import print_function`）
- 路径：`os.path`；配置用 `io.open(..., encoding='utf-8')`

---

## 5. 与 QGIS 版的差异说明（对用户透明）

1. **XYZ 第三方图**：ArcMap 10.2 不能像 QGIS 一键加 XYZ；ESRI 尽量走 REST/WMTS，Google/高德提供说明或禁用提示。  
2. **Locator**：不提供全局 `tdt` 前缀搜索。  
3. **搜索 UI**：Dock → 独立无模式窗口。  
4. **山体阴影 RGB 色带**：QGIS 用 `maptilerterrain` 解释；ArcMap 无等价 provider，terrain 层以官方 WMTS 为主，不做 RGB 色带模拟。  
5. **自动加载依赖 ArcObjects**：未装完整 ArcMap COM 环境或权限不足时，回退为「复制 URL + 手动添加」，功能仍可用。

---

## 6. 开发与验证计划

| 步骤 | 内容 | 产出 |
|------|------|------|
| 1 | 固化本设计文档 | `DESIGN.md` |
| 2 | 实现 config / API / layer_manager | 核心逻辑（py2） |
| 3 | 实现设置、搜索、底图菜单 | Tkinter UI |
| 4 | 实现 `__init__.py` 工具栏组件 | Add-In 入口 |
| 5 | 移植 maps JSON、生成图标 | 资源 |
| 6 | `build_addin.py` 打包 | `TiandituTools.esriaddin` |
| 7 | 结构校验 + py2 语法兼容检查（能在 py3 下用 `ast`/`compile` 做有限检查，语义按 py2 写） | 验证记录 |
| 8 | 交付 README（安装：自定义目录 / 双击安装） | `README.md` |

### 6.1 安装方式（ArcMap 10.2）

1. 双击 `TiandituTools.esriaddin` 按提示安装；或  
2. 将包放入 `...\Desktop10.2\bin\ESRI.PyAddIn` 管理的 Add-In 目录并重新加载。  

首次使用：工具栏 → 设置 → 填入天地图 Key（浏览器端类型）。

### 6.2 需在 Windows + ArcMap 10.2 真机验证的项

- [ ] 插件安装后工具栏可见  
- [ ] 设置保存/多 Key  
- [ ] WMTS 自动添加成功；失败时剪贴板与指引正确  
- [ ] 搜索打点与缩放  
- [ ] 中文路径/中文输入正常（UTF-8）  

> 本仓库开发环境为 macOS，无法运行 ArcMap；交付物以结构正确、py2 语法兼容、打包完整为验收线，真机项写入 README。

---

## 7. 目录与交付物

```
projects/arcmap/
├── DESIGN.md                      # 本文档
├── README.md                      # 安装与使用
├── TiandituTools/                 # Add-In 源码包
├── build_addin.py                 # 打包脚本
├── TiandituTools.esriaddin        # 安装包
├── tianditu-tools-0.6.0.zip       # 原 QGIS 插件（参考）
└── _extracted/                    # QGIS 插件解压（分析用）
```

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| ArcObjects 动态 COM 接口不稳 | 策略链回退到手动 WMTS；日志记录异常 |
| 天地图 Key/域名策略变化 | Key 设置与 Referer 头可配置；校验用 vec 0/0/0 瓦片 |
| Python 2.7 终止支持 | 锁定 10.2 环境；不引入需 py3 的依赖 |
| XYZ 第三方不可用 | 菜单内标注；优先官方与 ESRI/省级 WMTS |
| `wmts.liuxs.pro` 第三方代理可用性 | 与 QGIS 版同源；失败时提示 |

---

# 9. 实现现状（v0.8.0）—— 实际落地的架构与踩过的坑

> 第 1~8 节是**动工前**的规划（当时按 ArcMap 10.2 写的）。这一节记录
> **真正跑起来之后**的样子。冲突时以本节为准。

## 9.1 目标环境修正

| 项 | 规划 | 实际 |
|----|------|------|
| ArcMap | 10.2 | **10.4.1** |
| 系统 | Windows 7/10 | **Windows 11 25H2** |
| 屏幕 | —— | **3072x1920 / 225% 缩放**（Tk 只看到 1365x853） |
| 加图层 | arcpy 优先 | **只用 ArcObjects COM**（10.4 的 arcpy 没有 MakeWMTSLayer） |

## 9.2 组件与分层

```
入口层  __init__.py（打包后 TiandituTools_addin.py）
        5 个类：AddBasemapButton / SearchButton / XyzManagerButton /
                SettingsButton / HelpButton
        只做 __init__ + onClick；元数据全在 config.xml
桥接层  ui_bridge.py   把界面丢到**独立进程**（本模块不 import Tkinter）
界面层  ui_main.py -> mode=settings|basemap|search|xyz|help
        ui_*.py 的 run_standalone()，配 ui_util.py 做窗口摆放
数据层  ui_menus.py / layer_manager.py / arcobjects.py（ArcMap 进程内）
        xyz_sources.py / tile_proxy.py / tile_server.py（本机中转进程内）
```

## 9.3 四条硬约束（违反必然出事，改动前先读）

**一、Tkinter 绝不能进 ArcMap 进程。**
ArcMap 内部既有把 Tk 消息循环并入主循环的代码，也有会覆盖同一批数据结构
的代码（疑似 vtable 指针被破坏）。在加载项进程内建 Tk 窗口 → 约 20~30 秒后
被 MSVCR 强制中止：
`This application has requested the Runtime to terminate it in an unusual way.`
→ 所有界面走 `ui_bridge` → `ui_main.py` 独立进程，结果以 JSON 回传。

**二、`showInitially="false"`，工具条由用户手动勾选。**
`showInitially="true"` 时 ArcMap 在启动序列里自动创建 Python 加载项工具条，
同样会 CRT abort（退出码 `-1/0xFFFFFFFF`，事件日志里**没有** Application
Error，说明是主动 abort 而非堆损坏）。改成 `false` 后连续观测 100 秒稳定。

**三、造图层必须在 ArcMap 进程内做。**
`esriCarto.WMTSLayer` 是 in-proc 组件。在独立进程里 new 出来再交给 ArcMap，
ArcMap 拿到的是**跨进程代理** → 图层在左侧列表里、画布空白；那个进程一退出
ArcMap 会在几秒内崩。

**四、ArcMap 之外的进程里绝不 import arcpy。**
会拉进 `arcgisscripting → Geoprocessing → RasterCore → DFORRT.dll`。
辅助进程没有控制台，DFORRT 往 unit 0（CONOUT$）写诊断失败就弹
`Visual Fortran run-time error / forrtl: severe (38)` 并**永久卡死**。

## 9.4 XYZ → WMTS 翻译（v0.8.0 新增，本节是重点）

ArcMap 10.4 没有 XYZ 图层类型。方案：把任意 `{z}/{x}/{y}` 模板
**合成一份 WMTS capabilities** 交给 ArcMap，中转再把 ArcMap 发来的
WMTS KVP 请求反翻译成 XYZ 去取瓦片。ArcMap 侧零新增风险 —— 走的是与
天地图 WMTS 完全相同的那条通道。

统一 Web Mercator 格网（与天地图 `/esri/wmts` 逐位对齐）：

| 项 | 值 |
|----|----|
| TopLeftCorner | `-20037508.3427892 20037508.3427892` |
| TileWidth / Height | 256 |
| MatrixWidth = MatrixHeight | `2^z` |
| ScaleDenominator(z) | `559082264.0287178 / 2^z`（z=1 → 279541132.014359） |

### 踩过的三个坑

1. **ArcMap 把 KVP 无分隔符粘到 href 末尾**
   → 实测出现 `?tk=KEYservice=WMTS…`、`TILECOL=421service=WMTS`。
   对策：① 模板里把 `FORMAT=tiles`（中转完全忽略的字符串参数）放**最后**
   当"牺牲位"接住粘上来的尾巴；② 数值参数用 `_int_param()` 取前导整数兜底。
   （修之前粘连串只取回 169 字节，修之后 24514 字节。）

2. **"能放大"是上一版的根因，两条都跟"一次解析、多次复用"有关**
   → 域名每张瓦片重新解析会间歇性超时；改为 **DNS 只解析一次 + IP 直连 +
   每线程 keep-alive**。HTTPS 连 IP 时用自定义 `_HTTPSConn` 重写 `connect()`
   并 `wrap_socket(server_hostname=真实域名)` 带上正确的 SNI；证书不校验
   （瓦片中转不是安全通道，国内自签/域名不匹配的证书很多）。

3. **代理不能默认开**
   → 曾开着全局系统代理，本机中转取一张国内瓦片要 **124 秒**。
   代理做成三态：条目 `proxy: true|false` 优先，否则读全局 `xyzProxy`
   （空=直连 / `auto`=读 `http_proxy` 环境变量或注册表 Internet Settings /
   `host:port`=固定代理）。

### 其它设计点

- **子域 `seq` 固定为 0**：子域由 `(x+y) % len(subdomains)` 决定，保证同一张
  瓦片永远命中同一子域（缓存命中）；`seq` 只用于"第一次失败换个重试"。
- **`sources()` 带 mtime 签名缓存**：中转进程里新加图源不必重启，下次请求即生效。
- **取瓦片失败回 1x1 透明 PNG**，比回 HTML 错误页安全得多。
- **探测口径**：取样点用北京 `(116.391, 39.907)`（用 (0,0) 是几内亚湾，
  矢量图全是空白，第一版就是这么误报 30 个"失败"的）；**空白瓦片算通过**
  —— 服务是好的，只是那个位置没有要素。
- **GCJ-02 必须明示**：栅格瓦片纠不了偏。条目记 `datum:"gcj02"`，
  列表里显示警告，加图层时一次性 MessageBox。

## 9.5 界面与图标

- **Tk 8.5 的 PhotoImage 不认 PNG**（实测 `TclError: couldn't recognize data`）
  → 帮助页页眉只能用 **GIF**（`images/help_logo.gif`）。
  工具条图标给 ArcMap 用，PNG 没问题（16/24/32 三档）。
- **图标设计语言**（`dev_make_icons.py`，改图标请沿用）：圆角渐变底板
  `#3B8FE0→#1462B4` + 描边 `#0E4C8C` + 上缘高光；图形白色、强调用橙
  `#FF9F1C`；五个按钮共用同一块底板靠图形区分；每个尺寸独立 4 倍超采样后
  LANCZOS 缩小（旧的 16px 直接复用 32px，必然糊）。
- **窗口摆放走 `ui_util.py`**，别各自写 `geometry()`：225% 缩放下屏高只有
  853 逻辑像素，Tk 默认把窗口级联到右下会把底部按钮条压到任务栏底下。
- **帮助页「关于」里的公众号位是预留的**：`config.json` 的
  `wechatName` / `wechatArticleUrl` / `wechatTip` 默认为空 → 显示占位 +
  一张占位二维码（`images/wechat_qr.gif`）。文章发布后用户自己填、点保存即可，
  **不用等插件升级**；真二维码用同名文件覆盖 `wechat_qr.gif` 就换上了。
  （PhotoImage 不能缩放，所以大图按整数因子 subsample 到 ~150px，
  另给「查看原图」按钮保证扫码质量。）
- **帮助页正文支持极简标记**：`# ` 大标题 / `## ` 小节 / `!!` 警示（橙）/
  `++` 正面（绿）/ `> ` 示例（灰底等宽）/ `**粗体**`。
  粗体一律用**复合标签名**（`bold_h1`、`bold_warn`…）—— Tk 标签优先级按
  **创建顺序**，`"bold"` + `"h1"` 两个标签叠加时后建的 `h1` 会盖掉粗体字体。

## 9.6 打包

- `.esriaddin` 就是 ZIP，根目录平铺 `config.xml` / `README.txt` / `Install/`
  / `Images/`；`Install/` 会在加载时解包到 AssemblyCache（`images/`、`maps/`
  也在里面，所以运行期可以用 `os.path.dirname(__file__)` 找到它们）。
- 中文元数据一律用**数字字符引用**（`&#28155;`），不受解析编码影响。
- `<Toolbar>` **不能写 `class` 属性**（Python 加载项没有 Toolbar 类）。
- 版本号在 `build_addin.py` 的 `VERSION`，打包时写进 `Install/_build_info.py`
  —— 运行期既拿不到 `build_addin.py` 也拿不到 `config.xml`（后者留在压缩包里），
  帮助页「关于」只能读这个注入的小模块。
- `README_TXT` 里有 `%(name)s` 这种 %-格式化，正文里出现字面 `%APPDATA%`
  必须写成 `%%APPDATA%%`，否则格式化直接抛异常。

## 9.7 验证工具链（`dev_*.py`，不随插件发布）

| 脚本 | 验什么 |
|------|--------|
| `dev_make_icons.py` | 图标/页眉/二维码占位图生成 |
| `dev_test_xyz.py` | 端到端：**真实独立中转进程** + capabilities 6 项校验 + 取瓦片 + 粘连串 + 老链路未坏 |
| `dev_probe_xyz.py` | 批量探测内置图源（多线程） |
| `dev_test_help.py` | 起真实界面进程逐页**截图**（排版/字体/图片加载问题只有肉眼看得见） |
| `dev_run_check.py` | 启动 ArcMap → 查加载项 → 开工具条 → 截图 → 优雅退出 |
| `dev_check_addin.py` | 连运行中的 ArcMap，列工具条按钮 |
| `dev_install.py` | 装到官方 AddIns 目录（旧安装**移动**到 `_addin_removed_backup`，可还原） |

写 py2 测试脚本时两个高频坑：`io.open(1,"w")` 只收 unicode（`print()` 补的
换行是 `str`）→ 自定义 `_Out` 包一层；命令行 `sys.argv` 是 GBK 字节串 →
`kw = sys.argv[1].decode("mbcs","ignore")`。

截图验证时的坑：`GetWindowRect` 在"调用进程 DPI-aware、目标窗口 DPI-unaware"
时会给出跟屏幕实况对不上的值 → 用
`DwmGetWindowAttribute(h, DWMWA_EXTENDED_FRAME_BOUNDS=9)`；而且**必须在截屏前
重新量一次**窗口位置（窗口出生在 Tk 默认位置，之后才被 `ui_util` 挪走）。

