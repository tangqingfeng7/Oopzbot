#!/usr/bin/env python3
"""
Convert common subscriptions into a Clash/Mihomo YAML config.
Supports native Clash YAML passthrough and base64 text subscriptions
containing vmess://, vless://, trojan://, and ss:// links.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

YAML_HINT_KEYS = (
    "proxies:",
    "proxy-groups:",
    "rules:",
    "mixed-port:",
    "port:",
    "socks-port:",
    "mode:",
    "dns:",
)
SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9._:/@-]+$")


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    text = str(value)
    if SAFE_STRING_RE.fullmatch(text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _dump_yaml(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if not item:
                    lines.append(f"{prefix}{key}: []" if isinstance(item, list) else f"{prefix}{key}: {{}}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return lines

    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                if item:
                    lines.append(f"{prefix}-")
                    lines.extend(_dump_yaml(item, indent + 2))
                else:
                    lines.append(f"{prefix}- []" if isinstance(item, list) else f"{prefix}- {{}}")
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines

    return [f"{prefix}{_yaml_scalar(value)}"]


def _decode_base64_loose(value: str) -> str:
    compact = "".join(value.strip().split())
    compact = compact.replace("-", "+").replace("_", "/")
    compact += "=" * ((4 - len(compact) % 4) % 4)
    raw = base64.b64decode(compact)
    return raw.decode("utf-8")


def _looks_like_yaml(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(YAML_HINT_KEYS)
    return False


def _load_subscription_lines(text: str) -> list[str]:
    if _looks_like_yaml(text):
        return []

    lines = [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]
    if not lines:
        return []

    if len(lines) == 1 and "://" not in lines[0]:
        try:
            decoded = _decode_base64_loose(lines[0])
        except (binascii.Error, UnicodeDecodeError):
            return lines
        decoded_lines = [line.strip() for line in decoded.replace("\r", "\n").splitlines() if line.strip()]
        if decoded_lines:
            return decoded_lines

    return lines


def _get_query_value(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[0] if values else default


def _unique_name(name: str, seen: dict[str, int], fallback: str) -> str:
    base = (name or fallback).strip() or fallback
    count = seen.get(base, 0) + 1
    seen[base] = count
    return base if count == 1 else f"{base}-{count}"


def _parse_vmess(uri: str, seen: dict[str, int]) -> dict[str, Any]:
    payload = uri[len("vmess://") :]
    decoded = _decode_base64_loose(payload)
    data = json.loads(decoded)

    server = data.get("add") or data.get("server")
    port = int(data.get("port") or 0)
    uuid = data.get("id", "")
    if not server or not port or not uuid:
        raise ValueError("invalid vmess node")

    network = (data.get("net") or "tcp").lower()
    tls_enabled = (data.get("tls") or data.get("security") or "").lower() in {"tls", "xtls"}
    name = _unique_name(data.get("ps", ""), seen, f"vmess-{server}:{port}")
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": int(data.get("aid") or 0),
        "cipher": data.get("scy") or "auto",
        "udp": True,
        "network": network,
    }

    if tls_enabled:
        proxy["tls"] = True
    if data.get("sni"):
        proxy["servername"] = data["sni"]
    elif data.get("host"):
        proxy["servername"] = data["host"]
    if str(data.get("allowInsecure", "")).lower() in {"1", "true"}:
        proxy["skip-cert-verify"] = True
    if data.get("alpn"):
        proxy["alpn"] = [item.strip() for item in str(data["alpn"]).split(",") if item.strip()]
    if data.get("fp"):
        proxy["client-fingerprint"] = data["fp"]

    host = data.get("host", "")
    path = data.get("path") or "/"
    if network == "ws":
        ws_opts: dict[str, Any] = {"path": path}
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif network == "grpc":
        service_name = data.get("path") or data.get("serviceName") or ""
        if service_name:
            proxy["grpc-opts"] = {"grpc-service-name": service_name}
    elif network in {"http", "h2"}:
        http_opts: dict[str, Any] = {"path": [path or "/"]}
        if host:
            http_opts["headers"] = {"Host": [host]}
        proxy["http-opts"] = http_opts

    return proxy


def _parse_vless(uri: str, seen: dict[str, int]) -> dict[str, Any]:
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)
    server = parsed.hostname
    port = parsed.port or 0
    uuid = unquote(parsed.username or "")
    if not server or not port or not uuid:
        raise ValueError("invalid vless node")

    network = _get_query_value(params, "type", "tcp").lower()
    security = _get_query_value(params, "security", "").lower()
    name = _unique_name(unquote(parsed.fragment or ""), seen, f"vless-{server}:{port}")
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "udp": True,
        "network": network,
    }

    if security in {"tls", "reality"}:
        proxy["tls"] = True
    if security == "reality":
        reality_opts = {}
        if _get_query_value(params, "pbk"):
            reality_opts["public-key"] = _get_query_value(params, "pbk")
        if _get_query_value(params, "sid"):
            reality_opts["short-id"] = _get_query_value(params, "sid")
        if reality_opts:
            proxy["reality-opts"] = reality_opts
    if _get_query_value(params, "sni"):
        proxy["servername"] = _get_query_value(params, "sni")
    if _get_query_value(params, "flow"):
        proxy["flow"] = _get_query_value(params, "flow")
    if _get_query_value(params, "allowInsecure").lower() in {"1", "true"}:
        proxy["skip-cert-verify"] = True
    if _get_query_value(params, "fp"):
        proxy["client-fingerprint"] = _get_query_value(params, "fp")

    host = _get_query_value(params, "host")
    path = _get_query_value(params, "path", "/")
    if network == "ws":
        ws_opts: dict[str, Any] = {"path": path}
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif network == "grpc":
        if _get_query_value(params, "serviceName"):
            proxy["grpc-opts"] = {"grpc-service-name": _get_query_value(params, "serviceName")}

    return proxy


def _parse_trojan(uri: str, seen: dict[str, int]) -> dict[str, Any]:
    parsed = urlparse(uri)
    params = parse_qs(parsed.query)
    server = parsed.hostname
    port = parsed.port or 0
    password = unquote(parsed.username or "")
    if not server or not port or not password:
        raise ValueError("invalid trojan node")

    network = _get_query_value(params, "type", "tcp").lower()
    name = _unique_name(unquote(parsed.fragment or ""), seen, f"trojan-{server}:{port}")
    proxy: dict[str, Any] = {
        "name": name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "udp": True,
        "network": network,
    }

    if _get_query_value(params, "sni"):
        proxy["sni"] = _get_query_value(params, "sni")
    if _get_query_value(params, "allowInsecure").lower() in {"1", "true"}:
        proxy["skip-cert-verify"] = True
    if _get_query_value(params, "fp"):
        proxy["client-fingerprint"] = _get_query_value(params, "fp")

    host = _get_query_value(params, "host")
    path = _get_query_value(params, "path", "/")
    if network == "ws":
        ws_opts: dict[str, Any] = {"path": path}
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif network == "grpc":
        if _get_query_value(params, "serviceName"):
            proxy["grpc-opts"] = {"grpc-service-name": _get_query_value(params, "serviceName")}

    return proxy


def _parse_ss(uri: str, seen: dict[str, int]) -> dict[str, Any]:
    fragment = ""
    if "#" in uri:
        uri, fragment = uri.split("#", 1)
        fragment = unquote(fragment)

    body = uri[len("ss://") :]
    plugin = ""
    if "?" in body:
        body, query = body.split("?", 1)
        plugin = _get_query_value(parse_qs(query), "plugin")

    if "@" in body:
        userinfo, server_part = body.rsplit("@", 1)
        try:
            decoded_userinfo = _decode_base64_loose(userinfo)
        except (binascii.Error, UnicodeDecodeError):
            decoded_userinfo = userinfo
    else:
        decoded_full = _decode_base64_loose(body)
        decoded_userinfo, server_part = decoded_full.rsplit("@", 1)

    cipher, password = decoded_userinfo.split(":", 1)
    server, port_text = server_part.rsplit(":", 1)
    name = _unique_name(fragment, seen, f"ss-{server}:{port_text}")
    proxy: dict[str, Any] = {
        "name": name,
        "type": "ss",
        "server": server,
        "port": int(port_text),
        "cipher": cipher,
        "password": password,
        "udp": True,
    }
    if plugin:
        proxy["plugin"] = plugin
    return proxy


def _parse_proxy_uri(uri: str, seen: dict[str, int]) -> dict[str, Any] | None:
    if uri.startswith("vmess://"):
        return _parse_vmess(uri, seen)
    if uri.startswith("vless://"):
        return _parse_vless(uri, seen)
    if uri.startswith("trojan://"):
        return _parse_trojan(uri, seen)
    if uri.startswith("ss://"):
        return _parse_ss(uri, seen)
    return None


def _build_config(proxies: list[dict[str, Any]]) -> dict[str, Any]:
    names = [proxy["name"] for proxy in proxies]
    return {
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "AUTO",
                "type": "url-test",
                "url": "http://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 50,
                "proxies": names or ["DIRECT"],
            },
            {
                "name": "PROXY",
                "type": "select",
                "proxies": ["AUTO", *names, "DIRECT"] if names else ["DIRECT"],
            },
        ],
        "rules": [
            "MATCH,PROXY",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert common subscriptions to Clash/Mihomo YAML.")
    parser.add_argument("--source", required=True, help="Downloaded subscription path.")
    parser.add_argument("--target", required=True, help="Generated Clash YAML path.")
    args = parser.parse_args()

    source = Path(args.source)
    target = Path(args.target)
    text = source.read_text(encoding="utf-8", errors="ignore")

    if _looks_like_yaml(text):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="\n")
        print("Subscription detected as Clash YAML; copied as-is.")
        return 0

    lines = _load_subscription_lines(text)
    proxies: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}
    skipped = 0
    for line in lines:
        try:
            proxy = _parse_proxy_uri(line, seen_names)
        except Exception:
            skipped += 1
            continue
        if proxy:
            proxies.append(proxy)
        else:
            skipped += 1

    if not proxies:
        raise SystemExit("Subscription conversion failed: no supported nodes found.")

    yaml_text = "\n".join(_dump_yaml(_build_config(proxies))).rstrip() + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml_text, encoding="utf-8", newline="\n")
    print(f"Converted subscription: {len(proxies)} proxies, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
