"""Async file transfer helpers using rsync subprocess.

All NFS-touching file operations run as child processes via
asyncio.create_subprocess_exec so that kernel D-state (uninterruptible
sleep) on NFS I/O never blocks the uvicorn event loop.

See ARM's arm/ripper/utils.py:_move_to_shared_storage() for the sync
equivalent used in the Flask ripper.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


async def async_copy(src: str, dst: str, *, remove_source: bool = False) -> None:
    """Copy a file or directory tree using rsync subprocess.

    Args:
        src: Source path (file or directory).
        dst: Destination path.
        remove_source: If True, remove source files after successful transfer.
    """
    src_path = Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Source does not exist: {src}")

    cmd = ["rsync", "-a", "--info=name1"]

    if remove_source:
        cmd.append("--remove-source-files")

    if src_path.is_dir():
        # Trailing slash = merge contents into dst
        os.makedirs(dst, exist_ok=True)
        cmd.extend([src.rstrip("/") + "/", dst.rstrip("/") + "/"])
    else:
        # Single file copy
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        cmd.extend([src, dst])

    logger.info(f"rsync {'(move)' if remove_source else '(copy)'}: {src} -> {dst}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode().strip()[:200]
        logger.error(f"rsync failed (exit {proc.returncode}): {err_msg}")
        raise OSError(f"rsync failed: {err_msg}")

    # Log transferred files
    for line in stdout.decode().strip().splitlines():
        if line.strip():
            logger.debug(f"rsync: {line.strip()}")

    # rsync --remove-source-files leaves empty directories
    if remove_source and src_path.is_dir():
        await async_rmtree(src)

    logger.info(f"rsync complete: {src} -> {dst}")


async def async_copy_file(src: str, dst: str) -> None:
    """Copy a single file using rsync subprocess."""
    await async_copy(src, dst, remove_source=False)


async def async_move_file(src: str, dst: str) -> None:
    """Move a single file using rsync + delete.

    For single files, rsync --remove-source-files handles cleanup.
    """
    src_path = Path(src)
    dst_path = Path(dst)
    os.makedirs(dst_path.parent, exist_ok=True)

    cmd = ["rsync", "-a", "--remove-source-files", "--info=name1", src, dst]

    logger.debug(f"rsync move: {src} -> {dst}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode().strip()[:200]
        logger.error(f"rsync move failed (exit {proc.returncode}): {err_msg}")
        raise OSError(f"rsync move failed: {err_msg}")


async def async_rmtree(path: str) -> None:
    """Remove a directory tree using subprocess rm -rf.

    Runs as a child process so NFS D-state on unlink doesn't block
    the event loop.
    """
    if not Path(path).exists():
        return

    proc = await asyncio.create_subprocess_exec(
        "rm", "-rf", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode().strip()[:200]
        logger.error(f"rm -rf failed (exit {proc.returncode}): {err_msg}")
        raise OSError(f"rm -rf failed: {err_msg}")
