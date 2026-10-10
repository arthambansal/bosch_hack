"""Bounded, read-only source tools. Never follows paths outside app-src."""
from pathlib import Path

from .agentkit import Tool
from .common import ROOT

SOURCE_ROOT = Path(ROOT) / "sandbox" / "app-src"
MAX_BYTES = 256_000


def _path(path="."):
    root = SOURCE_ROOT.resolve(strict=True)
    candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise ValueError("path outside permitted application source")
    if any(part == ".git" or part == ".env" or part.startswith(".env.") for part in candidate.relative_to(root).parts):
        raise ValueError("repository metadata and environment files are not source evidence")
    return candidate


def list_files(path="."):
    base = _path(path)
    files = []
    for p in sorted(base.rglob("*")):
        if len(files) >= 200:
            break
        try:
            checked = _path(str(p.relative_to(SOURCE_ROOT.resolve())))
            if checked.is_file():
                files.append(p.relative_to(SOURCE_ROOT.resolve()).as_posix())
        except (ValueError, OSError):
            continue
    return files


def read_file(path, start_line=1, end_line=40):
    if type(start_line) is not int or type(end_line) is not int or not 1 <= start_line <= end_line <= start_line + 79:
        raise ValueError("request 1-80 lines using positive integer line numbers")
    p = _path(path)
    with p.open("rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or b"\x00" in raw:
        raise ValueError("file too large or binary")
    lines = raw.decode("utf-8").splitlines()
    return "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1) if start_line <= i <= end_line)


def grep(pattern, path="."):
    """Literal matching avoids unbounded regular-expression execution."""
    if not isinstance(pattern, str) or not 1 <= len(pattern) <= 200:
        raise ValueError("pattern must be 1-200 characters")
    base = _path(path)
    names = [base.relative_to(SOURCE_ROOT.resolve()).as_posix()] if base.is_file() else list_files(path)
    matches = []
    for name in names:
        try:
            p = _path(name)
            with p.open("rb") as f:
                raw = f.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or b"\x00" in raw:
                continue
            for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                if pattern in line:
                    matches.append(f"{name}:{n}: {line[:240]}")
                    if len(matches) >= 20:
                        return matches
        except (OSError, UnicodeError, ValueError):
            continue
    return matches


def make_code_tools():
    return {t.name: t for t in (
        Tool("list_files", "List application source paths only", ["path"], list_files),
        Tool("read_file", "Read numbered source lines (max 80)", ["path", "start_line", "end_line"], read_file),
        Tool("grep", "Find literal text in application source", ["pattern", "path"], grep),
    )}
