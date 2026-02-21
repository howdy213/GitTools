# GitHub 备份克隆

Python 编写的跨平台工具，可批量克隆或拉取指定用户的所有仓库。提供图形界面和命令行两种模式。

## 特性

* 自动获取用户所有公共仓库
* 若本地已存在仓库则执行 `git pull` 更新
* 图形界面实时显示每个仓库的状态（处理中/成功/失败/跳过）
* Git 全局配置快捷开关（安全目录通配符、SSL 验证）
* 支持 GitHub Token
* 命令行模式适合脚本集成

## 依赖

* Python 3
* Git 命令行工具

## 使用方法

### 图形界面模式

直接双击运行 `GitBackup.pyw`：

1. 输入 GitHub 用户名。
2. 选择本地存放目录。
3. （可选）填写 GitHub Token。
4. 点击“开始同步”。

### 命令行模式

```bash
python GitBackup.pyw <用户名> [--dir 目录] [--token TOKEN] [--color]
```

参数说明：

* `username`：GitHub 用户名（必填）
* `--dir`：本地根目录，默认为当前目录
* `--token`：GitHub 个人访问令牌
* `--color`：强制启用彩色输出（默认自动检测）

示例：

```bash
python GitBackup.pyw octocat --dir ./github-backup --token ghp_xxxx --color
```

## Git 全局配置快捷开关

工具界面提供了两个 Git 配置开关：

* **添加安全目录通配符**：执行 `git config --global --add safe.directory '\*'`，避免因目录所有者问题导致的错误。
* **启用 SSL 验证**：控制 `http.sslVerify` 配置，默认为启用。在遇到 SSL 证书问题时可以临时关闭。

点击复选框即可应用或取消，工具会自动刷新状态。

## 输出目录结构

在指定的本地根目录下，每个仓库会被克隆到以仓库名命名的文件夹中。例如：

```
./github-backup/
  ├── repo1/
  ├── repo2/
  └── repo3/
```

