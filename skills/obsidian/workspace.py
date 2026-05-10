"""
workspace.py — Path-safe IO boundary for an Obsidian vault.

Inspired by rowboat's apps/x/packages/core/src/workspace/workspace.ts:
all file operations go through `VaultWorkspace`, which enforces that
resolved paths stay inside the vault root, performs atomic writes,
detects external modifications via mtime + content hash, and moves
deleted files to a trash directory outside the vault (so the Obsidian
graph and search index stay clean).

This module has zero business dependencies — only stdlib.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePath
from typing import Iterator


class WorkspaceError(Exception):
    """Base error for workspace operations."""


class PathOutsideVaultError(WorkspaceError):
    """Raised when a requested path resolves outside the vault root."""


class ConflictError(WorkspaceError):
    """Raised when file state changed since the caller observed it."""


@dataclass(frozen=True)
class WorkspaceStat:
    """Snapshot of a file used for optimistic concurrency control."""

    mtime_ns: int
    size: int
    content_hash: str  # sha256 hex; empty string for non-existent files

    @classmethod
    def missing(cls) -> "WorkspaceStat":
        return cls(mtime_ns=0, size=0, content_hash="")

    @property
    def exists(self) -> bool:
        return self.content_hash != ""


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VaultWorkspace:
    """Safe IO surface for a single Obsidian vault directory.

    All public methods accept paths relative to ``root``. Absolute paths,
    ``..`` traversal, and symlinks pointing outside the vault are
    rejected with :class:`PathOutsideVaultError`.
    """

    def __init__(self, root: Path, trash_dir: Path | None = None) -> None:
        root = Path(root).expanduser()
        if not root.exists():
            raise WorkspaceError(f"Vault root does not exist: {root}")
        if not root.is_dir():
            raise WorkspaceError(f"Vault root is not a directory: {root}")

        self._root = root.resolve()

        if trash_dir is None:
            # Default outside the vault so Obsidian graph/search ignore it.
            trash_dir = self._root.parent / f".claude-obsidian-trash" / self._root.name
        self._trash_dir = Path(trash_dir).expanduser().resolve()

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def trash_dir(self) -> Path:
        return self._trash_dir

    def resolve_path(self, rel: str | PurePath) -> Path:
        """Resolve ``rel`` to an absolute path inside the vault.

        Rejects:
          - absolute input paths
          - paths that, after resolution, escape the vault root
            (catches ``..`` and out-of-tree symlinks)
        """

        candidate = Path(rel)
        if candidate.is_absolute():
            raise PathOutsideVaultError(
                f"Absolute paths are not allowed: {rel}"
            )

        # Reject explicit traversal up-front for a clearer error than
        # the post-resolve check would give.
        if any(part == ".." for part in candidate.parts):
            raise PathOutsideVaultError(
                f"Path traversal not allowed: {rel}"
            )

        joined = (self._root / candidate)
        # ``strict=False`` lets us resolve paths for files that do not
        # yet exist (e.g. before ``write_atomic``).
        resolved = joined.resolve(strict=False)

        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise PathOutsideVaultError(
                f"Resolved path escapes vault: {rel} -> {resolved}"
            ) from exc

        return resolved

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def exists(self, rel: str | PurePath) -> bool:
        try:
            return self.resolve_path(rel).exists()
        except PathOutsideVaultError:
            return False

    def read_bytes(self, rel: str | PurePath) -> bytes:
        return self.resolve_path(rel).read_bytes()

    def read_text(self, rel: str | PurePath, encoding: str = "utf-8") -> str:
        # ``errors='replace'`` matches the existing obsidian_writer behavior
        # for tolerance against vault files with mixed encodings.
        return self.resolve_path(rel).read_text(encoding=encoding, errors="replace")

    def stat(self, rel: str | PurePath) -> WorkspaceStat:
        path = self.resolve_path(rel)
        if not path.exists():
            return WorkspaceStat.missing()
        st = path.stat()
        data = path.read_bytes()
        return WorkspaceStat(
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            content_hash=_hash_bytes(data),
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write_atomic(
        self,
        rel: str | PurePath,
        data: bytes | str,
        *,
        expect: WorkspaceStat | None = None,
        encoding: str = "utf-8",
    ) -> WorkspaceStat:
        """Atomically write ``data`` to ``rel``.

        Uses a sibling ``.tmp`` file followed by :func:`os.replace`,
        which is atomic on both POSIX and Windows.

        If ``expect`` is provided, the current on-disk stat must match
        it; otherwise :class:`ConflictError` is raised. Pass
        ``WorkspaceStat.missing()`` to assert the file does not yet
        exist.
        """

        path = self.resolve_path(rel)

        if expect is not None:
            current = self._stat_no_resolve(path)
            if not _stats_match(current, expect):
                raise ConflictError(
                    f"Concurrent modification detected for {rel}: "
                    f"expected hash={expect.content_hash[:8]} mtime_ns={expect.mtime_ns}, "
                    f"got hash={current.content_hash[:8]} mtime_ns={current.mtime_ns}"
                )

        path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, str):
            payload = data.encode(encoding)
        else:
            payload = data

        tmp = path.with_name(path.name + ".tmp")
        try:
            # ``x`` mode would race with prior crashes leaving stale tmp;
            # we overwrite our own tmp file deterministically.
            with open(tmp, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            # Best-effort cleanup so a crashed write doesn't leave .tmp
            # files visible in the vault.
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

        return self._stat_no_resolve(path)

    # ------------------------------------------------------------------
    # Delete / rename
    # ------------------------------------------------------------------

    def move_to_trash(self, rel: str | PurePath) -> Path:
        """Move ``rel`` to the trash directory and return the trashed path."""

        path = self.resolve_path(rel)
        if not path.exists():
            raise WorkspaceError(f"Cannot trash missing file: {rel}")

        rel_inside = path.relative_to(self._root)
        # Microsecond resolution covers most cases; on Windows the
        # clock granularity (~15ms) can repeat within the same call,
        # so we additionally probe for collisions and append a counter.
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        base = self._trash_dir / f"{rel_inside}.trashed-{ts}"
        target = base
        counter = 1
        while target.exists():
            target = base.with_name(f"{base.name}-{counter}")
            counter += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        return target

    def rename(
        self,
        src_rel: str | PurePath,
        dst_rel: str | PurePath,
        *,
        expect: WorkspaceStat | None = None,
    ) -> WorkspaceStat:
        """Rename ``src_rel`` to ``dst_rel`` atomically."""

        src = self.resolve_path(src_rel)
        dst = self.resolve_path(dst_rel)

        if not src.exists():
            raise WorkspaceError(f"Source does not exist: {src_rel}")
        if dst.exists():
            raise WorkspaceError(f"Destination already exists: {dst_rel}")

        if expect is not None:
            current = self._stat_no_resolve(src)
            if not _stats_match(current, expect):
                raise ConflictError(
                    f"Concurrent modification detected for {src_rel}"
                )

        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return self._stat_no_resolve(dst)

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def iter_files(
        self,
        subdir: str | PurePath = "",
        pattern: str = "*.md",
    ) -> Iterator[Path]:
        """Yield absolute paths to files matching ``pattern`` under ``subdir``.

        The ``.trash`` directory is always excluded, even when subdir
        is empty, because it lives outside ``root`` by default and
        won't be traversed; this is a defensive guard for callers that
        configure trash inside the vault.
        """

        base = self.resolve_path(subdir) if subdir else self._root
        if not base.exists():
            return

        for path in base.rglob(pattern):
            if not path.is_file():
                continue
            try:
                path.relative_to(self._trash_dir)
                continue  # inside trash → skip
            except ValueError:
                pass
            yield path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _stat_no_resolve(self, path: Path) -> WorkspaceStat:
        if not path.exists():
            return WorkspaceStat.missing()
        st = path.stat()
        data = path.read_bytes()
        return WorkspaceStat(
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            content_hash=_hash_bytes(data),
        )


def _stats_match(a: WorkspaceStat, b: WorkspaceStat) -> bool:
    """Conflict guard.

    Content hash is the source of truth: if it matches, the file is
    semantically identical regardless of mtime jitter from the
    Obsidian client. Hash mismatch is always a real conflict.
    """

    return a.content_hash == b.content_hash
