"""提供单一存储根、有界上传读取和原子本地文件写入。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from os import close, environ, fsync, replace
from pathlib import Path
from tempfile import mkstemp
from typing import Protocol


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
DEFAULT_STORAGE_ROOT = BACKEND_ROOT / "storage"


class ReadableUpload(Protocol):
    """描述 FastAPI UploadFile 在文件边界所需的最小接口。"""

    async def read(self, size: int = -1) -> bytes:
        """读取至多 size 字节。"""


def configured_storage_root() -> Path:
    """解析唯一 DAYU_STORAGE_ROOT；相对路径一律以仓库根为基准。"""

    configured = environ.get("DAYU_STORAGE_ROOT", "").strip()
    if not configured:
        return DEFAULT_STORAGE_ROOT.resolve()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return path.resolve()


def resolve_within(root: Path, *parts: str | Path) -> Path:
    """解析受控根目录内路径，拒绝绝对子路径和任何目录逃逸。"""

    resolved_root = Path(root).resolve()
    candidate = resolved_root
    for part in parts:
        value = Path(part)
        if value.is_absolute():
            raise ValueError("storage path must be relative")
        candidate /= value
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_root):
        raise ValueError("storage path escapes configured root")
    return resolved_candidate


def storage_directory(name: str) -> Path:
    """返回统一存储根下的一个受控业务目录。"""

    if not name or Path(name).name != name:
        raise ValueError("storage directory name must be one path segment")
    return resolve_within(configured_storage_root(), name)


async def read_limited_upload(file: ReadableUpload, max_bytes: int) -> bytes:
    """只读取上限加一字节，让调用方保留既有空文件和超限语义。"""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    return await file.read(max_bytes + 1)


@contextmanager
def atomic_output_path(directory: Path, filename: str) -> Iterator[tuple[Path, Path]]:
    """在目标目录创建临时路径，并仅在生产成功后原子替换最终文件。"""

    target_directory = Path(directory).resolve()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = resolve_within(target_directory, filename)
    if target.parent != target_directory:
        raise ValueError("atomic output filename must be one path segment")
    descriptor, temporary_name = mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target_directory
    )
    close(descriptor)
    temporary = Path(temporary_name)
    # GDAL 等外部生产器要求目标路径尚不存在；随机名仍由 mkstemp 生成。
    temporary.unlink()
    try:
        yield temporary, target
        replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_bytes(directory: Path, filename: str, content: bytes) -> Path:
    """把字节原子写入受控目录并返回最终路径。"""

    with atomic_output_path(directory, filename) as (temporary, target):
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            fsync(handle.fileno())
    return target


def atomic_write_text(
    directory: Path,
    filename: str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """把文本原子写入受控目录并返回最终路径。"""

    return atomic_write_bytes(directory, filename, content.encode(encoding))
