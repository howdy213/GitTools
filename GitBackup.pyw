#!/usr/bin/env python3
"""
GitHub 仓库批量克隆/拉取工具
- 命令行：python script.py <username> [--dir DIR] [--token TOKEN] [--color] [--mode ...]
- GUI：python script.py（不带参数启动图形界面）
Token 可从 token.txt 自动读取（优先使用命令行/GUI 输入）。
"""

import os
import sys
import json
import subprocess
import argparse
import urllib.request
import urllib.error
import threading
import queue

# -------------------- 颜色支持 --------------------
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def supports_color():
    if not sys.stdout.isatty():
        return False
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            return True
        except Exception:
            return False
    return True


def color_text(text, color_code, use_color):
    if use_color:
        return f"{color_code}{text}{Colors.ENDC}"
    return text


# -------------------- Token 文件读取 --------------------
def _get_script_dir():
    """返回脚本（或打包后 exe）所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def load_token_from_file():
    """从脚本目录下的 token.txt 读取 token（仅第一行非空内容）"""
    token_file = os.path.join(_get_script_dir(), "token.txt")
    try:
        if os.path.isfile(token_file):
            with open(token_file, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        return stripped
    except Exception:
        pass
    return None


# -------------------- Git 认证辅助 --------------------
def build_auth_url(url, token):
    """把 token 注入 HTTPS URL 用于 git 认证（token 作为用户名）。"""
    if not token:
        return url
    if url.startswith("https://"):
        return "https://" + token + "@" + url[len("https://"):]
    return url


def sanitize_text(text, token):
    if not token or not text:
        return text
    return text.replace(token, "***")


# -------------------- 核心功能 --------------------
def _api_error_message(e, default_msg):
    """从 HTTPError 中提取更详细的信息（含 rate limit 判断）。"""
    body = ""
    try:
        body = e.read().decode(errors="replace")
    except Exception:
        pass
    body_low = body.lower()
    if e.code == 403 and "rate limit" in body_low:
        return "API 速率限制已用尽。请稍后再试，或使用个人访问令牌提高限制。"
    if e.code == 401:
        return "认证失败：Token 无效或已过期。"
    if e.code == 404:
        return None  # 由调用方处理
    return f"{default_msg}: HTTP {e.code} {body[:200]}"


def get_user_repos(username, token=None):
    repos = []
    page = 1
    per_page = 100

    if token:
        base_url = "https://api.github.com/user/repos"
    else:
        base_url = f"https://api.github.com/users/{username}/repos"

    while True:
        url = f"{base_url}?page={page}&per_page={per_page}&type=all"
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if not data:
                    break
                for repo in data:
                    if token:
                        owner_login = repo["owner"]["login"]
                        if owner_login.lower() != username.lower():
                            continue
                    repos.append({
                        "name": repo["name"],
                        "clone_url": repo["clone_url"],
                        "full_name": repo["full_name"],
                        "private": repo.get("private", False),
                    })
                link_header = response.headers.get("Link")
                if link_header and 'rel="next"' in link_header:
                    page += 1
                else:
                    break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Exception(f"用户 {username} 不存在或没有公共仓库。")
            msg = _api_error_message(e, "API 请求失败")
            raise Exception(msg or f"API 请求失败: {e}")
        except Exception as e:
            raise Exception(f"发生错误: {e}")

    return repos


def get_latest_release_assets(full_name, token=None):
    url = f"https://api.github.com/repos/{full_name}/releases/latest"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            release = json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        msg = _api_error_message(e, f"获取 Release 失败 ({full_name})")
        raise Exception(msg or f"获取 Release 失败 ({full_name}): {e}")
    except Exception as e:
        raise Exception(f"发生错误: {e}")

    assets = []
    for asset in release.get("assets", []):
        name = asset["name"]
        if name.lower() in ["source code (zip)", "source code (tar.gz)"]:
            continue
        assets.append({
            "name": name,
            "asset_id": asset["id"],
            "size": asset.get("size", 0),
        })
    return assets


def download_asset(repo_full_name, asset_id, save_path, token=None,
                   expected_size=0, output_callback=None, progress_callback=None):
    if os.path.exists(save_path):
        local_size = os.path.getsize(save_path)
        if expected_size > 0 and local_size == expected_size:
            if output_callback:
                output_callback(f"  文件已存在且大小一致，跳过: {os.path.basename(save_path)}")
            if progress_callback:
                progress_callback(-1, -1)
            return True
        elif expected_size == 0:
            if output_callback:
                output_callback(f"  已存在，跳过: {os.path.basename(save_path)}")
            if progress_callback:
                progress_callback(-1, -1)
            return True
        else:
            if output_callback:
                output_callback(
                    f"  文件大小不一致，重新下载: {os.path.basename(save_path)} "
                    f"(本地 {local_size}, 远程 {expected_size})"
                )

    if output_callback:
        output_callback(f"  下载: {os.path.basename(save_path)}")

    api_url = f"https://api.github.com/repos/{repo_full_name}/releases/assets/{asset_id}"
    headers = {"Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"token {token}"

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    tmp_path = save_path + ".part"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            total_size = resp.headers.get('Content-Length')
            total_size = int(total_size) if total_size else 0
            downloaded = 0
            chunk_size = 65536
            with open(tmp_path, 'wb') as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        # 原子替换，避免中断后留下残缺文件
        os.replace(tmp_path, save_path)

        if progress_callback:
            progress_callback(downloaded, total_size)
        return True
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        if output_callback:
            output_callback(f"  下载失败: {e}")
        if progress_callback:
            progress_callback(-1, -1)
        return False


def download_latest_release(repo_info, base_dir, token=None,
                            output_callback=None, progress_callback=None):
    repo_name = repo_info["name"]
    full_name = repo_info.get("full_name")
    if not full_name:
        if output_callback:
            output_callback(f"缺少仓库全名，跳过 Release: {repo_name}")
        return True
    if output_callback:
        output_callback(f"--- 下载最新 Release 附件: {repo_name} ---")
    try:
        assets = get_latest_release_assets(full_name, token)
    except Exception as e:
        if output_callback:
            output_callback(f"获取 Release 失败: {e}")
        return False
    if not assets:
        if output_callback:
            output_callback("  无符合条件的附件")
        return True

    if output_callback:
        output_callback("  附件列表：")
        for i, asset in enumerate(assets, 1):
            output_callback(f"    {i}. {asset['name']}")

    release_dir = os.path.join(base_dir, "Release", repo_name)
    all_ok = True
    for asset in assets:
        save_path = os.path.join(release_dir, asset["name"])

        def asset_progress(downloaded, total, _name=asset["name"]):
            if progress_callback:
                progress_callback(_name, downloaded, total)

        ok = download_asset(
            repo_full_name=full_name,
            asset_id=asset["asset_id"],
            save_path=save_path,
            token=token,
            expected_size=asset["size"],
            output_callback=output_callback,
            progress_callback=asset_progress,
        )
        if not ok:
            all_ok = False
    if progress_callback:
        progress_callback(None, -1, -1)
    return all_ok


def run_git_command(cmd, cwd=None, output_callback=None, sanitize=None):
    """执行 git 命令。sanitize 中的字符串（通常是 token）在输出中会被替换为 ***。"""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        process = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=creationflags,
        )
        output_lines = []
        for line in process.stdout:
            line = line.rstrip()
            if sanitize:
                line = line.replace(sanitize, "***")
            output_lines.append(line)
            if output_callback:
                output_callback(line)
        process.wait()
        return process.returncode == 0, "\n".join(output_lines)
    except Exception as e:
        return False, str(e)


def _remote_has_token(local_path, token):
    """检查已有仓库的 origin URL 是否已包含认证信息。"""
    ok, current = run_git_command(
        ["git", "remote", "get-url", "origin"], cwd=local_path, sanitize=token
    )
    if not ok:
        return True  # 没有 origin 或读取失败，不再折腾
    return token in current


def clone_or_pull(repo_info, base_dir, status_callback=None, output_callback=None,
                  stop_event=None, token=None):
    repo_name = repo_info["name"]
    repo_url = repo_info["clone_url"]
    local_path = os.path.normpath(os.path.join(base_dir, repo_name))

    if stop_event and stop_event.is_set():
        if status_callback:
            status_callback(repo_name, "失败")
        return False

    if status_callback:
        status_callback(repo_name, "处理中")

    auth_url = build_auth_url(repo_url, token)
    display_url = sanitize_text(auth_url, token)

    if not os.path.exists(local_path):
        if output_callback:
            output_callback(f"克隆 {display_url} 到 {local_path}")
        success, _ = run_git_command(
            ["git", "clone", auth_url, local_path],
            output_callback=output_callback, sanitize=token,
        )
    else:
        if not os.path.isdir(os.path.join(local_path, ".git")):
            if output_callback:
                output_callback(f"跳过: {local_path} 不是 Git 仓库")
            if status_callback:
                status_callback(repo_name, "跳过")
            return False

        # 有 token 时确保 origin 带认证信息，避免拉取时无法认证
        if token and not _remote_has_token(local_path, token):
            run_git_command(
                ["git", "remote", "set-url", "origin", auth_url],
                cwd=local_path, sanitize=token,
            )

        if output_callback:
            output_callback(f"拉取 {local_path}")
        success, _ = run_git_command(
            ["git", "pull"], cwd=local_path,
            output_callback=output_callback, sanitize=token,
        )

    if status_callback:
        status_callback(repo_name, "成功" if success else "失败")
    return success


# -------------------- 命令行模式 --------------------
def main_cli():
    parser = argparse.ArgumentParser(description="批量克隆或拉取指定 GitHub 用户的所有仓库。")
    parser.add_argument("username", help="GitHub 用户名")
    parser.add_argument("-d", "--dir", default=".", help="本地存放仓库的根目录（默认当前目录）")
    parser.add_argument("-t", "--token", help="GitHub 个人访问令牌")
    parser.add_argument("--mode", choices=["code", "release", "both"], default="code",
                        help="操作模式：code=仅代码同步，release=仅下载Release，both=代码+Release")
    parser.add_argument("-r", "--releases", action="store_true",
                        help="同时下载Release (等效于 --mode both)")
    parser.add_argument("--color", action="store_true", help="启用彩色输出")
    args = parser.parse_args()

    if args.releases and args.mode == "code":
        args.mode = "both"

    # Token 优先级：命令行 > token.txt
    token = args.token if args.token else load_token_from_file()

    use_color = args.color or supports_color()
    base_dir = os.path.abspath(args.dir)
    if not os.path.exists(base_dir):
        try:
            os.makedirs(base_dir)
            print(color_text(f"创建目录: {base_dir}", Colors.OKBLUE, use_color))
        except OSError as e:
            sys.exit(f"无法创建目录 {base_dir}: {e}")

    def colored_output(msg):
        if "克隆" in msg or "拉取" in msg:
            print(color_text(msg, Colors.OKBLUE, use_color))
        elif "成功" in msg or "完成" in msg:
            print(color_text(msg, Colors.OKGREEN, use_color))
        elif "失败" in msg or "错误" in msg or "跳过" in msg:
            print(color_text(msg, Colors.FAIL, use_color))
        else:
            print(msg)

    try:
        repos = get_user_repos(args.username, token)
    except Exception as e:
        sys.exit(f"错误: {e}")

    for repo in repos:
        code_ok = True
        rel_ok = True
        if args.mode in ("code", "both"):
            code_ok = clone_or_pull(repo, base_dir, output_callback=colored_output, token=token)
        if args.mode in ("release", "both"):
            rel_ok = download_latest_release(repo, base_dir, token, output_callback=colored_output)
        if args.mode == "both" and not (code_ok and rel_ok):
            print(color_text(f"[{repo['name']}] 同步存在失败项", Colors.FAIL, use_color))


# -------------------- GUI 模式 --------------------
def main_gui():
    if sys.platform == 'win32' and len(sys.argv) == 1:
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except Exception:
            pass

    import tkinter as tk
    from tkinter import scrolledtext, filedialog, messagebox
    from tkinter import ttk

    class GitHubClonerApp:
        def __init__(self, root):
            self.root = root
            self.root.title("GitHub 仓库批量克隆/拉取工具")
            self.root.geometry("850x750")

            self.username_var = tk.StringVar()
            self.dir_var = tk.StringVar(value=os.getcwd())
            self.token_var = tk.StringVar()
            self.mode_var = tk.StringVar(value="code")
            self.safe_dir_var = tk.BooleanVar(value=False)
            self.ssl_verify_var = tk.BooleanVar(value=True)

            self.repo_infos = {}
            self.repo_items = {}
            self.stop_event = threading.Event()
            self.is_running = False

            # 尝试从 token.txt 预填充 Token 输入框
            file_token = load_token_from_file()
            if file_token:
                self.token_var.set(file_token)

            self.create_widgets()
            self.update_config_status()
            self.update_button_states()

            self.output_queue = queue.Queue()
            self.status_queue = queue.Queue()
            self.update_ui()

        def create_widgets(self):
            input_frame = ttk.LabelFrame(self.root, text="设置", padding=5)
            input_frame.pack(fill="x", padx=5, pady=5)

            ttk.Label(input_frame, text="GitHub 用户名:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.username_var, width=40).grid(
                row=0, column=1, padx=5, pady=5, sticky="we")

            ttk.Label(input_frame, text="本地目录:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.dir_var, width=40).grid(
                row=1, column=1, padx=5, pady=5, sticky="we")
            ttk.Button(input_frame, text="浏览...", command=self.browse_dir).grid(
                row=1, column=2, padx=5, pady=5)

            ttk.Label(input_frame, text="Token (可选):").grid(row=2, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.token_var, width=40, show="*").grid(
                row=2, column=1, padx=5, pady=5, sticky="we")

            mode_frame = ttk.LabelFrame(input_frame, text="操作模式", padding=5)
            mode_frame.grid(row=3, column=1, sticky="w", padx=5, pady=5)
            ttk.Radiobutton(mode_frame, text="仅代码", variable=self.mode_var, value="code").pack(side="left", padx=5)
            ttk.Radiobutton(mode_frame, text="仅 Release", variable=self.mode_var, value="release").pack(side="left", padx=5)
            ttk.Radiobutton(mode_frame, text="代码 + Release", variable=self.mode_var, value="both").pack(side="left", padx=5)

            btn_frame = ttk.Frame(input_frame)
            btn_frame.grid(row=4, column=1, pady=10, sticky="w")
            self.fetch_button = ttk.Button(btn_frame, text="获取仓库列表", command=self.fetch_repos)
            self.fetch_button.pack(side="left", padx=5)
            self.start_button = ttk.Button(btn_frame, text="开始同步", command=self.start_sync, state="disabled")
            self.start_button.pack(side="left", padx=5)
            self.stop_button = ttk.Button(btn_frame, text="停止", command=self.stop_sync, state="disabled")
            self.stop_button.pack(side="left", padx=5)
            self.retry_button = ttk.Button(btn_frame, text="重试失败", command=self.retry_failed, state="disabled")
            self.retry_button.pack(side="left", padx=5)

            config_frame = ttk.LabelFrame(self.root, text="Git 全局配置", padding=5)
            config_frame.pack(fill="x", padx=5, pady=5)

            self.safe_dir_cb = ttk.Checkbutton(
                config_frame,
                text="添加安全目录通配符 (safe.directory = '*')",
                variable=self.safe_dir_var, command=self.on_safe_directory_toggle)
            self.safe_dir_cb.grid(row=0, column=0, sticky="w", padx=5, pady=2)

            self.ssl_verify_cb = ttk.Checkbutton(
                config_frame,
                text="启用 SSL 验证 (http.sslVerify)",
                variable=self.ssl_verify_var, command=self.on_ssl_verify_toggle)
            self.ssl_verify_cb.grid(row=1, column=0, sticky="w", padx=5, pady=2)

            main_panel = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
            main_panel.pack(fill="both", expand=True, padx=5, pady=5)

            list_frame = ttk.LabelFrame(main_panel, text="仓库列表")
            main_panel.add(list_frame, weight=1)

            select_toolbar = ttk.Frame(list_frame)
            select_toolbar.pack(fill="x", padx=2, pady=2)
            ttk.Button(select_toolbar, text="全选", command=self.select_all).pack(side="left", padx=2)
            ttk.Button(select_toolbar, text="取消全选", command=self.deselect_all).pack(side="left", padx=2)

            columns = ("status",)
            self.tree = ttk.Treeview(list_frame, columns=columns, show="tree headings",
                                     selectmode="extended", height=15)
            self.tree.heading("#0", text="仓库名称")
            self.tree.heading("status", text="状态")
            self.tree.column("#0", width=180)
            self.tree.column("status", width=80, anchor="center")

            # 预先配置 tag 颜色，避免反复配置
            self.tree.tag_configure("success", foreground="green")
            self.tree.tag_configure("fail", foreground="red")
            self.tree.tag_configure("processing", foreground="blue")

            tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=tree_scroll.set)
            tree_scroll.pack(side="right", fill="y")
            self.tree.pack(side="left", fill="both", expand=True)

            right_frame = ttk.Frame(main_panel)
            main_panel.add(right_frame, weight=2)

            log_frame = ttk.LabelFrame(right_frame, text="详细日志")
            log_frame.pack(fill="both", expand=True)
            self.output_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
            self.output_text.pack(fill="both", expand=True)

            progress_frame = ttk.Frame(right_frame)
            progress_frame.pack(fill="x", pady=5)
            self.progress_label = ttk.Label(progress_frame, text="下载进度：")
            self.progress_label.pack(side="left")
            self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=300)
            self.progress_bar.pack(side="left", fill="x", expand=True, padx=5)

        def browse_dir(self):
            directory = filedialog.askdirectory(initialdir=self.dir_var.get())
            if directory:
                self.dir_var.set(directory)

        def select_all(self):
            for item in self.tree.get_children():
                self.tree.selection_add(item)

        def deselect_all(self):
            self.tree.selection_remove(self.tree.get_children())

        def update_button_states(self):
            if self.is_running:
                self.fetch_button.config(state="disabled")
                self.start_button.config(state="disabled")
                self.stop_button.config(state="normal")
                self.retry_button.config(state="disabled")
            else:
                has_list = len(self.tree.get_children()) > 0
                self.fetch_button.config(state="normal")
                self.start_button.config(state="normal" if has_list else "disabled")
                self.stop_button.config(state="disabled")
                self.retry_button.config(state="normal" if has_list else "disabled")

        def update_config_status(self):
            try:
                result = subprocess.run(
                    ["git", "config", "--global", "--get-all", "safe.directory"],
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                self.safe_dir_var.set(
                    '*' in result.stdout.strip().split('\n') if result.returncode == 0 else False)
            except Exception:
                self.safe_dir_var.set(False)

            try:
                result = subprocess.run(
                    ["git", "config", "--global", "--get", "http.sslVerify"],
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                self.ssl_verify_var.set(
                    result.stdout.strip().lower() == "true" if result.returncode == 0 else True)
            except Exception:
                self.ssl_verify_var.set(True)

        def set_config_controls_state(self, state):
            self.safe_dir_cb.config(state=state)
            self.ssl_verify_cb.config(state=state)

        def on_safe_directory_toggle(self):
            target = self.safe_dir_var.get()
            self.set_config_controls_state("disabled")
            old_state = not target
            try:
                cmd = (["git", "config", "--global", "--add", "safe.directory", "*"] if target
                       else ["git", "config", "--global", "--unset-all", "safe.directory"])
                result = subprocess.run(
                    cmd, capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode != 0:
                    self.safe_dir_var.set(old_state)
                    messagebox.showerror("错误", f"执行 Git 命令失败:\n{result.stderr}")
                else:
                    self.update_config_status()
            except Exception as e:
                self.safe_dir_var.set(old_state)
                messagebox.showerror("错误", f"发生异常:\n{e}")
            finally:
                self.set_config_controls_state("normal")

        def on_ssl_verify_toggle(self):
            target = self.ssl_verify_var.get()
            self.set_config_controls_state("disabled")
            old_state = not target
            try:
                value = "true" if target else "false"
                cmd = ["git", "config", "--global", "http.sslVerify", value]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                if result.returncode != 0:
                    self.ssl_verify_var.set(old_state)
                    messagebox.showerror("错误", f"执行 Git 命令失败:\n{result.stderr}")
                else:
                    self.update_config_status()
            except Exception as e:
                self.ssl_verify_var.set(old_state)
                messagebox.showerror("错误", f"发生异常:\n{e}")
            finally:
                self.set_config_controls_state("normal")

        def fetch_repos(self):
            username = self.username_var.get().strip()
            if not username:
                messagebox.showerror("错误", "请输入 GitHub 用户名")
                return
            token = self.token_var.get().strip() or None

            self.output_text.delete(1.0, tk.END)
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.repo_items.clear()
            self.repo_infos.clear()

            def fetch_thread():
                try:
                    repos = get_user_repos(username, token)
                except Exception as e:
                    self.output_queue.put(("log", f"错误: {e}"))
                    self.output_queue.put(("fetch_done", None))
                    return
                self.output_queue.put(("log", f"共找到 {len(repos)} 个仓库"))
                self.output_queue.put(("repos_list", repos))
                self.output_queue.put(("fetch_done", None))

            self.is_running = True
            self.update_button_states()
            thread = threading.Thread(target=fetch_thread)
            thread.daemon = True
            thread.start()

        def populate_repo_list(self, repos):
            for repo in repos:
                name = repo["name"]
                self.repo_infos[name] = repo
                item_id = self.tree.insert("", "end", text=name, values=("等待",))
                self.repo_items[name] = item_id
                self.tree.selection_add(item_id)
            self.update_button_states()

        def _run_sync(self, repos_to_process, base_dir, token, mode):
            """在后台线程中同步指定仓库列表。"""
            def status_cb(name, status):
                self.status_queue.put((name, status))

            def out_cb(msg):
                self.output_queue.put(("log", msg))

            def prog_cb(filename, downloaded, total):
                self.output_queue.put(("progress", filename, downloaded, total))

            self.output_queue.put(("log", f"开始处理 {len(repos_to_process)} 个仓库..."))

            for repo in repos_to_process:
                if self.stop_event.is_set():
                    self.output_queue.put(("log", "用户停止，剩余未处理仓库将被标记为失败。"))
                    break

                code_ok = True
                rel_ok = True

                if mode in ("code", "both"):
                    code_ok = clone_or_pull(
                        repo, base_dir,
                        status_callback=status_cb,
                        output_callback=out_cb,
                        stop_event=self.stop_event,
                        token=token,
                    )

                if mode in ("release", "both") and not self.stop_event.is_set():
                    rel_ok = download_latest_release(
                        repo, base_dir, token,
                        output_callback=out_cb,
                        progress_callback=prog_cb,
                    )

                # 统一最终状态
                if mode == "release":
                    status_cb(repo["name"], "成功" if rel_ok else "失败")
                elif mode == "both":
                    status_cb(repo["name"], "成功" if (code_ok and rel_ok) else "失败")

            self.output_queue.put(("sync_done", None))

        def start_sync(self):
            if self.is_running:
                return
            selected = self.tree.selection()
            if not selected:
                messagebox.showinfo("提示", "没有选中的仓库。")
                return

            selected_names = [self.tree.item(item, "text") for item in selected]
            base_dir = self.dir_var.get().strip()
            token = self.token_var.get().strip() or None
            if not os.path.exists(base_dir):
                try:
                    os.makedirs(base_dir)
                except Exception as e:
                    messagebox.showerror("错误", f"无法创建目录: {e}")
                    return

            self.stop_event.clear()
            self.is_running = True
            self.update_button_states()
            mode = self.mode_var.get()

            repos_to_process = [self.repo_infos[name] for name in selected_names if name in self.repo_infos]
            thread = threading.Thread(target=self._run_sync,
                                      args=(repos_to_process, base_dir, token, mode))
            thread.daemon = True
            thread.start()

        def stop_sync(self):
            self.stop_event.set()
            self.output_queue.put(("log", "正在停止..."))
            for item in self.tree.get_children():
                status = self.tree.item(item, "values")[0]
                if status in ("等待", "处理中"):
                    self.tree.item(item, values=("失败",), tags=("fail",))
            self.reset_progress_bar()

        def retry_failed(self):
            if self.is_running:
                return
            failed_items = [item for item in self.tree.get_children()
                            if self.tree.item(item, "values")[0] == "失败"]
            if not failed_items:
                messagebox.showinfo("提示", "没有失败的仓库需要重试。")
                return

            base_dir = self.dir_var.get().strip()
            token = self.token_var.get().strip() or None
            if not os.path.exists(base_dir):
                messagebox.showerror("错误", "本地目录不存在")
                return

            self.stop_event.clear()
            self.is_running = True
            self.update_button_states()
            mode = self.mode_var.get()

            failed_names = [self.tree.item(item, "text") for item in failed_items]
            repos_to_retry = [self.repo_infos[name] for name in failed_names if name in self.repo_infos]

            thread = threading.Thread(target=self._run_sync,
                                      args=(repos_to_retry, base_dir, token, mode))
            thread.daemon = True
            thread.start()

        def reset_progress_bar(self):
            self.progress_bar.stop()
            self.progress_bar['value'] = 0
            self.progress_bar['maximum'] = 100
            self.progress_bar['mode'] = 'determinate'
            self.progress_label['text'] = "下载进度："

        def handle_progress(self, filename, downloaded, total):
            if downloaded == -1 and total == -1:
                self.reset_progress_bar()
                return
            if filename is None:
                self.reset_progress_bar()
                return

            short_name = filename if len(filename) < 30 else filename[:27] + "..."
            self.progress_label['text'] = f"下载进度：{short_name}"

            if total > 0:
                self.progress_bar['mode'] = 'determinate'
                self.progress_bar['maximum'] = total
                self.progress_bar['value'] = downloaded
            else:
                self.progress_bar['mode'] = 'indeterminate'
                self.progress_bar.start(10)

        def update_ui(self):
            try:
                while True:
                    item = self.output_queue.get_nowait()
                    if isinstance(item, tuple):
                        msg_type = item[0]
                        if msg_type == "log":
                            self.output_text.insert(tk.END, item[1] + "\n")
                            self.output_text.see(tk.END)
                        elif msg_type == "repos_list":
                            self.populate_repo_list(item[1])
                        elif msg_type == "fetch_done":
                            self.is_running = False
                            self.update_button_states()
                        elif msg_type == "sync_done":
                            self.is_running = False
                            self.update_button_states()
                            self.mark_remaining_as_failed()
                            self.reset_progress_bar()
                        elif msg_type == "progress":
                            _, filename, downloaded, total = item
                            self.handle_progress(filename, downloaded, total)
            except queue.Empty:
                pass

            try:
                while True:
                    repo_name, status = self.status_queue.get_nowait()
                    self.update_repo_status(repo_name, status)
            except queue.Empty:
                pass

            self.root.after(100, self.update_ui)

        def mark_remaining_as_failed(self):
            for item in self.tree.get_children():
                cur_status = self.tree.item(item, "values")[0]
                if cur_status in ("等待", "处理中"):
                    self.tree.item(item, values=("失败",), tags=("fail",))

        def update_repo_status(self, repo_name, status):
            if repo_name in self.repo_items:
                item_id = self.repo_items[repo_name]
                self.tree.item(item_id, values=(status,))
                if status == "成功":
                    self.tree.item(item_id, tags=("success",))
                elif status in ("失败", "跳过"):
                    self.tree.item(item_id, tags=("fail",))
                elif status == "处理中":
                    self.tree.item(item_id, tags=("processing",))
                else:
                    self.tree.item(item_id, tags=())

    root = tk.Tk()
    app = GitHubClonerApp(root)
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main_gui()
    else:
        main_cli()