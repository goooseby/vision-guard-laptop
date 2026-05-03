# Laptop Sentinel

Laptop Sentinel 是一个基于笔记本摄像头的本地哨兵系统。项目目标不是做一个临时脚本，而是做成个人可用、界面精美、结构可靠的桌面应用。

## 当前能力

项目已经具备第一版桌面应用骨架和核心链路：

- 使用 `pywebview` 创建独立桌面窗口。
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

首次启动会从 `config.example.json` 生成本地 `config.json`。运行数据默认写入：

- `storage/`: 录像、缩略图、事件数据库。
- `logs/`: 运行日志。

总览页的实时视窗默认关闭。开启后，前端从后台捕捉引擎读取最近帧，不会额外打开摄像头；离开总览页或窗口不可见时会停止渲染。

实时视窗会显示当前运动分数。分数达到触发阈值时会进入事件录制；热区框用于辅助判断画面中哪些区域贡献了运动分数。可以在预览画面上拖拽选择检测区域，设置会立即保存并影响后续检测；也可以在设置页用百分比精确调整或重置为全画面。

设置页可以切换界面主题。`Studio` 是默认主题，偏克制、清爽；`Graphite` 是深色生产力风格；`Sentinel` 保留更强的哨兵氛围。

事件页可以在应用内管理录像文件。删除事件会同时删除数据库记录、录像和缩略图；修改保存路径只影响后续新事件，不自动迁移历史录像。

## 验证

```powershell
python -m compileall vision_guard tests
python -m ruff check vision_guard tests
python -m pytest
```

## 使用边界

本系统仅适用于用户本人授权的设备和环境。程序不得绕过操作系统摄像头权限、摄像头指示灯或用户安全策略。
