# -*- coding: utf-8 -*-
"""
标签打印助手 —— Windows 托盘版入口（后台运行 + 系统托盘图标）

设计说明
--------
* 不改动 webapp/main.py 的启动逻辑：本文件通过 ``from webapp.main import app``
  复用现有的 FastAPI 应用对象（路由 / 静态页 / SDK 全部一致），
  仅在内部用后台线程承载 uvicorn.Server。
* 无控制台窗口（配合 PyInstaller --noconsole 打包）。
* 托盘图标：左键单击打开打印页面；菜单含 打开页面 / 重启服务 / 开机自启 / 退出。

配置
----
配置文件位于 %APPDATA%\\LabelPrintAssistant\\config.json，字段：
    host               绑定地址，默认 0.0.0.0（允许局域网访问）
    port               服务端口，默认 4050
    auto_start         开机自启动（布尔）
    auto_open_browser  启动后自动打开浏览器（布尔）
    log_level          info / warning / error

用法
----
开发调试:  python win_tray/tray_app.py
打包构建:  见 win_tray/build.bat
"""

import ctypes
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------
# 路径 & 环境准备（与 webapp/main.py 保持一致：把项目根目录加入 sys.path）
# ---------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

APP_NAME = "LabelPrintAssistant"
APP_TITLE = "标签打印助手"
APP_DATA_DIR = os.path.join(os.environ.get("APPDATA", PROJECT_ROOT), APP_NAME)
CONFIG_PATH = os.path.join(APP_DATA_DIR, "config.json")
LOG_DIR = os.path.join(APP_DATA_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")

# 用于"已有实例"通知的本地端口（服务端口 + 1，仅供本机内部通信）
DEFAULT_PORT = 4050

# ---------------------------------------------------------------
# 日志
# ---------------------------------------------------------------
logger = logging.getLogger("tray")


def setup_logging(level: str = "info") -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # 让 uvicorn / fastapi 的日志也落到同一文件
    logging.getLogger("uvicorn").setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("uvicorn.error").propagate = True
    logging.getLogger("uvicorn.access").propagate = True


# ---------------------------------------------------------------
# 配置管理
# ---------------------------------------------------------------
DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": DEFAULT_PORT,
    "custom_port": 4051,       # 通用打印接口端口（0 表示关闭）
    "custom_token": "",        # 通用打印接口鉴权令牌（预留，空=不鉴权）
    "auto_start": False,
    "auto_open_browser": False,   # 启动后自动打开浏览器（默认关闭，避免打扰全屏场景）
    "log_level": "info",
}


# 配置版本：用于迁移行为默认值（v2 起启动后不再自动打开浏览器）
CONFIG_VERSION = 2


def load_config() -> dict:
    merged = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        merged.update(cfg)
    except (OSError, json.JSONDecodeError):
        pass

    # v1 -> v2 迁移：旧配置文件固化了 auto_open_browser=true（旧默认值），
    # 统一重置为 false，避免老用户升级后启动仍自动弹浏览器打扰全屏场景。
    if merged.get("config_version", 1) < CONFIG_VERSION:
        merged["auto_open_browser"] = False
        merged["config_version"] = CONFIG_VERSION
        save_config(merged)
    return merged


def save_config(cfg: dict) -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------
# 开机自启动（注册表 HKCU\...\Run）
# ---------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _reg_set(name: str, value: str | None) -> None:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if value is None:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def autostart_command() -> str:
    """开机自启使用的命令行：打包后为 exe 自身，开发模式为 pythonw + 本脚本。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def is_autostart_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    _reg_set(APP_NAME, autostart_command() if enabled else None)
    cfg = load_config()
    cfg["auto_start"] = enabled
    save_config(cfg)
    logger.info("开机自启动已%s", "开启" if enabled else "关闭")


# ---------------------------------------------------------------
# 单实例互斥（Windows 命名互斥量）
# ---------------------------------------------------------------
_kernel32 = ctypes.windll.kernel32
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance() -> bool:
    """获取全局互斥量；返回 False 表示已有实例在运行。"""
    handle = _kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}_Mutex")
    if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    # 持有句柄直到进程退出（不释放）
    return True


# ---------------------------------------------------------------
# 本地通知通道：第二个实例 -> 已有实例（触发打开浏览器）
# 注意：端口必须动态分配，避免与自定义打印端口（4051）等其他服务冲突。
# 安全：客户端必须发送服务端随机生成的口令（令牌）才触发弹窗，
#       防止本机任意进程 TCP 探测端口导致浏览器频繁弹出（方案A）。
# ---------------------------------------------------------------
NOTIFY_PORT_FILE = os.path.join(APP_DATA_DIR, "notify_port")
NOTIFY_TOKEN_FILE = os.path.join(APP_DATA_DIR, "notify_token")
NOTIFY_TOKEN_LEN = 32  # 口令字节长度（hex 字符数 = 64）


def _load_notify_state() -> tuple[int, str]:
    """读取端口与口令；任一缺失则返回 (0, '')。"""
    try:
        with open(NOTIFY_PORT_FILE, "r", encoding="utf-8") as f:
            port = int(f.read().strip())
        with open(NOTIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
            token = f.read().strip()
        return port, token
    except (OSError, ValueError):
        return 0, ""


def notify_existing_instance() -> None:
    """第二实例：向已有实例发送口令，请求其打开打印页面。"""
    port, token = _load_notify_state()
    if not port or not token:
        return
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as conn:
            conn.sendall(token.encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def _local_listener(stop_event: threading.Event) -> None:
    """监听本机动态端口；仅当客户端发送正确口令时触发打开浏览器。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", 0))  # 动态分配空闲端口
        srv.listen(4)
        srv.settimeout(0.5)
    except OSError:
        srv.close()
        logger.warning("本地通知通道不可用，跳过")
        return

    port = srv.getsockname()[1]
    token = secrets.token_hex(NOTIFY_TOKEN_LEN)
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(NOTIFY_PORT_FILE, "w", encoding="utf-8") as f:
            f.write(str(port))
        with open(NOTIFY_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(token)
        logger.info("本地通知通道端口: %s", port)
    except OSError:
        logger.warning("无法写入通知状态文件，通知通道不可用")
        srv.close()
        return

    while not stop_event.is_set():
        try:
            conn, _ = srv.accept()
            try:
                conn.settimeout(2.0)  # 等待客户端发送口令
                received = conn.recv(1024).decode("utf-8", "ignore").strip()
                if received == token:
                    logger.info("收到二次启动请求（口令校验通过），打开打印页面")
                    open_browser(source="二次唤醒")
                else:
                    # 未发口令或口令错误：可能是端口探测，记录但不弹窗
                    logger.warning("通知通道收到无效口令连接（len=%d），已忽略", len(received))
            except socket.timeout:
                logger.warning("通知通道连接超时未发送口令，已忽略")
            except OSError as e:
                logger.warning("通知通道处理连接异常: %s", e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        except socket.timeout:
            continue
        except OSError:
            break
    srv.close()


# ---------------------------------------------------------------
# uvicorn 服务（后台线程）
# ---------------------------------------------------------------
class UvicornThread:
    def __init__(self, app, host: str, port: int, name: str = "uvicorn-server"):
        self.app = app
        self.host = host
        self.port = port
        self.name = name
        self._server = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.started

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        import uvicorn

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=True,
            use_colors=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name=self.name, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        self._stop.set()

    def wait(self, timeout: float = 10.0) -> None:
        if self._thread:
            self._thread.join(timeout)


_servers: list[UvicornThread] = []


def start_servers() -> None:
    """启动主服务 + 通用打印服务（双端口）。"""
    global _servers
    cfg = load_config()
    host = str(cfg.get("host", "0.0.0.0"))

    # 主服务（网页 / 闲鱼系统），复用现有应用，不触碰 main.py 的 __main__ 逻辑
    from webapp.main import app

    main_server = UvicornThread(app, host, int(cfg.get("port", DEFAULT_PORT)), "uvicorn-main")
    main_server.start()
    logger.info("主服务启动中: http://%s:%s", main_server.host, main_server.port)

    # 通用打印接口（独立端口）
    servers = [main_server]
    custom_port = int(cfg.get("custom_port", 0))
    if custom_port:
        from webapp.custom_print_app import create_custom_app

        custom_app = create_custom_app(str(cfg.get("custom_token", "")))
        custom_server = UvicornThread(custom_app, host, custom_port, "uvicorn-custom")
        custom_server.start()
        servers.append(custom_server)
        logger.info("通用打印接口启动中: http://%s:%s", custom_server.host, custom_server.port)
    else:
        logger.info("通用打印接口未启用 (custom_port=0)")

    _servers = servers


def stop_servers() -> None:
    for s in _servers:
        s.stop()
    for s in _servers:
        s.wait()
    logger.info("服务已停止")


def restart_servers() -> None:
    logger.info("正在重启服务...")
    stop_servers()
    time.sleep(0.5)
    start_servers()
    notify("服务已重启", f"http://127.0.0.1:{load_config().get('port', DEFAULT_PORT)}")


# ---------------------------------------------------------------
# 托盘相关
# ---------------------------------------------------------------
_icon = None
_notify = None


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 解压目录与开发目录。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        p = os.path.join(base, rel)
        if os.path.exists(p):
            return p
    return os.path.join(PROJECT_ROOT, rel)


def open_browser(source: str = "") -> None:
    """打开打印页面。source 用于记录触发来源，便于排查。"""
    cfg = load_config()
    url = f"http://127.0.0.1:{cfg.get('port', DEFAULT_PORT)}/static/index.html"
    webbrowser.open(url)
    if source:
        logger.info("打开浏览器(%s): %s", source, url)
    else:
        logger.info("打开浏览器: %s", url)


def notify(message: str, title: str = APP_TITLE) -> None:
    try:
        if _icon is not None:
            _icon.notify(message, title)
    except Exception:  # noqa: BLE001
        pass


def quit_app(icon=None, item=None) -> None:
    logger.info("收到退出指令")
    if _local_stop is not None:
        _local_stop.set()
    stop_servers()
    if _icon is not None:
        _icon.stop()
    sys.exit(0)


def toggle_autostart(icon=None, item=None) -> None:
    set_autostart(not is_autostart_enabled())
    if is_autostart_enabled():
        notify("已开启开机自启动")
    else:
        notify("已关闭开机自启动")


def build_menu() -> "pystray.Menu":
    import pystray

    return pystray.Menu(
        pystray.MenuItem("打开打印页面", lambda i, it: open_browser(source="托盘菜单"), default=True),
        pystray.MenuItem("重启服务", lambda i, it: restart_servers()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "开机自启动",
            lambda i, it: toggle_autostart(),
            checked=lambda item: is_autostart_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda i, it: quit_app()),
    )


_local_stop: threading.Event | None = None


def main() -> None:
    global _icon, _local_stop, _notify

    # 1. 单实例检查
    if not acquire_single_instance():
        notify_existing_instance()
        ctypes.windll.user32.MessageBoxW(
            0,
            "标签打印助手已在后台运行。\n如需打开页面，请点击托盘图标。",
            APP_TITLE,
            0x40,
        )
        return

    # 2. 初始化
    cfg = load_config()
    setup_logging(cfg.get("log_level", "info"))
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    logger.info("=" * 50)
    logger.info("%s 启动 (frozen=%s)", APP_TITLE, getattr(sys, "frozen", False))
    logger.info("配置文件: %s", CONFIG_PATH)

    # 3. 同步注册表中的自启状态到配置
    if is_autostart_enabled() != bool(cfg.get("auto_start")):
        cfg["auto_start"] = is_autostart_enabled()
        save_config(cfg)

    # 4. 启动本地监听线程 + 服务线程（主服务 + 通用打印接口）
    _local_stop = threading.Event()
    threading.Thread(target=_local_listener, args=(_local_stop,), daemon=True).start()
    start_servers()

    # 5. 托盘图标
    import pystray
    from PIL import Image

    icon_path = resource_path(os.path.join("icon", "app.ico"))
    image = Image.open(icon_path) if os.path.exists(icon_path) else Image.new("RGBA", (64, 64), (239, 179, 54, 255))

    _icon = pystray.Icon(
        APP_NAME,
        image,
        APP_TITLE,
        menu=build_menu(),
    )

    # 6. 启动后自动打开浏览器
    if cfg.get("auto_open_browser", True):
        threading.Timer(1.2, lambda: open_browser(source="启动自动")).start()

    logger.info("托盘已就绪，服务端口: %s", cfg.get("port"))
    _icon.run()


if __name__ == "__main__":
    main()
