from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class RuffBaseline:
    revision: str
    source_path: str


@dataclass
class ChangedFile:
    path: Path
    lines: set[int] | None = None
    ruff_baseline: RuffBaseline | None = None
    subtract_ruff_baseline: bool = False
    _baseline_disabled: bool = False

    def add_lines(self, lines: set[int] | None) -> None:
        if self.lines is None or lines is None:
            self.lines = None
        else:
            self.lines.update(lines)

    def set_baseline_candidate(self, baseline: RuffBaseline | None) -> None:
        if baseline is not None and not self._baseline_disabled and self.ruff_baseline is None:
            self.ruff_baseline = baseline

    def check_whole_file(self, *, subtract_baseline: bool) -> None:
        self.lines = None
        if subtract_baseline and self.ruff_baseline is not None and not self._baseline_disabled:
            self.subtract_ruff_baseline = True
            return
        self.ruff_baseline = None
        self.subtract_ruff_baseline = False
        self._baseline_disabled = True

    def includes(self, start: int, end: int | None = None) -> bool:
        if self.lines is None:
            return True
        end = start if end is None else max(start, end)
        return any(line in self.lines for line in range(start, end + 1))


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} 执行失败")
    return result.stdout


def _parse_hunk_lines(diff: str) -> set[int] | None:
    lines: set[int] = set()
    for raw in diff.splitlines():
        match = _HUNK.match(raw)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        # 纯删除 hunk 在新文件中没有可标记的行，但它可能让
        # 保留行出现未定义名称等诊断，因此要检查整个文件。
        if count == 0:
            return None
        lines.update(range(start, start + count))
    return lines


def _name_status(diff_args: list[str]) -> list[tuple[str, str, str]]:
    raw = _git(*diff_args, "--name-status", "--diff-filter=AMCR", "--", "*.py")
    result: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        status = fields[0]
        path = fields[-1]
        source_path = fields[-2] if status.startswith(("R", "C")) and len(fields) >= 3 else path
        result.append((status, path, source_path))
    return result


def _merge_diff(
    changed: dict[Path, ChangedFile],
    diff_args: list[str],
    baseline_revision: str | None,
) -> None:
    for status, raw_path, source_path in _name_status(diff_args):
        path = (ROOT / raw_path).resolve()
        if not path.is_file():
            continue
        entry = changed.setdefault(path, ChangedFile(path, set()))
        if status.startswith("A"):
            entry.check_whole_file(subtract_baseline=False)
            continue
        entry.set_baseline_candidate(
            RuffBaseline(baseline_revision, source_path) if baseline_revision else None
        )
        diff = _git(*diff_args, "--unified=0", "--", raw_path)
        lines = _parse_hunk_lines(diff)
        if lines is None:
            entry.check_whole_file(subtract_baseline=True)
        else:
            entry.add_lines(lines)


def _resolve_baseline(base: str | None) -> str | None:
    if base:
        revision = _git("merge-base", base, "HEAD").strip()
        if not revision:
            raise RuntimeError(f"无法计算 {base} 与 HEAD 的 merge-base")
        return revision
    return _git("rev-parse", "--verify", "HEAD", check=False).strip() or None


def collect_changed_files(base: str | None) -> dict[Path, ChangedFile]:
    changed: dict[Path, ChangedFile] = {}
    baseline_revision = _resolve_baseline(base)
    if base and baseline_revision:
        _merge_diff(
            changed,
            ["diff", f"{baseline_revision}...HEAD"],
            baseline_revision,
        )
    _merge_diff(changed, ["diff", "--cached"], baseline_revision)
    _merge_diff(changed, ["diff"], baseline_revision)
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", "*.py")
    for raw_path in untracked.splitlines():
        path = (ROOT / raw_path).resolve()
        if path.is_file():
            entry = ChangedFile(path, set())
            entry.check_whole_file(subtract_baseline=False)
            changed[path] = entry
    return {
        path: entry
        for path, entry in changed.items()
        if entry.lines is None or entry.lines
    }


def _tool(name: str) -> str:
    beside_python = Path(sys.executable).with_name(name)
    if beside_python.is_file():
        return str(beside_python)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"缺少开发工具 {name}；请安装 requirements-dev.txt")


def _run_json(command: list[str], *, input_text: str | None = None) -> object:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=input_text,
    )
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or result.stdout.strip() or "没有输出"
        raise RuntimeError(
            f"{Path(command[0]).name} 执行失败 (exit={result.returncode}): {detail}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stderr.strip() or result.stdout.strip() or "没有输出"
        raise RuntimeError(f"{Path(command[0]).name} 输出无效: {detail}") from exc


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _ruff_signature(diagnostic: dict) -> tuple[str, str]:
    return (
        str(diagnostic.get("code") or "Ruff"),
        str(diagnostic.get("message") or ""),
    )


def _baseline_ruff_signatures(entry: ChangedFile, ruff: str) -> Counter[tuple[str, str]]:
    baseline = entry.ruff_baseline
    if not entry.subtract_ruff_baseline or baseline is None:
        return Counter()
    source = _git("show", f"{baseline.revision}:{baseline.source_path}", check=False)
    payload = _run_json(
        [
            ruff,
            "check",
            "--output-format=json",
            "--stdin-filename",
            str(entry.path),
            "-",
        ],
        input_text=source,
    )
    if not isinstance(payload, list):
        return Counter()
    return Counter(
        _ruff_signature(diagnostic)
        for diagnostic in payload
        if isinstance(diagnostic, dict)
    )


def run_ruff(changed: dict[Path, ChangedFile]) -> list[str]:
    ruff = _tool("ruff")
    payload = _run_json(
        [
            ruff,
            "check",
            "--output-format=json",
            "--force-exclude",
            *[str(path) for path in sorted(changed)],
        ]
    )
    failures: list[str] = []
    baseline_signatures: dict[Path, Counter[tuple[str, str]]] = {}
    for diagnostic in payload if isinstance(payload, list) else []:
        path = Path(str(diagnostic.get("filename", ""))).resolve()
        entry = changed.get(path)
        if entry is None:
            continue
        start = int((diagnostic.get("location") or {}).get("row") or 1)
        end = int((diagnostic.get("end_location") or {}).get("row") or start)
        touches_changed_line = entry.includes(start, end)
        fix = diagnostic.get("fix")
        raw_edits = fix.get("edits", []) if isinstance(fix, dict) else []
        edits = raw_edits if isinstance(raw_edits, list) else []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            edit_start = int((edit.get("location") or {}).get("row") or 1)
            edit_end = int((edit.get("end_location") or {}).get("row") or edit_start)
            touches_changed_line = touches_changed_line or entry.includes(
                edit_start,
                edit_end,
            )
        if touches_changed_line:
            if entry.subtract_ruff_baseline:
                remaining = baseline_signatures.get(path)
                if remaining is None:
                    remaining = _baseline_ruff_signatures(entry, ruff)
                    baseline_signatures[path] = remaining
                signature = _ruff_signature(diagnostic)
                if remaining[signature] > 0:
                    remaining[signature] -= 1
                    continue
            failures.append(
                f"{_relative(path)}:{start}: "
                f"{diagnostic.get('code', 'Ruff')} {diagnostic.get('message', '')}"
            )
    return failures


def run_pyright(changed: dict[Path, ChangedFile]) -> list[str]:
    payload = _run_json(
        [
            _tool("pyright"),
            "--outputjson",
            "--pythonpath",
            sys.executable,
            *[str(path) for path in sorted(changed)],
        ]
    )
    failures: list[str] = []
    diagnostics = payload.get("generalDiagnostics", []) if isinstance(payload, dict) else []
    for diagnostic in diagnostics:
        path = Path(str(diagnostic.get("file", ""))).resolve()
        entry = changed.get(path)
        if entry is None:
            continue
        location = diagnostic.get("range") or {}
        start = int((location.get("start") or {}).get("line") or 0) + 1
        end = int((location.get("end") or {}).get("line") or (start - 1)) + 1
        if entry.includes(start, end):
            rule = diagnostic.get("rule") or diagnostic.get("severity") or "Pyright"
            failures.append(f"{_relative(path)}:{start}: {rule} {diagnostic.get('message', '')}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="与 HEAD 比较的 Git base SHA/ref")
    args = parser.parse_args()
    try:
        changed = collect_changed_files(args.base)
        if not changed:
            print("增量质量门禁：没有 Python 新增/修改行。")
            return 0
        failures = [*run_ruff(changed), *run_pyright(changed)]
    except RuntimeError as exc:
        print(f"增量质量门禁无法执行：{exc}", file=sys.stderr)
        return 2
    if failures:
        print("增量质量门禁失败：", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"增量质量门禁通过：检查 {len(changed)} 个 Python 文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
