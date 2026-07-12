本项目是 pyfcstm 的桌面工作台，提供源码编辑、结构化诊断、状态图、普通
仿真、动态用例验证、五类代码生成和统一导出。动态用例验证用于复现确定的
运行场景，不等同于形式化验证。

## 发布包使用

从 GitHub Actions 的 `Build & Verify` 下载与系统匹配的产物：

- `fcstm-gui-linux-x86_64` / `-onefile`
- `fcstm-gui-windows-x86_64` / `-onefile`
- `fcstm-gui-macos-x86_64` / `-onefile`

onedir ZIP 解压后运行目录内的 `fcstm-gui`（Windows 为
`fcstm-gui.exe`）；onefile 产物可直接运行。发布包不需要 Python，但状态图
PNG/SVG/PDF 渲染需要 Java 11 或兼容 JRE。当前 CI 验证的是 GitHub 托管的
Linux x86_64、Windows x86_64 和 macOS Intel 环境，不声称已经在 Windows 7
实机验证。

发布包内置 Noto Sans CJK SC 字体，以保证干净系统上的中文界面可读；字体依据
SIL Open Font License 1.1 分发，许可证位于 `app/resources/fonts/OFL.txt`。

## 产品自检

以下命令不仅 import 模块，还会真实执行 loader、inspect、公式、普通仿真、
四个动态用例、PlantUML、Office 文件、Qt 原生组件、五类模板和至少五条 Z3
求解/优化路径：

```bash
fcstm-gui --self-check --json-report self-check.json
```

GUI 黑盒验收会通过键盘和真实控件完成打开、编辑、诊断定位、状态图、普通
仿真、动态验证、代码生成、统一导出、任务结果和失败恢复，并生成截图与报告：

```bash
fcstm-gui --acceptance-check \
  --viewport 1280x720 \
  --json-report acceptance/report.json \
  --artifact-dir acceptance/artifacts
```

任一独立检查失败都会返回非零退出码。完整操作见
[`docs/使用说明.md`](docs/使用说明.md)，环境问题见
[`docs/故障排查.md`](docs/故障排查.md)，CI 门禁见
[`docs/验收矩阵.md`](docs/验收矩阵.md)。

## 📋 环境要求 (Prerequisites)

为了确保程序正常运行，请遵守以下版本要求：

*   **Python 版本**: Python 3.7.16 
(Docker VNC 镜像)
*   **Java 环境**: 需要安装 JRE (用于支持 PlantUML 功能)

## 🛠️ 安装步骤 (Installation)

### 1. 安装系统依赖 (System Dependencies)
由于项目使用了 PyQt5，在 Linux/Docker 环境下**必须**安装以下系统库，否则会报错 `xcb plugin not found`：

```bash
sudo apt-get update
sudo apt-get install -y \
    python3.7 python3-pip \
    default-jre \
    graphviz \
    libgl1-mesa-glx \
    libegl1-mesa \
    libxkbcommon-x11-0 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libqt5gui5 \
    fonts-wqy-microhei


