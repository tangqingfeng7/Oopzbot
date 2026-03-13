"""插件配置资产导出工具。"""

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

from app.infrastructure.plugin_runtime import export_plugin_config_assets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导出插件配置示例和结构说明文件。",
    )
    parser.add_argument(
        "plugins",
        nargs="*",
        help="要导出的插件名；为空时默认导出全部插件。",
    )
    parser.add_argument(
        "--output-dir",
        default="config/plugins",
        help="资产输出目录，默认是 config/plugins。",
    )
    parser.add_argument(
        "--plugins-dir",
        default="plugins",
        help="插件源码目录，默认是 plugins。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    exported = export_plugin_config_assets(
        args.plugins or None,
        output_dir=args.output_dir,
        plugins_dir=args.plugins_dir,
    )
    for plugin_name, example_path, schema_path in exported:
        print(f"[ok] {plugin_name}")
        print(f"  example: {example_path}")
        print(f"  schema : {schema_path}")

    print(f"已导出 {len(exported)} 个插件的配置资产。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
