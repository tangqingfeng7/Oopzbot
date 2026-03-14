"""插件脚手架创建工具。"""

from __future__ import annotations

import argparse
import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from app.infrastructure.plugin_runtime import create_plugin_scaffold


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建标准插件脚手架。")
    parser.add_argument("plugin_name", help="插件名，只允许字母、数字和下划线。")
    parser.add_argument("--description", default="", help="插件说明。")
    parser.add_argument("--author", default="", help="插件作者。")
    parser.add_argument("--mention-prefix", default=None, help="@bot 指令前缀。")
    parser.add_argument("--slash-command", default=None, help="slash 命令，例如 /demo。")
    parser.add_argument(
        "--admin-only",
        action="store_true",
        help="如果指定，则脚手架默认生成管理员私有命令。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="如果指定，则覆盖已存在的同名插件文件。",
    )
    parser.add_argument(
        "--project-root",
        default=PROJECT_ROOT,
        help="项目根目录，默认是当前仓库根目录。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result = create_plugin_scaffold(
        args.plugin_name,
        project_root=args.project_root,
        description=args.description,
        author=args.author,
        mention_prefix=args.mention_prefix,
        slash_command=args.slash_command,
        is_public_command=not args.admin_only,
        force=args.force,
    )
    print(f"[ok] {result.plugin_name}")
    print(f"  module : {result.module_path}")
    print(f"  example: {result.example_path}")
    print(f"  schema : {result.schema_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
