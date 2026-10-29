# yt-dlp UI

基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 的桌面图形界面。项目参考 GitHub 上的 yt-dlp，在此基础上设计全新的 UI，帮助不熟悉命令行操作的用户下载主流媒体平台的视频与音频。界面使用 Python 标准库 tkinter 构建，无需安装额外依赖。

## 功能

- 批量下载：一次粘贴多个链接，自动排队执行
- 四种下载预设：最高画质、1080P 以内、仅视频、仅音频（MP3）
- 实时进度、速度、剩余时间与任务日志
- 取消任务、失败重试、历史记录与状态筛选
- 深色 / 浅色主题，系统标题栏同步变色
- 界面语言：中文、English、日本語、한국어
- 进度动画开关、下载完成提示音（4 种可选，支持试听）
- 主界面直接更改保存位置
- 关于 yt-dlp、隐私政策，以及爱发电捐赠入口

## 环境要求

- Windows，Python 3.9 或更高版本
- 已安装 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，将 `yt-dlp.exe` 放在项目根目录或加入 `PATH`
- 合并视频与音频需要 `ffmpeg`（可选，建议安装）

## 快速开始

1. 获取代码：

   ```bash
   git clone https://github.com/HaiFengjiang/yt-dlp-ui.git
   ```

2. 将 `yt-dlp.exe` 放入项目目录，或确保它已在 `PATH` 中。
3. 双击 `start.cmd` 启动，或执行：

   ```bash
   pythonw gui.py
   ```

配置、任务历史与日志保存在本机 `data/` 目录，不会上传到网络。

## 项目结构

```
core.py    # 下载引擎、任务队列与配置持久化
gui.py     # tkinter 图形界面
i18n.py    # 中文 / English / 日本語 / 한국어 文案
start.cmd  # 启动脚本
data/      # 本地配置与任务记录（运行时生成）
```

## 支持

如果这个项目对你有帮助，可以在应用的「设置 → 支持（爱发电）」中点击「捐赠」，或直接访问 <https://afdian.com/a/sea27378/plan>。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
