#!/usr/bin/env python3
"""
GitHub 仓库批量克隆/拉取工具（增强版）
- 命令行模式：python script.py <username> [--dir DIR] [--token TOKEN] [--color]
- GUI 模式：python script.py（不带参数启动图形界面）
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
from urllib.parse import urlparse

# -------------------- 颜色支持（仅命令行）--------------------
class Colors:
    """ANSI 颜色代码，仅在支持颜色的终端使用"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def supports_color():
    """检测终端是否支持颜色"""
    if not sys.stdout.isatty():
        return False
    if os.name == 'nt':  # Windows
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            return True
        except:
            return False
    return True

def color_text(text, color_code, use_color):
    if use_color:
        return f"{color_code}{text}{Colors.ENDC}"
    return text

# -------------------- 核心功能 --------------------
def get_user_repos(username, token=None):
    repos = []
    page = 1
    per_page = 100
    while True:
        url = f"https://api.github.com/users/{username}/repos?page={page}&per_page={per_page}"
        headers = {}
        if token:
            headers["Authorization"] = f"token {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                if not data:
                    break
                for repo in data:
                    repos.append({
                        "name": repo["name"],
                        "clone_url": repo["clone_url"]
                    })
                link_header = response.headers.get("Link")
                if link_header and 'rel="next"' in link_header:
                    page += 1
                else:
                    break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Exception(f"用户 {username} 不存在或没有公共仓库。")
            elif e.code == 403 and "rate limit" in str(e):
                raise Exception("API 速率限制已用尽。请稍后再试，或使用个人访问令牌提高限制。")
            else:
                raise Exception(f"API 请求失败: {e}")
        except Exception as e:
            raise Exception(f"发生错误: {e}")
    return repos

def run_git_command(cmd, cwd=None, output_callback=None):
    """执行 Git 命令，隐藏子进程窗口（Windows）"""
    try:
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW  # 0x08000000
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags
        )
        output_lines = []
        for line in process.stdout:
            line = line.rstrip()
            output_lines.append(line)
            if output_callback:
                output_callback(line)
        process.wait()
        if process.returncode != 0:
            return False, "\n".join(output_lines)
        return True, "\n".join(output_lines)
    except Exception as e:
        return False, str(e)

def clone_or_pull(repo_info, base_dir, status_callback=None, output_callback=None):
    repo_name = repo_info["name"]
    repo_url = repo_info["clone_url"]
    local_path = os.path.normpath(os.path.join(base_dir, repo_name))

    if status_callback:
        status_callback(repo_name, "处理中")

    if not os.path.exists(local_path):
        if output_callback:
            output_callback(f"克隆 {repo_url} 到 {local_path}")
        success, output = run_git_command(["git", "clone", repo_url, local_path],
                                          output_callback=output_callback)
        if success:
            if status_callback:
                status_callback(repo_name, "成功")
        else:
            if status_callback:
                status_callback(repo_name, "失败")
        return success
    else:
        if not os.path.isdir(os.path.join(local_path, ".git")):
            if output_callback:
                output_callback(f"跳过: {local_path} 不是一个 Git 仓库")
            if status_callback:
                status_callback(repo_name, "跳过")
            return False
        if output_callback:
            output_callback(f"拉取 {local_path}")
        success, output = run_git_command(["git", "pull"], cwd=local_path,
                                          output_callback=output_callback)
        if success:
            if status_callback:
                status_callback(repo_name, "成功")
        else:
            if status_callback:
                status_callback(repo_name, "失败")
        return success

def process_repos(username, base_dir, token=None,
                  status_callback=None, output_callback=None):
    try:
        if output_callback:
            output_callback(f"正在获取用户 {username} 的仓库列表...")
        repos = get_user_repos(username, token)
    except Exception as e:
        if output_callback:
            output_callback(f"错误: {e}")
        return False

    if not repos:
        if output_callback:
            output_callback("没有找到任何仓库。")
        return True

    if output_callback:
        output_callback(f"共找到 {len(repos)} 个仓库，开始处理...")

    success_count = 0
    fail_count = 0
    for repo in repos:
        ok = clone_or_pull(repo, base_dir,
                           status_callback=status_callback,
                           output_callback=output_callback)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    if output_callback:
        output_callback(f"\n处理完成: {success_count} 成功, {fail_count} 失败")
    return fail_count == 0

# -------------------- 命令行模式 --------------------
def main_cli():
    parser = argparse.ArgumentParser(
        description="批量克隆或拉取指定 GitHub 用户的所有仓库。"
    )
    parser.add_argument("username", help="GitHub 用户名")
    parser.add_argument("-d", "--dir", default=".",
                        help="本地存放仓库的根目录（默认当前目录）")
    parser.add_argument("-t", "--token", help="GitHub 个人访问令牌")
    parser.add_argument("--color", action="store_true",
                        help="启用彩色输出（默认自动检测）")
    args = parser.parse_args()

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

    process_repos(args.username, base_dir, args.token,
                  output_callback=colored_output)

# -------------------- GUI 模式 --------------------
def main_gui():
    # 隐藏控制台窗口（仅 Windows 且无命令行参数时）
    if sys.platform == 'win32' and len(sys.argv) == 1:
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except:
            pass

    import tkinter as tk
    from tkinter import scrolledtext, filedialog, messagebox
    from tkinter import ttk

    class GitHubClonerApp:
        def __init__(self, root):
            self.root = root
            self.root.title("GitHub 仓库批量克隆/拉取工具")
            self.root.geometry("800x650")  # 增高以容纳配置区域

            # 变量
            self.username_var = tk.StringVar()
            self.dir_var = tk.StringVar(value=os.getcwd())
            self.token_var = tk.StringVar()
            # 配置复选框变量
            self.safe_dir_var = tk.BooleanVar(value=False)
            self.ssl_verify_var = tk.BooleanVar(value=True)

            self.repo_status = {}
            self.repo_items = {}

            # 创建界面
            self.create_widgets()

            # 初始化配置状态
            self.update_config_status()

            # 用于线程间通信的队列
            self.output_queue = queue.Queue()
            self.status_queue = queue.Queue()
            self.update_ui()

        def create_widgets(self):
            # 输入区域
            input_frame = ttk.LabelFrame(self.root, text="设置", padding=5)
            input_frame.pack(fill="x", padx=5, pady=5)

            ttk.Label(input_frame, text="GitHub 用户名:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.username_var, width=40).grid(row=0, column=1, padx=5, pady=5, sticky="we")

            ttk.Label(input_frame, text="本地目录:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.dir_var, width=40).grid(row=1, column=1, padx=5, pady=5, sticky="we")
            ttk.Button(input_frame, text="浏览...", command=self.browse_dir).grid(row=1, column=2, padx=5, pady=5)

            ttk.Label(input_frame, text="Token (可选):").grid(row=2, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(input_frame, textvariable=self.token_var, width=40, show="*").grid(row=2, column=1, padx=5, pady=5, sticky="we")

            # 执行按钮
            self.run_button = ttk.Button(input_frame, text="开始同步", command=self.start_sync)
            self.run_button.grid(row=3, column=1, pady=10)

            # 配置区域（新增）
            config_frame = ttk.LabelFrame(self.root, text="Git 全局配置", padding=5)
            config_frame.pack(fill="x", padx=5, pady=5)

            self.safe_dir_cb = ttk.Checkbutton(
                config_frame,
                text="添加安全目录通配符 (safe.directory = '*')",
                variable=self.safe_dir_var,
                command=self.on_safe_directory_toggle
            )
            self.safe_dir_cb.grid(row=0, column=0, sticky="w", padx=5, pady=2)

            self.ssl_verify_cb = ttk.Checkbutton(
                config_frame,
                text="启用 SSL 验证 (http.sslVerify)",
                variable=self.ssl_verify_var,
                command=self.on_ssl_verify_toggle
            )
            self.ssl_verify_cb.grid(row=1, column=0, sticky="w", padx=5, pady=2)

            # 主内容区域：左侧仓库列表，右侧日志
            main_panel = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
            main_panel.pack(fill="both", expand=True, padx=5, pady=5)

            # 左侧列表
            list_frame = ttk.LabelFrame(main_panel, text="仓库状态")
            main_panel.add(list_frame, weight=1)

            columns = ("status",)
            self.tree = ttk.Treeview(list_frame, columns=columns, show="tree headings", height=15)
            self.tree.heading("#0", text="仓库名称")
            self.tree.heading("status", text="状态")
            self.tree.column("#0", width=200)
            self.tree.column("status", width=100, anchor="center")

            tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=tree_scroll.set)
            tree_scroll.pack(side="right", fill="y")
            self.tree.pack(side="left", fill="both", expand=True)

            # 右侧日志
            log_frame = ttk.LabelFrame(main_panel, text="详细日志")
            main_panel.add(log_frame, weight=2)

            self.output_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
            self.output_text.pack(fill="both", expand=True)

        def browse_dir(self):
            directory = filedialog.askdirectory(initialdir=self.dir_var.get())
            if directory:
                self.dir_var.set(directory)

        # ---------- 配置相关方法 ----------
        def update_config_status(self):
            """从 git 全局配置读取当前状态，更新复选框"""
            # 检查 safe.directory 是否包含 '*'
            try:
                result = subprocess.run(
                    ["git", "config", "--global", "--get-all", "safe.directory"],
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode == 0:
                    values = result.stdout.strip().split('\n')
                    has_star = '*' in values
                else:
                    has_star = False
                self.safe_dir_var.set(has_star)
            except Exception as e:
                print(f"获取 safe.directory 失败: {e}")
                self.safe_dir_var.set(False)

            # 检查 http.sslVerify
            try:
                result = subprocess.run(
                    ["git", "config", "--global", "--get", "http.sslVerify"],
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode == 0:
                    value = result.stdout.strip().lower()
                    ssl_enabled = (value == "true")
                else:
                    ssl_enabled = True  # 默认启用
                self.ssl_verify_var.set(ssl_enabled)
            except Exception as e:
                print(f"获取 http.sslVerify 失败: {e}")
                self.ssl_verify_var.set(True)

        def set_controls_state(self, state):
            """统一设置交互控件的状态（normal/disabled）"""
            self.run_button.config(state=state)
            self.safe_dir_cb.config(state=state)
            self.ssl_verify_cb.config(state=state)

        def on_safe_directory_toggle(self):
            """处理安全目录复选框点击"""
            target = self.safe_dir_var.get()  # True=添加，False=移除
            self.set_controls_state("disabled")
            old_state = not target
            try:
                if target:
                    cmd = ["git", "config", "--global", "--add", "safe.directory", "*"]
                else:
                    cmd = ["git", "config", "--global", "--unset-all", "safe.directory"]
                result = subprocess.run(
                    cmd,
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode != 0:
                    self.safe_dir_var.set(old_state)
                    messagebox.showerror("错误", f"执行 Git 命令失败:\n{result.stderr}")
                else:
                    self.update_config_status()
            except Exception as e:
                self.safe_dir_var.set(old_state)
                messagebox.showerror("错误", f"发生异常:\n{e}")
            finally:
                self.set_controls_state("normal")

        def on_ssl_verify_toggle(self):
            """处理 SSL 验证复选框点击"""
            target = self.ssl_verify_var.get()  # True=启用，False=禁用
            self.set_controls_state("disabled")
            old_state = not target
            try:
                value = "true" if target else "false"
                cmd = ["git", "config", "--global", "http.sslVerify", value]
                result = subprocess.run(
                    cmd,
                    capture_output=True, text=True, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                )
                if result.returncode != 0:
                    self.ssl_verify_var.set(old_state)
                    messagebox.showerror("错误", f"执行 Git 命令失败:\n{result.stderr}")
                else:
                    self.update_config_status()
            except Exception as e:
                self.ssl_verify_var.set(old_state)
                messagebox.showerror("错误", f"发生异常:\n{e}")
            finally:
                self.set_controls_state("normal")

        # ---------- 同步功能 ----------
        def start_sync(self):
            username = self.username_var.get().strip()
            base_dir = self.dir_var.get().strip()
            token = self.token_var.get().strip() or None

            if not username:
                messagebox.showerror("错误", "请输入 GitHub 用户名")
                return
            if not base_dir:
                messagebox.showerror("错误", "请选择本地目录")
                return
            if not os.path.exists(base_dir):
                try:
                    os.makedirs(base_dir)
                except Exception as e:
                    messagebox.showerror("错误", f"无法创建目录: {e}")
                    return

            # 清空界面
            self.output_text.delete(1.0, tk.END)
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.repo_items.clear()
            self.repo_status.clear()

            # 禁用控件
            self.set_controls_state("disabled")

            # 启动线程
            thread = threading.Thread(target=self.sync_thread, args=(username, base_dir, token))
            thread.daemon = True
            thread.start()

        def sync_thread(self, username, base_dir, token):
            def status_callback(repo_name, status):
                self.status_queue.put((repo_name, status))
            def output_callback(msg):
                self.output_queue.put(("log", msg))

            process_repos(username, base_dir, token,
                          status_callback=status_callback,
                          output_callback=output_callback)

            self.output_queue.put(("done", None))

        def update_ui(self):
            """定期从队列获取数据更新界面"""
            try:
                while True:
                    item = self.output_queue.get_nowait()
                    if isinstance(item, tuple) and item[0] == "done":
                        # 同步完成，重新获取配置状态并启用控件
                        self.update_config_status()
                        self.set_controls_state("normal")
                        break
                    elif isinstance(item, tuple) and item[0] == "log":
                        msg = item[1]
                        self.output_text.insert(tk.END, msg + "\n")
                        self.output_text.see(tk.END)
                    else:
                        self.output_text.insert(tk.END, item + "\n")
                        self.output_text.see(tk.END)
            except queue.Empty:
                pass

            try:
                while True:
                    repo_name, status = self.status_queue.get_nowait()
                    self.update_repo_status(repo_name, status)
            except queue.Empty:
                pass

            self.root.after(100, self.update_ui)

        def update_repo_status(self, repo_name, status):
            if repo_name not in self.repo_items:
                item_id = self.tree.insert("", "end", text=repo_name, values=(status,))
                self.repo_items[repo_name] = item_id
            else:
                item_id = self.repo_items[repo_name]
                self.tree.item(item_id, values=(status,))

            if status == "成功":
                self.tree.tag_configure("success", foreground="green")
                self.tree.item(item_id, tags=("success",))
            elif status in ("失败", "跳过"):
                self.tree.tag_configure("fail", foreground="red")
                self.tree.item(item_id, tags=("fail",))
            elif status == "处理中":
                self.tree.tag_configure("processing", foreground="blue")
                self.tree.item(item_id, tags=("processing",))

    root = tk.Tk()
    app = GitHubClonerApp(root)
    root.mainloop()

# -------------------- 入口 --------------------
if __name__ == "__main__":
    if len(sys.argv) == 1:
        main_gui()
    else:
        main_cli()
