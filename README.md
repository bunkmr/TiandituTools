# TiandituTools — ArcMap 天地图底图 / 在线图源插件

ArcMap 10.4 的 Python Add-In。在 ArcMap 里一键加载在线底图、按地名定位，
并且把**任意 `{z}/{x}/{y}` 瓦片源**接进来 —— 这一项 ArcMap 原生做不到。

设计思路与"为什么这么做"见同目录 [`DESIGN.md`](DESIGN.md)。

当前版本 **0.8.0**。

---

## 功能

| 按钮 | 说明 |
|------|------|
| 添加底图 | 内置五组 100+ 条图源，带关键词筛选；双击即加并缩放到全图 |
| 搜索 | 天地图地名检索 / 地理编码 / 逆地理编码；双击结果落点并缩放 |
| 图源管理 | 增删改**自定义 XYZ 瓦片源**，可就地测试连通性 |
| 设置 | Key（多条/随机）、子域、图源启停、XYZ 代理、导入地图包 |
| 帮助 | 快速上手 / 图源说明 / 自定义 XYZ / 常见问题 / 关于（含公众号位） |

### 内置图源（5 组 35 条）

| 组 | 条数 | 说明 |
|----|------|------|
| 天地图（XYZ 接口） | 5 | 矢量 / 影像 / 地形 / 注记；需 Key，国内直连 |
| Esri 在线地图 | 9 | 影像 / 街道 / 地形 / 海洋 / 注记等；**不需 Key**，直连 |
| 国内图源（GCJ-02 偏移） | 4 | 高德影像 / 高德路网注记 / 高德矢量 / 腾讯矢量 |
| 境外图源（需代理） | 15 | Google / OSM / OpenTopoMap / CARTO / Wikimedia / USGS / OpenRailwayMap |
| 专题 · 科研 | 2 | NASA Blue Marble、MODIS 真彩 |

> ⚠ 「国内图源」是 GCJ-02（火星坐标）。栅格瓦片没法在不重采样的前提下纠偏，
> 与 GPS 实测点 / WGS84 矢量叠加会整体偏移 300~600 米。要精确套合请用天地图或 Esri。

## 自定义 XYZ 图源

ArcMap 10.4 **没有** XYZ 图层类型（arcpy 里没有 `MakeWMTSLayer`，
`Layer(<URL>)` 也读不了在线服务）。插件走的路子是：

```
ArcMap ──WMTS GetCapabilities/GetTile──> 本机中转(tile_proxy) ──XYZ──> 图源站点
                ▲                                              │
                └────────── 合成一份 WMTS capabilities ─────────┘
```

即"把任意 XYZ 模板合成成一份 WMTS 服务"给 ArcMap 连；ArcMap 发来的 WMTS
KVP 请求再由中转反翻译回 XYZ 去取瓦片。ArcMap 侧走的仍是与天地图完全相同
的那条已验证通道，所以缩放、拼接、缓存全部正常。

URL 模板占位符：`{z}` `{x}` `{y}` `{-y}`(TMS 南起) `{s}`(子域) `{tk}`(天地图 Key) `{q}`

- 内置清单：`TiandituTools/maps/xyz.json`（只读，升级会覆盖）
- 自定义源：`%APPDATA%\TiandituTools\config.json` 的 `xyzSources`
- 加完源**不用重启** ArcMap：中转按文件 mtime 自动重读清单

## 环境要求

- **ArcMap 10.4**（Windows，自带 Python 2.7.10 32 位 + Tkinter + comtypes）
- 天地图 Key（[申请](https://console.tianditu.gov.cn/api/key)，**浏览器端**类型）
  —— 只用 Esri / 高德 / OSM 的话可以不填
- 境外图源需要自备代理（在「设置 → 图源管理 → XYZ 图源代理」里配）

## 安装

1. 关闭 ArcMap。
2. 双击 `TiandituTools.esriaddin` → Install Add-In。
3. 启动 ArcMap → 菜单「自定义(Customize)」→「工具条(Toolbars)」→ 勾选「天地图 Tools」。
   （本包默认 `showInitially="false"`，原因见 DESIGN.md 第 9 节。）
4. 「设置」里填天地图 Key → 校验并保存。
5. 「添加底图」→ 双击想用的图源。

## 目录结构

```text
projects/arcmap/
├── README.md / DESIGN.md
├── build_addin.py               # 打包（py2/py3 均可）
├── TiandituTools.esriaddin      # 安装包（产物）
├── TiandituTools/
│   ├── __init__.py              # 5 个组件类（打包时改名 TiandituTools_addin.py）
│   ├── ui_bridge.py             # 把界面丢到独立进程（ArcMap 进程内绝不碰 Tkinter）
│   ├── ui_main.py               # 独立进程入口：mode=settings/basemap/search/xyz/help
│   ├── ui_util.py               # 窗口摆放（夹进屏幕 / 居中，兼容高 DPI）
│   ├── ui_menus.py              # 底图选择窗 + 图源枚举
│   ├── ui_xyz.py                # 自定义 XYZ 图源管理器
│   ├── ui_help.py               # 帮助窗（五页签 + 公众号位）
│   ├── ui_settings.py           # 设置窗
│   ├── ui_search.py             # 搜索窗
│   ├── xyz_sources.py           # XYZ 源模型 / capabilities 合成 / 瓦片地址 / 探测
│   ├── tile_proxy.py            # 本机中转：WMTS ⇄ XYZ 翻译（核心）
│   ├── tile_server.py           # 中转进程的起停与端口协商
│   ├── layer_manager.py         # ArcMap 进程内加图层（ArcObjects COM 桥）
│   ├── arcobjects.py            # comtypes 封装的 ArcObjects 调用
│   ├── config.py                # %APPDATA%\TiandituTools\config.json
│   ├── tianditu_api.py          # 天地图 Key 校验 / 检索 API / 地图清单
│   ├── maps/xyz.json            # 内置 XYZ 图源清单
│   ├── maps/tianditu_province.json
│   └── images/*.png|gif         # 工具条图标 + 帮助页页眉/二维码
├── dev_*.py                     # 开发/验证工具（不随插件发布）
└── _*.png / _*.log              # 调试产物（不随插件发布）
```

## 重新打包

```bash
python build_addin.py            # 正式包（自动排除 dev_*）
TIANDITU_BUILD_DEV=1 python build_addin.py   # 含 dev_* 的测试包
```

打包时会顺带把版本号写进 `Install/_build_info.py`（运行期拿不到 config.xml，
帮助页「关于」读它）。

## 开发 / 验证工具

| 脚本 | 用途 |
|------|------|
| `dev_make_icons.py` | 生成全套按钮图标 + 帮助页页眉 GIF + 二维码占位图 |
| `dev_test_help.py` | 起真实界面进程，逐页截图（帮助 5 页 / 图源管理 / 底图 / 设置） |
| `dev_run_check.py` | 启动 ArcMap → 验证加载项 → 打开工具条 → 截图 → 优雅退出 |
| `dev_check_addin.py` | 连到运行中的 ArcMap，列出工具条按钮并截图（用 ArcGIS py2 跑） |
| `dev_install.py` | 装到官方 AddIns 目录（旧安装移到 `_addin_removed_backup`，可还原） |
| `dev_probe_xyz.py` | 批量探测内置 XYZ 图源的连通性 |
| `dev_test_xyz.py` | 端到端：独立中转进程 + capabilities 校验 + 取瓦片 + 粘连串 |
| `dev_selftest.py` | ArcMap 内自检（由环境变量 `TIANDITU_SELFTEST` 驱动） |

## 真机验收清单（Windows + ArcMap 10.4）

- [x] 安装后「自定义 → 工具条」里能看到「天地图 Tools」，5 个按钮图标清晰
- [x] 设置保存 Key / 子域；随机 Key 生效
- [x] 添加天地图底图：自动上图并缩放到全图
- [x] 添加 Esri / 高德 / 腾讯 XYZ 源：自动上图（走 WMTS 翻译通道）
- [x] 放大缩小不白屏（DNS 只解析一次 + IP 直连 + keep-alive + KVP 粘连容错）
- [x] 图源管理：新增 / 复制为自定义 / 测试连通性 / 删除
- [x] 帮助页五页签可开，页眉与二维码占位显示正常
- [x] 地名搜索 → 双击结果 → 落点并缩放
- [ ] 境外图源在配好代理的机器上出图（本机未验）
- [ ] 微信公众号二维码换成真图（等文章发布）

## 与 QGIS 版（TianDiTu Tools 0.6.0）的差异

- 无 QGIS Locator（`tdt` / `tdt-adm` 全局搜索）—— 并入搜索窗口。
- 无 QGIS Dock；界面全部是独立进程里的普通窗口。
- 山东历史影像 dock、FitZoom 未移植。
- **多做了** QGIS 版没有的：任意 XYZ 图源 + 图源管理器 + 帮助页。

## 许可

参考原项目 GPLv3；本移植代码同样以 GPLv3 提供，除非另行说明。
