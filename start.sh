#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

load_env_file() {
  local env_file="$1"
  if [ -f "$env_file" ]; then
    echo "Loading environment from $env_file"
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
  fi
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SKIP_INSTALL="${SKIP_INSTALL:-0}"
SKIP_PLAYWRIGHT_INSTALL="${SKIP_PLAYWRIGHT_INSTALL:-0}"
CLASH_AUTO_START="${CLASH_AUTO_START:-0}"
CLASH_WORKDIR="${CLASH_WORKDIR:-$ROOT_DIR/data/clash}"
CLASH_SOURCE_CONFIG_PATH="${CLASH_SOURCE_CONFIG_PATH:-$CLASH_WORKDIR/subscription.yaml}"
CLASH_CONVERTED_CONFIG_PATH="${CLASH_CONVERTED_CONFIG_PATH:-$CLASH_WORKDIR/subscription.converted.yaml}"
CLASH_CONFIG_PATH="${CLASH_CONFIG_PATH:-$CLASH_WORKDIR/config.yaml}"
CLASH_MIXED_PORT="${CLASH_MIXED_PORT:-7890}"
CLASH_SOCKS_PORT="${CLASH_SOCKS_PORT:-7891}"
CLASH_EXTERNAL_CONTROLLER="${CLASH_EXTERNAL_CONTROLLER:-127.0.0.1:9090}"
CLASH_LOG_LEVEL="${CLASH_LOG_LEVEL:-info}"
created_config=0
CLASH_PID=""

cleanup() {
  if [ -n "${CLASH_PID:-}" ] && kill -0 "$CLASH_PID" >/dev/null 2>&1; then
    echo "Stopping Clash kernel ($CLASH_PID)..."
    kill "$CLASH_PID" >/dev/null 2>&1 || true
    wait "$CLASH_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

pick_downloader() {
  if command -v curl >/dev/null 2>&1; then
    echo "curl"
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    echo "wget"
    return 0
  fi
  return 1
}

download_file() {
  local url="$1"
  local output_path="$2"
  local downloader
  downloader="$(pick_downloader)" || {
    echo "curl or wget is required to download Clash subscriptions."
    return 1
  }

  mkdir -p "$(dirname "$output_path")"
  if [ "$downloader" = "curl" ]; then
    curl -fsSL --retry 3 --connect-timeout 10 "$url" -o "$output_path"
  else
    wget -qO "$output_path" "$url"
  fi
}

find_clash_kernel() {
  if [ -n "${CLASH_KERNEL_BIN:-}" ]; then
    if [ -x "$CLASH_KERNEL_BIN" ]; then
      echo "$CLASH_KERNEL_BIN"
      return 0
    fi
    if command -v "$CLASH_KERNEL_BIN" >/dev/null 2>&1; then
      command -v "$CLASH_KERNEL_BIN"
      return 0
    fi
    echo "Configured CLASH_KERNEL_BIN was not found: $CLASH_KERNEL_BIN" >&2
    return 1
  fi

  local candidate
  for candidate in mihomo clash-meta clash; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

wait_for_proxy() {
  local proxy_url="$1"
  local timeout="${2:-20}"
  python - "$proxy_url" "$timeout" <<'PY'
import socket
import sys
import time
from urllib.parse import urlparse

url = sys.argv[1]
timeout = float(sys.argv[2])
parsed = urlparse(url if "://" in url else f"http://{url}")
host = parsed.hostname or "127.0.0.1"
port = parsed.port
if not port:
    sys.exit(0)

deadline = time.time() + timeout
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(0.5)

print(f"Timed out waiting for proxy {host}:{port}", file=sys.stderr)
sys.exit(1)
PY
}

prepare_clash_runtime() {
  local source_path=""
  local kernel_bin=""
  local -a prepare_args
  prepare_args=(
    --target "$CLASH_CONFIG_PATH"
    --mixed-port "$CLASH_MIXED_PORT"
    --socks-port "$CLASH_SOCKS_PORT"
    --external-controller "$CLASH_EXTERNAL_CONTROLLER"
    --log-level "$CLASH_LOG_LEVEL"
  )

  if [ -n "${CLASH_ALLOW_LAN:-}" ]; then
    prepare_args+=(--allow-lan "$CLASH_ALLOW_LAN")
  fi
  if [ -n "${CLASH_BIND_ADDRESS:-}" ]; then
    prepare_args+=(--bind-address "$CLASH_BIND_ADDRESS")
  fi
  if [ -n "${CLASH_SECRET:-}" ]; then
    prepare_args+=(--secret "$CLASH_SECRET")
  fi

  if [ -n "${CLASH_SUBSCRIPTION_URL:-}" ]; then
    echo "Downloading Clash subscription..."
    download_file "$CLASH_SUBSCRIPTION_URL" "$CLASH_SOURCE_CONFIG_PATH"
    source_path="$CLASH_SOURCE_CONFIG_PATH"
  elif [ -f "$CLASH_SOURCE_CONFIG_PATH" ]; then
    source_path="$CLASH_SOURCE_CONFIG_PATH"
  elif [ -f "$CLASH_CONFIG_PATH" ]; then
    source_path="$CLASH_CONFIG_PATH"
  else
    echo "No Clash subscription or config found. Set CLASH_SUBSCRIPTION_URL or CLASH_CONFIG_PATH."
    return 1
  fi

  python tools/convert_subscription.py --source "$source_path" --target "$CLASH_CONVERTED_CONFIG_PATH"
  python tools/prepare_clash_config.py --source "$CLASH_CONVERTED_CONFIG_PATH" "${prepare_args[@]}"

  kernel_bin="$(find_clash_kernel)" || {
    echo "Clash kernel not found. Install mihomo/clash-meta/clash or set CLASH_KERNEL_BIN."
    return 1
  }

  if [ -z "${BOT_OOPZ_PROXY:-}" ]; then
    export BOT_OOPZ_PROXY="${CLASH_PROXY:-http://127.0.0.1:$CLASH_MIXED_PORT}"
  fi
  if [ "${BOT_OOPZ_PROXY:-}" = "clash" ]; then
    export BOT_OOPZ_PROXY="http://127.0.0.1:$CLASH_MIXED_PORT"
  fi

  mkdir -p "$CLASH_WORKDIR"
  echo "Starting Clash kernel: $kernel_bin"
  "$kernel_bin" -d "$CLASH_WORKDIR" -f "$CLASH_CONFIG_PATH" >"$CLASH_WORKDIR/kernel.log" 2>&1 &
  CLASH_PID=$!

  if ! wait_for_proxy "${BOT_OOPZ_PROXY:-http://127.0.0.1:$CLASH_MIXED_PORT}" 20; then
    echo "Clash kernel failed to become ready. Recent log output:"
    tail -n 40 "$CLASH_WORKDIR/kernel.log" 2>/dev/null || true
    return 1
  fi
  echo "Clash proxy is ready at ${BOT_OOPZ_PROXY:-http://127.0.0.1:$CLASH_MIXED_PORT}"
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.10+ is required. Set PYTHON_BIN if python3 is not in PATH."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip
else
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

if [ "$SKIP_INSTALL" != "1" ]; then
  pip install -r requirements.txt
fi

if [ "$SKIP_PLAYWRIGHT_INSTALL" != "1" ]; then
  _PW_MARKER="$VENV_DIR/.playwright_chromium_installed"
  if [ -f "$_PW_MARKER" ]; then
    echo "Playwright chromium already installed, skipping. (delete $_PW_MARKER to force reinstall)"
  else
    python -m playwright install --with-deps chromium
    touch "$_PW_MARKER"
  fi
fi

if [ ! -f config.py ] && [ -f config.example.py ]; then
  cp config.example.py config.py
  created_config=1
  echo "Created config.py from config.example.py"
fi

if [ ! -f private_key.py ] && [ -f private_key.example.py ]; then
  cp private_key.example.py private_key.py
  created_config=1
  echo "Created private_key.py from private_key.example.py"
fi

for example_json in config/plugins/*.example.json; do
  [ -e "$example_json" ] || break
  target="${example_json%.example.json}.json"
  if [ ! -f "$target" ]; then
    cp "$example_json" "$target"
  fi
done

if [ -n "${CLASH_PROXY:-}" ] && [ -z "${BOT_OOPZ_PROXY:-}" ]; then
  export BOT_OOPZ_PROXY="$CLASH_PROXY"
fi

if [ "${BOT_OOPZ_PROXY:-}" = "clash" ]; then
  export BOT_OOPZ_PROXY="http://127.0.0.1:$CLASH_MIXED_PORT"
fi

if [ "$created_config" = "1" ]; then
  echo "Config templates were created. Edit config.py/private_key.py, then rerun ./start.sh."
  exit 0
fi

if [ -n "${CLASH_SUBSCRIPTION_URL:-}" ]; then
  CLASH_AUTO_START=1
fi

if is_true "$CLASH_AUTO_START"; then
  prepare_clash_runtime
fi

echo "Starting Oopz Bot..."
python main.py
