# Laptop Sentinel

Laptop Sentinel 是一个基于笔记本摄像头的本地哨兵系统。项目目标不是做一个临时脚本，而是做成个人可用、界面精美、结构可靠的桌面应用。

## 当前能力

项目已经具备第一版桌面应用骨架和核心链路：

- 使用 `pywebview` 创建独立桌面窗口。
- 支持系统托盘、关闭/最小化到托盘和单实例运行。
- 使用 HTML/CSS/JavaScript 构建现代 UI。
- 使用 Python 和 OpenCV 实现摄像头监控、运动检测、预录制和录像。
- 使用 SQLite 保存事件索引。
- 暂缓远程 Webhook 告警，优先打磨本地可用性。

## 文档

- [需求说明书.md](需求说明书.md): MVP 功能范围、状态模型和验收标准。
- [docs/技术方案.md](docs/技术方案.md): 当前采用的三层技术架构。
- [docs/环境准备.md](docs/环境准备.md): 开发环境和依赖安装清单。

## MVP 能力

- 独立桌面窗口控制面板。
- 布防、撤防、触发、冷却状态管理。
- 摄像头低帧率运动检测。
- 触发前内存预录制。
- 触发后本地录像。
- 事件缩略图生成。
- 总览页实时摄像头视窗，可手动开启，按当前采集帧率上限渲染。
- 总览页展示运动分数、ROI 检测区域和运动热区叠加，支持在预览画面上拖拽选择检测区域。
- 内置 Studio、Graphite、Sentinel 三套界面主题。
- SQLite 事件时间线。
- 事件页支持时间筛选、单条删除、批量删除、按保留规则清理和存储占用统计。
- 关闭或最小化窗口时默认进入系统托盘，后台监控继续运行；再次启动会唤起已有窗口。
- 默认使用系统用户目录保存配置、数据和日志，设置页会展示实际路径。
- 支持 Windows 开机自启，可在设置页启用。
- 点击事件调用系统默认播放器。
- 本地配置和日志。

## 环境

使用已创建的 conda 环境：

```powershell
conda activate vision-guard
```

依赖安装见 [docs/环境准备.md](docs/环境准备.md)。

快速安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

安装开发与测试依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

## 启动

```powershell
python -m vision_guard
```

如果 VSCode 当前解释器不是 `vision-guard`，可以使用脚本启动：

```powershell
.\scripts\start.ps1
```

也可以显式指定解释器：

```powershell
$env:VISION_GUARD_PYTHON = "D:\pythonDev\Anaconda\envs\vision-guard\python.exe"
.\scripts\start.ps1
```

如果需要打开 pywebview 调试模式：

```powershell
python -m vision_guard --debug
```

首次启动会从 `config.example.json` 生成配置。桌面模式默认使用系统用户目录：

- 配置：`AppData/Local/Vision Guard/Laptop Sentinel/config.json`
- 数据：`AppData/Local/Vision Guard/Laptop Sentinel/`
- 日志：`AppData/Local/Vision Guard/Laptop Sentinel/Logs/`

如果项目根目录已有旧版 `config.json`，首次桌面化启动会迁移配置。若旧 `storage/` 中已有事件，为避免历史事件不可见，迁移后的保存路径会继续指向旧存储目录；新安装则默认使用系统数据目录。

总览页的实时视窗默认关闭。开启后，前端从后台捕捉引擎读取最近帧，不会额外打开摄像头；离开总览页或窗口不可见时会停止渲染。

实时视窗会显示当前运动分数。分数达到触发阈值时会进入事件录制；热区框用于辅助判断画面中哪些区域贡献了运动分数。可以在预览画面上拖拽选择检测区域，设置会立即保存并影响后续检测；也可以在设置页用百分比精确调整或重置为全画面。

设置页采用左侧分类、右侧分区的专业布局。`Studio` 是默认主题，偏克制、清爽；`Graphite` 是深色生产力风格；`Sentinel` 保留更强的哨兵氛围。

事件页可以在应用内管理录像文件。删除事件会同时删除数据库记录、录像和缩略图；修改保存路径只影响后续新事件，不自动迁移历史录像。

桌面模式默认开启关闭到托盘、最小化到托盘和单实例运行。需要真正退出时，请使用托盘菜单中的“退出 Laptop Sentinel”，或在设置页关闭对应桌面行为。开机自启默认关闭，需要用户主动开启。

## 验证

```powershell
python -m compileall vision_guard tests
python -m ruff check vision_guard tests
python -m pytest
```

## 使用边界

本系统仅适用于用户本人授权的设备和环境。程序不得绕过操作系统摄像头权限、摄像头指示灯或用户安全策略。
