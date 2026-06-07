# GitHub 仓库批量备份工具

跨平台的 Python 脚本，支持批量克隆或拉取指定 GitHub 用户的所有公共仓库，并可单独下载最新 Release 附件（自动过滤源码包）。提供图形界面和命令行两种模式，包含进度显示、停止重试、更新判断等功能。

## 特性

- 自动获取用户所有公共仓库列表
- 支持三种操作模式：
  - **仅代码**：克隆 / 拉取仓库
  - **仅 Release**：下载每个仓库最新 Release 附件（自动排除 GitHub 自动生成的源码包）
  - **代码 + Release**：先同步代码，再下载附件
- 下载 Release 时：
  - 先列出所有待下载文件名
  - 显示当前文件下载进度条（带百分比或脉冲动画）
  - 基于文件大小进行增量更新：若本地已存在且大小匹配则跳过，避免重复下载
- 图形界面提供完整交互流程：
  - 先点击“获取仓库列表”查看所有仓库
  - 支持全选 / 取消全选 / 手动多选要处理的仓库
  - 点击“开始同步”仅处理选中仓库
  - 处理过程中可随时“停止”，剩余仓库自动标记为失败
  - “重试失败”按钮可单独重试状态为“失败”的仓库
- Git 全局配置快捷开关（安全目录通配符、SSL 验证）
- 支持 GitHub 个人访问令牌
- 命令行模式适合脚本集成

## 依赖

- Python 3.6+
- Git 命令行工具（需在 PATH 环境变量中可用）

## 使用方法

### 图形界面模式

直接双击运行 `GitBackup.pyw`（无控制台窗口）或 `python GitBackup.py`。

1. 输入目标 GitHub 用户名。
2. 选择本地存放目录（若不存在会自动创建）。
3. （可选）填写 GitHub 个人访问令牌。
4. 选择操作模式：`仅代码` / `仅 Release` / `代码 + Release`。
5. 点击“获取仓库列表”，等待列表加载完毕。
6. 在仓库列表中勾选需要处理的仓库（默认全选）。
7. 点击“开始同步”开始处理。
8. 处理过程中可查看每个仓库的状态（等待 / 处理中 / 成功 / 失败 / 跳过），并可在日志区域看到详细输出。
9. 如需中断，点击“停止”；停止后未处理的仓库会标记为失败，可稍后使用“重试失败”继续。

### 命令行模式

```bash
python GitBackup.pyw <用户名> [选项]
```

#### 参数说明

| 参数                         | 描述                                                         |
| ---------------------------- | ------------------------------------------------------------ |
| `username`                   | 必填，GitHub 用户名                                          |
| `-d DIR`, `--dir DIR`        | 本地根目录，默认为当前目录                                   |
| `-t TOKEN`, `--token TOKEN`  | GitHub 个人访问令牌，用于提高 API 限额                       |
| `--mode {code,release,both}` | 操作模式：`code`=仅代码同步，`release`=仅下载 Release，`both`=代码+Release（默认：`code`） |
| `-r`, `--releases`           | 快捷方式，等效于 `--mode both`（如果同时指定 `--mode` 则以 `--mode` 为准） |
| `--color`                    | 强制启用彩色输出（默认自动检测终端是否支持）                 |

#### 示例

```bash
# 仅同步代码
python GitBackup.pyw octocat --dir ./github-backup --token ghp_xxxx

# 仅下载 Release 附件
python GitBackup.pyw octocat --dir ./backup --mode release

# 同时同步代码和 Release
python GitBackup.pyw octocat -d ./all --mode both --color
```

## Git 全局配置快捷开关

在图形界面中，可直接控制以下两项 Git 全局配置：

- **添加安全目录通配符**  
  执行 `git config --global --add safe.directory '*'`，解决因目录权限 / 所有者问题导致的 `detected dubious ownership` 错误。  
  取消勾选时会移除该通配符配置。

- **启用 SSL 验证**  
  控制 `http.sslVerify` 配置，默认启用。当遇到自签名证书或网络代理问题时，可临时关闭。  
  勾选状态会实时从 Git 全局配置中读取并显示。

> 点击复选框会自动调用 `git config` 命令并刷新界面状态，无需手动编辑配置文件。

## 输出目录结构

所有操作均在指定的本地根目录下进行。

- **代码同步**：每个仓库被克隆到以仓库名命名的文件夹中。
- **Release 下载**：附件统一存放在 `<根目录>/Release/<仓库名>/` 下，文件名保持与发布时一致。

示例结构（模式为 `both`）：

```
backup/
├── repo1/                    # 仓库代码
│   ├── .git/
│   ├── README.md
│   └── ...
├── repo2/                    # 仓库代码
│   └── ...
└── Release/                  # 所有 Release 附件
    ├── repo1/
    │   ├── tool-v1.2.zip
    │   └── manual.pdf
    └── repo2/
        └── app-v3.0.AppImage
```

## 注意事项

- 工具仅处理公共仓库（Public），私有仓库需提供具有相应权限的 Token。
- GitHub API 对未认证请求有严格的速率限制（60 次/小时），建议配置 Token 以提高至 5000 次/小时。
- 命令行模式下不支持停止和重试功能，会顺序处理所有仓库。
- 若下载 Release 时没有获取到文件大小（`Content-Length` 缺失），进度条将切换为脉冲动画，且更新判断仅基于文件名存在性。
- Release 附件中自动排除 `Source code (zip)` 和 `Source code (tar.gz)` 两个 GitHub 自动生成的源码包，避免下载不必要的文件。
