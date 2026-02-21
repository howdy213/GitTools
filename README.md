# GitHub 工具集

实用工具的集合，用于简化与 GitHub 仓库的交互。所有工具均为开源，可直接在浏览器或本地运行。

## 工具列表

|工具|描述|快速链接|
|-|-|-|
|**文件批量下载器** (`GitLoad.html`)|通过镜像站加速，选择性下载仓库文件。支持文件树选择、ZIP打包、下载历史等。|[查看文档](docs/GitLoad.md) · [直接使用](GitLoad.html)|
|**仓库统计** (`GitStats.html`)|查看用户所有仓库的星标、分支、语言、更新日期等统计信息。|[查看文档](docs/GitStats.md) · [直接使用](gitstats.html)|
|**备份克隆** (`GitBackup.pyw`)|批量克隆或拉取用户所有仓库。提供图形界面和命令行两种模式，支持 Git 配置快速调整。|[查看文档](docs/GitBackup.md) · [下载脚本](GitBackup.pyw)|

## 快速开始

* **文件批量下载器** 和 **仓库统计** 为纯静态 HTML 页面，直接在浏览器中打开对应的 `.html` 文件即可使用。
* **备份克隆** 需要 Python 3 环境以及 Git 命令行工具，双击运行 `GitBackup.pyw` 启动图形界面，或在终端中以命令行方式执行。

## 许可证

本项目采用 **Apache License, Version 2.0** 进行许可。  
详情请参见项目根目录下的 [LICENSE](LICENSE) 文件。

