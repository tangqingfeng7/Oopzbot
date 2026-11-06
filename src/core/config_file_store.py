"""配置文件的同进程串行化与原子替换辅助。"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ConfigFileStore")

PathLike = str | os.PathLike[str]

_CONFIG_FILE_WRITE_LOCK = threading.RLock()


@contextmanager
def config_file_write_lock() -> Iterator[None]:
    """串行化进程内所有配置文件的读-改-写事务。"""

    with _CONFIG_FILE_WRITE_LOCK:
        yield


@dataclass(frozen=True, slots=True)
class _StagedTextFile:
    target: Path
    replacement: Path
    backup: Path | None
    existed: bool


def _resolved_target(path: PathLike) -> Path:
    # Docker 把 /app/config.py 等稳定导入路径做成符号链接。替换
    # 真实目标才能保留链接本身，并确保 temp 与 bind mount 同文件系统。
    return Path(os.path.realpath(os.fspath(path)))


def _write_unique_sibling(
    target: Path,
    data: bytes,
    *,
    mode: int,
    suffix: str,
) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=suffix,
        dir=target.parent,
    )
    temp_path = Path(raw_path)
    try:
        os.chmod(temp_path, mode)
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        with suppress(OSError):
            os.close(fd)
        _unlink_best_effort(temp_path)
        raise
    return temp_path


def _stage_text_file(path: PathLike, content: str) -> _StagedTextFile:
    target = _resolved_target(path)
    try:
        target_stat = target.stat()
    except FileNotFoundError:
        existed = False
        mode = 0o600
        original = None
    else:
        existed = True
        mode = stat.S_IMODE(target_stat.st_mode)
        original = target.read_bytes()

    backup = None
    try:
        if original is not None:
            backup = _write_unique_sibling(
                target,
                original,
                mode=mode,
                suffix=".bak",
            )
        replacement = _write_unique_sibling(
            target,
            content.encode("utf-8"),
            mode=mode,
            suffix=".tmp",
        )
    except BaseException:
        _unlink_best_effort(backup)
        raise

    return _StagedTextFile(
        target=target,
        replacement=replacement,
        backup=backup,
        existed=existed,
    )


def _fsync_directory_best_effort(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _unlink_best_effort(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("清理配置临时文件失败 %s: %s", path, exc)


def _cleanup_staged(staged: Iterable[_StagedTextFile]) -> None:
    directories: set[Path] = set()
    for item in staged:
        _unlink_best_effort(item.replacement)
        _unlink_best_effort(item.backup)
        directories.add(item.target.parent)
    for directory in directories:
        _fsync_directory_best_effort(directory)


def _rollback_attempted(attempted: list[_StagedTextFile]) -> None:
    for item in reversed(attempted):
        try:
            if item.existed:
                if item.backup is None or not item.backup.exists():
                    raise FileNotFoundError(f"配置回滚备份不存在: {item.target}")
                os.replace(item.backup, item.target)
            else:
                item.target.unlink(missing_ok=True)
            _fsync_directory_best_effort(item.target.parent)
        except BaseException as exc:
            logger.error("回滚配置文件失败 %s: %s", item.target, exc)


def _commit_staged(staged: list[_StagedTextFile]) -> None:
    attempted: list[_StagedTextFile] = []
    try:
        for item in staged:
            # 先记录 attempted：即使底层 replace 在已生效后才报错，
            # 回滚仍会覆盖这一项。
            attempted.append(item)
            os.replace(item.replacement, item.target)
            _fsync_directory_best_effort(item.target.parent)
    except BaseException:
        _rollback_attempted(attempted)
        _cleanup_staged(staged)
        raise
    _cleanup_staged(staged)


def replace_text_files_atomically(writes: Iterable[tuple[PathLike, str]]) -> None:
    """先完整 stage 所有内容，再逐个原子替换目标。

    这是同进程事务：任一 replace 报错时，已尝试的文件会按逆序
    best-effort 回滚。调用方如果在替换前需要读取和编辑旧内容，应在
    :func:`config_file_write_lock` 中包住整个 read-edit-commit 过程；本函数
    内部再次获取同一 RLock，避免独立调用者绕过串行化。
    """

    pending = list(writes)
    if not pending:
        return
    with config_file_write_lock():
        staged: list[_StagedTextFile] = []
        targets: set[Path] = set()
        try:
            for path, content in pending:
                target = _resolved_target(path)
                if target in targets:
                    raise ValueError(f"同一事务不能重复写入配置目标: {target}")
                targets.add(target)
                staged.append(_stage_text_file(target, content))
        except BaseException:
            _cleanup_staged(staged)
            raise
        _commit_staged(staged)


__all__ = ["config_file_write_lock", "replace_text_files_atomically"]
