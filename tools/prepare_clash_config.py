#!/usr/bin/env python3
"""
Normalize a Clash/Mihomo YAML config for local startup.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _apply_updates(text: str, updates: list[tuple[str, str]]) -> str:
    lines = text.splitlines()
    seen = {key: False for key, _ in updates}
    rendered = dict(updates)
    output: list[str] = []

    for line in lines:
        replaced = False
        if line and not line[0].isspace():
            for key, _ in updates:
                if re.match(rf"^{re.escape(key)}\s*:", line):
                    if not seen[key]:
                        output.append(f"{key}: {rendered[key]}")
                        seen[key] = True
                    replaced = True
                    break
        if not replaced:
            output.append(line)

    missing = [f"{key}: {rendered[key]}" for key, _ in updates if not seen[key]]
    if missing:
        output = missing + [""] + output

    return "\n".join(output).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Clash config for local runtime.")
    parser.add_argument("--source", required=True, help="Source Clash YAML path.")
    parser.add_argument("--target", required=True, help="Output Clash YAML path.")
    parser.add_argument("--mixed-port", type=int, default=None)
    parser.add_argument("--socks-port", type=int, default=None)
    parser.add_argument("--external-controller", default=None)
    parser.add_argument("--secret", default=None)
    parser.add_argument("--bind-address", default=None)
    parser.add_argument("--allow-lan", choices=("true", "false"), default=None)
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    source = Path(args.source)
    target = Path(args.target)
    text = source.read_text(encoding="utf-8")

    updates: list[tuple[str, str]] = []
    if args.mixed_port is not None:
        updates.append(("mixed-port", _yaml_scalar(args.mixed_port)))
    if args.socks_port is not None:
        updates.append(("socks-port", _yaml_scalar(args.socks_port)))
    if args.external_controller:
        updates.append(("external-controller", _yaml_scalar(args.external_controller)))
    if args.secret is not None:
        updates.append(("secret", _yaml_scalar(args.secret)))
    if args.bind_address:
        updates.append(("bind-address", _yaml_scalar(args.bind_address)))
    if args.allow_lan is not None:
        updates.append(("allow-lan", _yaml_scalar(args.allow_lan == "true")))
    if args.log_level:
        updates.append(("log-level", _yaml_scalar(args.log_level)))

    if updates:
        text = _apply_updates(text, updates)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
