本项目是一个基于 PyQt5 开发的 UI 系统，用于集成后端逻辑并展示状态机模型。

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




