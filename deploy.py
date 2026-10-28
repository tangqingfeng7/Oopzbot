#!/usr/bin/env python3
"""一键部署并启动 Oopz Bot，Linux / macOS / Windows 通用。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"
MIN_PYTHON = (3, 10)
NETEASE_REPO = "https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git"
NETEASE_DOCKER_IMAGE = "moefurina/ncm-api:latest"
NETEASE_DEFAULT_DIR = "NeteaseCloudMusicApi"
REDIS_HOST, REDIS_PORT = "127.0.0.1", 6379
SCREEN_SHARE_CLIENT_DIR = ROOT / "src" / "screen_share" / "client"
SCREEN_SHARE_ASSET_DIR = ROOT / "src" / "web" / "assets" / "screen-share"
SCREEN_SHARE_REQUIRED_ASSETS = ("index.html", "style.css", "app.js")

_STEP = 0


def say(message: str) -> None:
    print(f"  {message}", flush=True)


def step(title: str) -> None:
    global _STEP
    _STEP += 1
    print(f"\n[{_STEP}] {title}", flush=True)


def warn(message: str) -> None:
    print(f"  ! {message}", flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=kwargs.pop("cwd", ROOT), **kwargs)


def run_ok(cmd: list[str], **kwargs) -> bool:
    """跑一条命令，只关心成没成。输出直接透传给用户，装依赖时能看到进度。"""
    try:
        return run(cmd, **kwargs).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def quiet_ok(cmd: list[str]) -> bool:
    return run_ok(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------
# 虚拟环境与 Python 依赖
# --------------------------------------------------------------------------


def load_env_files() -> None:
    """读取 .env / .env.local。

    已经设好的环境变量优先，文件只补空缺——命令行上临时指定的值不该被文件盖掉。
    """
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        loaded = 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
        say(f"已读取 {name}（{loaded} 项）")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        need = ".".join(str(x) for x in MIN_PYTHON)
        have = platform.python_version()
        sys.exit(f"需要 Python {need} 或更高版本，当前是 {have}")


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists():
        say(f"虚拟环境已存在：{VENV_DIR}")
        return python
    say(f"创建虚拟环境：{VENV_DIR}")
    try:
        venv.EnvBuilder(with_pip=True, upgrade_deps=False).create(VENV_DIR)
    except Exception as exc:
        # 最常见的原因是这个 Python 没带 ensurepip：Debian/Ubuntu 把它拆成了
        # 单独的包，某些第三方发行版（如 uv 装的解释器）也可能缺。
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        sys.exit(venv_failure_hint(exc))
    if not python.exists():
        sys.exit(f"虚拟环境创建失败，找不到 {python}")
    return python


def venv_failure_hint(exc: Exception) -> str:
    lines = [
        f"创建虚拟环境失败：{exc}",
        "",
        f"当前用的解释器是 {sys.executable}，它可能缺少 venv/ensurepip 组件。",
    ]
    if IS_WINDOWS:
        lines += [
            "建议从 python.org 或微软商店重装 Python，安装时勾选完整组件。",
        ]
    else:
        lines += [
            "常见修法：",
            "  Ubuntu/Debian : sudo apt install python3-venv",
            "  Fedora        : sudo dnf install python3-devel",
            "或者换一个自带 venv 的解释器：PYTHON_BIN=/usr/bin/python3 ./deploy.sh",
        ]
    return "\n".join(lines)


def install_requirements(python: Path) -> None:
    say("安装 Python 依赖（首次会比较久）")
    run_ok([str(python), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    if not run_ok([str(python), "-m", "pip", "install", "-r", "requirements.txt"]):
        sys.exit("Python 依赖安装失败，请看上面的报错。网络问题可以先配好代理再重试。")
    say("Python 依赖就绪")


def install_browser(python: Path) -> None:
    """装 Playwright Chromium，语音推流要用。装不上不致命，只是没有语音。"""
    if browser_ready(python):
        say("浏览器已就绪")
        return
    # --with-deps 需要管理员权限装系统库，非 root 时退回不带依赖的安装
    cmd = [str(python), "-m", "playwright", "install", "chromium"]
    if not IS_WINDOWS and os.geteuid() == 0:
        cmd.insert(4, "--with-deps")
    if run_ok(cmd):
        say("浏览器就绪")
    else:
        warn("浏览器安装失败，语音功能将不可用（其余功能不受影响）")
        if not IS_WINDOWS:
            warn(f"可手动重试：sudo {python} -m playwright install --with-deps chromium")


# --------------------------------------------------------------------------
# 屏幕共享网页资源
# --------------------------------------------------------------------------


def screen_share_assets_ready() -> bool:
    """正式部署只依赖仓库内已提交的编译产物，不要求 Node.js。"""
    return all(
        (SCREEN_SHARE_ASSET_DIR / name).is_file()
        and (SCREEN_SHARE_ASSET_DIR / name).stat().st_size > 0
        for name in SCREEN_SHARE_REQUIRED_ASSETS
    )


def setup_screen_share_assets(install: bool) -> None:
    """校验屏幕共享页；仅当发行包缺产物时才尝试用本机 Node 恢复构建。"""
    if screen_share_assets_ready():
        say("屏幕共享网页资源已就绪（无需 Node.js）")
        return
    missing = [
        name
        for name in SCREEN_SHARE_REQUIRED_ASSETS
        if not (SCREEN_SHARE_ASSET_DIR / name).is_file()
        or (SCREEN_SHARE_ASSET_DIR / name).stat().st_size <= 0
    ]
    warn(f"屏幕共享网页资源不完整：{'、'.join(missing)}")
    if not install:
        warn("已跳过安装，屏幕共享暂不可用")
        return
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    if not SCREEN_SHARE_CLIENT_DIR.is_dir() or not shutil.which(npm):
        warn("发行包应自带编译产物；当前又找不到 npm，无法自动恢复")
        return
    say("尝试从模块内 TypeScript 源码恢复屏幕共享网页")
    commands = (
        [npm, "ci"],
        [npm, "run", "typecheck"],
        [npm, "run", "build"],
    )
    if (
        all(run_ok(command, cwd=SCREEN_SHARE_CLIENT_DIR) for command in commands)
        and screen_share_assets_ready()
    ):
        say("屏幕共享网页资源已恢复")
        return
    warn("屏幕共享网页构建失败，Bot 其他功能仍可继续部署")


# --------------------------------------------------------------------------
# 配置文件
# --------------------------------------------------------------------------


def ensure_dirs() -> None:
    for name in ("data", "logs"):
        (ROOT / name).mkdir(exist_ok=True)
    say("data/ 与 logs/ 就绪")


def ensure_config_files() -> list[str]:
    """从模板生成缺失的配置文件，返回本次新建的文件名。"""
    created = []
    for target, template in (
        ("config.py", "config.example.py"),
        ("private_key.py", "private_key.example.py"),
    ):
        if not (ROOT / target).exists() and (ROOT / template).exists():
            shutil.copy(ROOT / template, ROOT / target)
            created.append(target)
    for example in (ROOT / "config" / "plugins").glob("*/example.json"):
        target = example.parent / "config.json"
        if not target.exists():
            shutil.copy(example, target)
    if created:
        say(f"已从模板生成：{'、'.join(created)}")
    else:
        say("配置文件已存在，保持原样")
    return created


def config_value(key: str, default: str = "") -> str:
    """从 config.py 里读一个字符串字段。读不到就用默认值。

    直接文本匹配而不是 import config：此时依赖可能还没装，import 会失败。
    """
    path = ROOT / "config.py"
    if not path.exists():
        return default
    match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', path.read_text(encoding="utf-8"))
    return match.group(1) if match else default


def netease_dir() -> Path:
    """网易云 API 的目录以 config.py 里的 auto_start_path 为准。

    模板默认叫 NeteaseCloudMusicApi，但用户可能改成别的名字，
    写死目录名会把「已经装好」误报成「没装」。
    """
    configured = config_value("auto_start_path", NETEASE_DEFAULT_DIR).strip()
    if not configured:
        return ROOT / NETEASE_DEFAULT_DIR
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def browser_ready(python: Path) -> bool:
    """问 Playwright 要 Chromium 的真实路径，比标记文件靠谱。

    标记文件只能反映「本脚本装过」，手动装的或换了环境都会误判成没装。
    """
    if not python.exists():
        return False
    probe = (
        "import sys;"
        "from pathlib import Path;"
        "from playwright.sync_api import sync_playwright;"
        "p=sync_playwright().start();"
        "sys.exit(0 if Path(p.chromium.executable_path).exists() else 1)"
    )
    return quiet_ok([str(python), "-c", probe])


def read_credentials() -> dict[str, str]:
    """读出 config.py 里与登录有关的字段，判断能不能连上平台。"""
    content = (ROOT / "config.py").read_text(encoding="utf-8")
    values = {}
    for key in ("login_phone", "login_password", "device_id", "person_uid", "jwt_token"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', content)
        values[key] = match.group(1) if match else ""
    return values


def has_usable_credentials(values: dict[str, str]) -> bool:
    if values["login_phone"] and values["login_password"]:
        return True
    return bool(values["device_id"] and values["person_uid"] and values["jwt_token"])


def write_login(phone: str, password: str) -> None:
    """把账号密码写进 config.py，复用凭据模块的替换逻辑，避免自己解析 Python 源码。"""
    sys.path.insert(0, str(ROOT / "src"))
    from oopz.credentials import _replace_config_value

    path = ROOT / "config.py"
    content = path.read_text(encoding="utf-8")
    content, ok_phone = _replace_config_value(content, "login_phone", phone)
    content, ok_password = _replace_config_value(content, "login_password", password)
    if not (ok_phone and ok_password):
        raise RuntimeError("没能在 config.py 里找到 login_phone / login_password 字段")
    path.write_text(content, encoding="utf-8")


def _section_span(content: str, section: str) -> tuple[int, int] | None:
    """定位某个顶层配置块的范围，例如 NETEASE_CLOUD = { ... }。

    api_key / cookie 这类键名在好几个块里都有，不限定范围就会写错地方——
    比如把一个配置块的同名字段写进另一个配置块。
    """
    match = re.search(rf"^{re.escape(section)}\s*=\s*\{{", content, re.MULTILINE)
    if not match:
        return None
    end = content.find("\n}", match.end())
    if end == -1:
        return None
    return match.end(), end


def set_config_field(content: str, section: str, key: str, value: str | bool) -> tuple[str, bool]:
    """只在指定配置块内替换字段值。返回新内容和是否改动过。"""
    span = _section_span(content, section)
    if span is None:
        return content, False
    start, end = span
    block = content[start:end]
    if isinstance(value, bool):
        pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*)(?:True|False)')
        replacement = f"\\g<1>{'True' if value else 'False'}"
    else:
        pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*)"[^"]*"')
        replacement = f"\\g<1>{json.dumps(value, ensure_ascii=False)}"
    new_block, count = pattern.subn(replacement, block, count=1)
    if not count:
        return content, False
    return content[:start] + new_block + content[end:], True


def config_section_string(section: str, key: str, default: str = "") -> str:
    """只读取指定顶层配置块的字符串字段，避免命中其他块的同名键。"""
    path = ROOT / "config.py"
    if not path.exists():
        return default
    content = path.read_text(encoding="utf-8")
    span = _section_span(content, section)
    if span is None:
        return default
    block = content[span[0] : span[1]]
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', block)
    return match.group(1) if match else default


def config_section_flag(section: str, key: str, default: bool = False) -> bool:
    """只读取指定配置块的 Python 布尔字面量。"""
    path = ROOT / "config.py"
    if not path.exists():
        return default
    content = path.read_text(encoding="utf-8")
    span = _section_span(content, section)
    if span is None:
        return default
    block = content[span[0] : span[1]]
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(True|False)', block)
    return match.group(1) == "True" if match else default


def valid_agora_credential(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", str(value or "").strip()))


def valid_screen_share_url(value: str) -> bool:
    """公网必须 HTTPS；只保留浏览器允许的本机 HTTP 调试例外。"""
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    return bool(
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def set_admin_uids(content: str, uids: list[str]) -> tuple[str, bool]:
    """改写顶层的 ADMIN_UIDS 列表。"""
    match = re.search(r"^ADMIN_UIDS\s*=\s*\[[^\]]*\]", content, re.MULTILINE)
    if not match:
        return content, False
    body = "".join(f'\n    "{uid}",' for uid in uids)
    return content[: match.start()] + f"ADMIN_UIDS = [{body}\n]" + content[match.end() :], True


def ask(prompt: str, *, secret_hint: str = "") -> str:
    """问一个可跳过的问题。回车即跳过。"""
    suffix = f"（{secret_hint}）" if secret_hint else ""
    try:
        return input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def ask_secret(prompt: str, *, secret_hint: str = "") -> str:
    """读取敏感项时不回显，防止 Certificate 出现在终端历史或录屏中。"""
    suffix = f"（{secret_hint}）" if secret_hint else ""
    try:
        return getpass.getpass(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def configure_screen_share(content: str) -> tuple[str, bool]:
    """首次部署的可选声网向导；任一项无效时不写入半套配置。"""
    app_id = ask("声网 App ID", secret_hint="32 位十六进制；留空不启用屏幕共享")
    if not app_id:
        return content, False
    certificate = ask_secret(
        "声网 App Certificate",
        secret_hint="32 位十六进制，输入不回显",
    )
    public_url = ask(
        "Bot 对外 HTTPS 地址",
        secret_hint="如 https://bot.example.com",
    ).rstrip("/")
    errors: list[str] = []
    if not valid_agora_credential(app_id):
        errors.append("App ID 必须是 32 位十六进制字符")
    if not valid_agora_credential(certificate):
        errors.append("App Certificate 必须是 32 位十六进制字符")
    if not valid_screen_share_url(public_url):
        errors.append("公网地址必须使用 HTTPS（只有 localhost 可使用 HTTP）")
    if errors:
        for error in errors:
            warn(error)
        warn("未启用屏幕共享，避免写入不完整配置")
        return content, False

    staged = content
    updates: tuple[tuple[str, str, str | bool], ...] = (
        ("SCREEN_SHARE_CONFIG", "enabled", True),
        ("SCREEN_SHARE_CONFIG", "agora_app_id", app_id.lower()),
        ("SCREEN_SHARE_CONFIG", "agora_app_certificate", certificate.lower()),
        ("WEB_PLAYER_CONFIG", "url", public_url),
        ("WEB_PLAYER_CONFIG", "cookie_secure", public_url.startswith("https://")),
        ("WEB_PLAYER_CONFIG", "admin_cookie_secure", public_url.startswith("https://")),
    )
    for section, key, value in updates:
        staged, ok = set_config_field(staged, section, key, value)
        if not ok:
            warn(f"配置模板缺少 {section}.{key}，未启用屏幕共享")
            return content, False
    return staged, True


def prompt_optional_settings() -> None:
    """把常用的可选配置过一遍，全都可以直接回车跳过。"""
    path = ROOT / "config.py"
    content = path.read_text(encoding="utf-8")
    changed: list[str] = []

    print()
    print("  下面几项都是可选的，直接回车跳过，之后也能在 config.py 里改。")

    admin_password = ask("后台管理密码", secret_hint="设了才能打开 /admin 管理页")
    if admin_password:
        content, ok = set_config_field(content, "WEB_PLAYER_CONFIG", "admin_password", admin_password)
        if ok:
            content, _ = set_config_field(content, "WEB_PLAYER_CONFIG", "admin_enabled", True)
            changed.append("后台管理")

    content, screen_share_enabled = configure_screen_share(content)
    if screen_share_enabled:
        changed.append("网页屏幕共享")

    netease_cookie = ask("网易云 Cookie", secret_hint="填了才能听 VIP 音质，可留空")
    if netease_cookie:
        content, ok = set_config_field(content, "NETEASE_CLOUD", "cookie", netease_cookie)
        if ok:
            changed.append("网易云账号")

    proxy = ask("代理地址", secret_hint="如 http://127.0.0.1:7890，不用代理就留空")
    if proxy:
        content, ok = set_config_field(content, "OOPZ_CONFIG", "proxy", proxy)
        if ok:
            changed.append("代理")

    admin_uid = ask("你的 Oopz 用户 UID", secret_hint="设了之后只有你能用管理命令")
    if admin_uid:
        content, ok = set_admin_uids(content, [u.strip() for u in admin_uid.split(",") if u.strip()])
        if ok:
            changed.append("管理员名单")

    if not changed:
        say("可选配置全部跳过，保持默认")
        return
    path.write_text(content, encoding="utf-8")
    say(f"已写入：{'、'.join(changed)}")


def prompt_credentials() -> bool:
    """问一次账号密码。返回是否写入成功。"""
    print()
    print("  Bot 需要一个 Oopz 账号才能登录。密码只会写进本机的 config.py，不上传。")
    print("  直接回车可跳过，之后手动编辑 config.py 也行。")
    try:
        phone = input("  Oopz 手机号/账号: ").strip()
        if not phone:
            return False
        password = input("  Oopz 密码: ").strip()
        if not password:
            return False
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    try:
        write_login(phone, password)
    except Exception as exc:
        warn(f"写入配置失败：{exc}")
        return False
    say("账号密码已写入 config.py")
    return True


# --------------------------------------------------------------------------
# Redis
# --------------------------------------------------------------------------


def redis_alive() -> bool:
    try:
        with socket.create_connection((REDIS_HOST, REDIS_PORT), timeout=1.5):
            return True
    except OSError:
        return False


def linux_package_manager() -> tuple[str, list[str]] | None:
    for manager, install in (
        ("apt-get", ["apt-get", "install", "-y", "redis-server"]),
        ("dnf", ["dnf", "install", "-y", "redis"]),
        ("pacman", ["pacman", "-S", "--noconfirm", "redis"]),
        ("zypper", ["zypper", "install", "-y", "redis"]),
    ):
        if shutil.which(manager):
            return manager, install
    return None


def try_install_redis() -> bool:
    """尽力装上并拉起 Redis。装不上返回 False，交给调用方降级。"""
    if IS_WINDOWS:
        # Redis 官方不支持 Windows。有 Docker 就用容器顶上，这是最省事的路子。
        if shutil.which("docker"):
            say("用 Docker 启动 Redis 容器")
            quiet_ok(["docker", "rm", "-f", "oopzbot-redis"])
            if quiet_ok([
                "docker", "run", "-d", "--name", "oopzbot-redis",
                "-p", f"{REDIS_PORT}:6379", "redis:7-alpine",
            ]):
                return wait_for_redis()
        warn("Windows 没有官方 Redis。可选：装 Docker Desktop、用 WSL，或用 Memurai。")
        return False

    if shutil.which("brew"):
        say("用 Homebrew 安装 Redis")
        if run_ok(["brew", "install", "redis"]):
            run_ok(["brew", "services", "start", "redis"])
            if wait_for_redis():
                return True

    found = linux_package_manager()
    if found is None:
        if shutil.which("docker"):
            say("没有识别到包管理器，改用 Docker 启动 Redis")
            quiet_ok(["docker", "rm", "-f", "oopzbot-redis"])
            if quiet_ok([
                "docker", "run", "-d", "--name", "oopzbot-redis",
                "-p", f"{REDIS_PORT}:6379", "redis:7-alpine",
            ]):
                return wait_for_redis()
        return False

    manager, install_cmd = found
    if os.geteuid() != 0:
        if not shutil.which("sudo"):
            warn(f"需要管理员权限安装 Redis，请手动执行：sudo {' '.join(install_cmd)}")
            return False
        install_cmd = ["sudo", *install_cmd]
        if manager == "apt-get":
            quiet_ok(["sudo", "apt-get", "update"])
    elif manager == "apt-get":
        quiet_ok(["apt-get", "update"])

    say(f"用 {manager} 安装 Redis（可能需要输入密码）")
    if not run_ok(install_cmd):
        return False

    for service in ("redis-server", "redis"):
        if quiet_ok(["sudo", "systemctl", "start", service] if os.geteuid() else
                    ["systemctl", "start", service]):
            break
    return wait_for_redis()


def wait_for_redis(timeout: float = 15.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if redis_alive():
            return True
        time.sleep(0.5)
    return False


def setup_redis(install: bool) -> None:
    if redis_alive():
        say(f"Redis 已在 {REDIS_HOST}:{REDIS_PORT} 运行")
        return
    if not install:
        warn("Redis 未运行，将使用内存队列（重启后队列丢失）")
        warn("屏幕共享依赖真实 Redis，当前将拒绝创建共享")
        return
    say("Redis 未运行，尝试安装")
    if try_install_redis():
        say("Redis 就绪")
    else:
        warn("Redis 装不上，Bot 会退到内存队列，重启后队列丢失")
        warn("屏幕共享将不可用；其他不依赖 Redis 持久权限状态的功能仍可继续")


# --------------------------------------------------------------------------
# 网易云 API（点歌用）
# --------------------------------------------------------------------------


def setup_netease(install: bool) -> None:
    target = netease_dir()
    if (target / "app.js").exists():
        say(f"网易云 API 已就绪：{target.name}/")
        return
    if not install:
        warn("没有网易云 API，点歌功能不可用")
        return
    if shutil.which("git") and (shutil.which("npm") or shutil.which("npm.cmd")):
        if install_netease_from_source(target):
            say("网易云 API 就绪，Bot 启动时会自动拉起")
            return
        warn("网易云 API 安装失败")
    else:
        warn("缺少 git 或 Node.js / npm")

    if start_netease_container():
        say("已用 Docker 启动网易云 API 容器")
        return
    warn("网易云 API 的源码安装和 Docker 兜底都失败，点歌功能暂不可用")
    warn("请根据上方 Git、npm 或 Docker 的错误处理后重跑本脚本")


def install_netease_from_source(target: Path) -> bool:
    """拉取维护中的 fork 并装依赖。目录里有 app.js 时 Bot 才会自动拉起它。"""
    say(f"拉取网易云 API 源码到 {target.name}/")
    if target.exists() and any(target.iterdir()):
        warn(f"{target.name}/ 已存在但缺少 app.js，先手动清理再重跑")
        return False
    if not run_ok(["git", "clone", "--depth", "1", NETEASE_REPO, str(target)]):
        return False
    if not (target / "app.js").exists():
        warn("拉下来的源码里没有 app.js，可能上游结构变了")
        return False
    say("安装网易云 API 依赖")
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    # 上游的 prepare 脚本会调用只放在 devDependencies 里的 husky。
    # 生产安装省略 devDependencies 后再执行 prepare，必然报 husky: not found。
    # API 的运行只需要 dependencies，因此生产部署不执行这些开发期生命周期脚本。
    return run_ok([npm, "install", "--omit=dev", "--ignore-scripts"], cwd=target)


def start_netease_container() -> bool:
    if not shutil.which("docker"):
        return False
    say("尝试用 Docker 启动网易云 API")
    quiet_ok(["docker", "rm", "-f", "oopzbot-netease"])
    if not run_ok([
        "docker", "run", "-d", "--name", "oopzbot-netease",
        "--restart", "unless-stopped", "-p", "3000:3000", NETEASE_DOCKER_IMAGE,
    ]):
        return False
    if wait_for_port("127.0.0.1", 3000, 20):
        return True
    warn("Docker 容器已创建，但网易云 API 在 20 秒内没有监听 3000 端口")
    run_ok(["docker", "logs", "--tail", "50", "oopzbot-netease"])
    return False


# --------------------------------------------------------------------------
# 体检与启动
# --------------------------------------------------------------------------


def wait_for_port(host: str, port: int, timeout: float) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def find_clash_kernel() -> str | None:
    configured = os.environ.get("CLASH_KERNEL_BIN", "").strip()
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    for candidate in ("mihomo", "clash-meta", "clash"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def start_clash(python: Path) -> subprocess.Popen | None:
    """按 .env 里的配置拉起 Clash 内核，并把代理地址交给 Bot。

    有些网络环境连不上 Oopz，必须走代理。返回内核进程，调用方负责收尾。
    """
    workdir = Path(os.environ.get("CLASH_WORKDIR", ROOT / "data" / "clash"))
    source = Path(os.environ.get("CLASH_SOURCE_CONFIG_PATH", workdir / "subscription.yaml"))
    converted = Path(
        os.environ.get("CLASH_CONVERTED_CONFIG_PATH", workdir / "subscription.converted.yaml")
    )
    config = Path(os.environ.get("CLASH_CONFIG_PATH", workdir / "config.yaml"))
    mixed_port = int(os.environ.get("CLASH_MIXED_PORT", "7890"))
    workdir.mkdir(parents=True, exist_ok=True)

    subscription = os.environ.get("CLASH_SUBSCRIPTION_URL", "").strip()
    if subscription:
        say("下载 Clash 订阅")
        try:
            import urllib.request

            with urllib.request.urlopen(subscription, timeout=30) as response:
                source.write_bytes(response.read())
        except Exception as exc:
            warn(f"订阅下载失败：{exc}")
            return None
    elif source.exists():
        pass
    elif config.exists():
        source = config
    else:
        warn("没有 Clash 订阅或配置，设置 CLASH_SUBSCRIPTION_URL 或 CLASH_CONFIG_PATH")
        return None

    if not run_ok([str(python), "tools/convert_subscription.py",
                   "--source", str(source), "--target", str(converted)]):
        warn("订阅转换失败")
        return None

    prepare = [
        str(python), "tools/prepare_clash_config.py",
        "--source", str(converted), "--target", str(config),
        "--mixed-port", str(mixed_port),
        "--socks-port", os.environ.get("CLASH_SOCKS_PORT", "7891"),
        "--external-controller", os.environ.get("CLASH_EXTERNAL_CONTROLLER", "127.0.0.1:9090"),
        "--log-level", os.environ.get("CLASH_LOG_LEVEL", "info"),
    ]
    for flag, name in (
        ("--allow-lan", "CLASH_ALLOW_LAN"),
        ("--bind-address", "CLASH_BIND_ADDRESS"),
        ("--secret", "CLASH_SECRET"),
    ):
        value = os.environ.get(name, "").strip()
        if value:
            prepare += [flag, value]
    if not run_ok(prepare):
        warn("生成 Clash 配置失败")
        return None

    kernel = find_clash_kernel()
    if not kernel:
        warn("找不到 Clash 内核，装 mihomo / clash-meta / clash 或设置 CLASH_KERNEL_BIN")
        return None

    proxy = os.environ.get("BOT_OOPZ_PROXY") or os.environ.get("CLASH_PROXY") or ""
    if not proxy or proxy == "clash":
        proxy = f"http://127.0.0.1:{mixed_port}"
    os.environ["BOT_OOPZ_PROXY"] = proxy

    say(f"启动 Clash 内核：{kernel}")
    log_path = workdir / "kernel.log"
    with open(log_path, "wb") as log_file:
        process = subprocess.Popen(
            [kernel, "-d", str(workdir), "-f", str(config)],
            stdout=log_file, stderr=subprocess.STDOUT, cwd=ROOT,
        )
    if not wait_for_port("127.0.0.1", mixed_port, 20):
        warn(f"Clash 没能就绪，看看 {log_path}")
        process.terminate()
        return None
    say(f"代理已就绪：{proxy}")
    return process


def screen_share_readiness() -> tuple[bool, bool, list[str]]:
    """返回（是否启用、是否就绪、不就绪原因），不回显任何凭据。"""
    enabled = config_section_flag("SCREEN_SHARE_CONFIG", "enabled")
    if not enabled:
        return False, True, []
    reasons: list[str] = []
    if not valid_agora_credential(
        config_section_string("SCREEN_SHARE_CONFIG", "agora_app_id")
    ):
        reasons.append("声网 App ID 未正确配置")
    if not valid_agora_credential(
        config_section_string("SCREEN_SHARE_CONFIG", "agora_app_certificate")
    ):
        reasons.append("声网 App Certificate 未正确配置")
    if not valid_screen_share_url(config_section_string("WEB_PLAYER_CONFIG", "url")):
        reasons.append("对外 Web 地址不是 HTTPS（或 localhost HTTP）")
    if not redis_alive():
        reasons.append("Redis 未就绪")
    if not screen_share_assets_ready():
        reasons.append("屏幕共享网页资源不完整")
    return True, not reasons, reasons


def report(python: Path) -> dict[str, bool]:
    checks = {
        "Python 依赖": python.exists(),
        "浏览器（语音）": browser_ready(python),
        "Redis（队列持久化 / 屏幕共享）": redis_alive(),
        "网易云 API（点歌）": (netease_dir() / "app.js").exists(),
    }
    config_ok = (ROOT / "config.py").exists() and has_usable_credentials(read_credentials())
    checks["Oopz 凭据"] = config_ok
    print()
    print("环境体检")
    for name, ok in checks.items():
        print(f"  [{'OK' if ok else '--'}] {name}")
    screen_enabled, screen_ready, screen_reasons = screen_share_readiness()
    if not screen_enabled:
        print("  [--] 屏幕共享（可选，未启用）")
    else:
        print(f"  [{'OK' if screen_ready else '!!'}] 屏幕共享")
        for reason in screen_reasons:
            print(f"       - {reason}")
    # 屏幕共享是可选功能；未启用不应拦截 Bot 启动。
    checks["屏幕共享"] = screen_ready
    return checks


def launch(python: Path) -> int:
    clash: subprocess.Popen | None = None
    if env_flag("CLASH_AUTO_START") or os.environ.get("CLASH_SUBSCRIPTION_URL", "").strip():
        step("启动 Clash 代理")
        clash = start_clash(python)
        if clash is None:
            warn("代理没起来，直连启动（连不上 Oopz 的话请检查代理配置）")

    print("\n启动 Oopz Bot（Ctrl+C 停止）\n" + "-" * 40, flush=True)
    try:
        return run([str(python), "main.py"]).returncode
    except KeyboardInterrupt:
        return 0
    finally:
        # Bot 退出后内核不收掉会一直占着端口，下次启动就撞上了
        if clash is not None and clash.poll() is None:
            say("停止 Clash 内核")
            clash.terminate()
            try:
                clash.wait(timeout=10)
            except subprocess.TimeoutExpired:
                clash.kill()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="一键部署并启动 Oopz Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-input", action="store_true", help="不提问，适合服务器无人值守")
    parser.add_argument("--no-start", action="store_true", help="只准备环境，不启动 Bot")
    parser.add_argument("--check", action="store_true", help="只体检，不做任何改动")
    parser.add_argument("--skip-install", action="store_true", help="跳过依赖安装，只启动")
    args = parser.parse_args()

    ensure_python_version()
    print(f"Oopz Bot 一键部署  ({platform.system()} / Python {platform.python_version()})")
    load_env_files()
    # 兼容原 start.sh 的开关，老用户的 .env 不用改
    skip_install = args.skip_install or env_flag("SKIP_INSTALL")

    if args.check:
        report(venv_python())
        return 0

    step("准备虚拟环境")
    python = ensure_venv()

    if not skip_install:
        step("安装 Python 依赖")
        install_requirements(python)
        step("安装浏览器（语音推流用）")
        install_browser(python)

    step("准备配置文件与目录")
    ensure_dirs()
    created = ensure_config_files()

    step("检查屏幕共享网页资源")
    setup_screen_share_assets(install=not skip_install)

    step("检查 Redis")
    setup_redis(install=not skip_install)

    step("检查网易云 API")
    setup_netease(install=not skip_install)

    step("检查 Oopz 凭据")
    credentials = read_credentials()
    if has_usable_credentials(credentials):
        say("凭据已配置")
    elif args.no_input:
        warn("缺少 Oopz 凭据，且当前是无人值守模式，不启动")
        warn("请在 config.py 填写 login_phone / login_password 后重跑")
        report(python)
        return 1
    elif not prompt_credentials():
        warn("没有凭据，Bot 无法登录，先不启动")
        warn(f"请编辑 {ROOT / 'config.py'} 的 login_phone / login_password 后重跑本脚本")
        report(python)
        return 1

    # 只在首次生成配置时走一遍可选项，之后重跑不再打断
    if created and not args.no_input:
        step("可选配置")
        prompt_optional_settings()

    checks = report(python)

    if args.no_start:
        say("环境已就绪，加上 --skip-install 重跑即可快速启动")
        return 0
    if not checks["Oopz 凭据"]:
        return 1
    return launch(python)


if __name__ == "__main__":
    sys.exit(main())
