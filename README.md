# Laptop Sentinel / Vision Guard

中文 | [English](README.en.md)

## 简介

Laptop Sentinel 是一个基于笔记本摄像头的本地哨兵系统。它使用 Python、OpenCV 和 pywebview 构建，目标不是临时脚本，而是个人可长期使用的桌面应用。

## 当前能力

- 独立桌面窗口，带系统托盘、关闭/最小化到托盘和单实例运行。
- HTML/CSS/JavaScript 前端，Python/OpenCV 后端。
- 布防、撤防、触发、冷却状态管理。
- 低帧率运动检测、ROI 检测区域、运动分数和热区叠加。
- 触发前内存预录制，触发后本地录像。
- MP4 录像、JPG 缩略图和 SQLite 事件索引。
- 事件页支持时间筛选、单条删除、批量删除、规则清理和存储统计。
- 设置页支持主题、桌面行为、开机自启、保存路径和运行参数配置。

远程 Webhook 告警暂缓实现。当前优先级是本地可用性和桌面应用可靠性。

## 文档

- [需求说明书.md](需求说明书.md): MVP 功能范围、状态模型和验收标准。
- [docs/技术方案.md](docs/技术方案.md): 三层架构、数据流和技术决策。
- [docs/环境准备.md](docs/环境准备.md): 开发环境和依赖安装清单。

## 环境

推荐使用已创建的 conda 环境：

```powershell
conda activate vision-guard
```

安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

安装开发与测试依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

## 启动

开发模式启动：

```powershell
python -m vision_guard
```

如果 VSCode 当前解释器不是 `vision-guard`，可以使用脚本：

```powershell
.\scripts\start.ps1
```

也可以显式指定解释器：

```powershell
$env:VISION_GUARD_PYTHON = "D:\pythonDev\Anaconda\envs\vision-guard\python.exe"
.\scripts\start.ps1
```

打开 pywebview 调试模式：

```powershell
python -m vision_guard --debug
```

## 运行数据

桌面模式默认使用系统用户目录：

- 配置：`AppData/Local/Vision Guard/Laptop Sentinel/config.json`
- 数据：`AppData/Local/Vision Guard/Laptop Sentinel/`
- 日志：`AppData/Local/Vision Guard/Laptop Sentinel/Logs/`

如果项目根目录已有旧版 `config.json`，首次桌面化启动会迁移配置。若旧 `storage/` 中已有事件，迁移后的保存路径会继续指向旧存储目录，避免历史事件不可见。

## 使用说明

实时视窗默认关闭。开启后，前端从后台捕捉引擎读取最近帧，不会额外打开摄像头；离开总览页或窗口不可见时会停止渲染。

实时视窗会显示运动分数、ROI 边框和运动热区。可以在预览画面中拖拽选择检测区域，也可以在设置页用百分比精确调整。

事件页可以管理录像文件。删除事件会同时删除数据库记录、录像和缩略图；修改保存路径只影响后续新事件，不自动迁移历史录像。

桌面模式默认启用关闭到托盘、最小化到托盘和单实例运行。真正退出应用请使用托盘菜单中的“退出 Laptop Sentinel”。开机自启默认关闭，需要用户主动开启。

## 打包

第一代推荐使用 PyInstaller 的 `onedir` + `windowed` 方案，稳定、易检查资源，适合早期产品验收。

示例命令：

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name "Laptop Sentinel" `
  --icon "vision_guard\ui\assets\favicon.ico" `
  --add-data "vision_guard\ui;vision_guard\ui" `
  --add-data "config.example.json;." `
  scripts\start_desktop.py
```

产物位置：

```text
dist\Laptop Sentinel\Laptop Sentinel.exe
```

## 验证

```powershell
python -m compileall vision_guard tests scripts
python -m ruff check vision_guard tests scripts
python -m pytest
node --check vision_guard\ui\app.js
```

## 使用边界

本系统仅适用于用户本人授权的设备和环境。程序不得绕过操作系统摄像头权限、系统摄像头指示灯或用户安全策略。
