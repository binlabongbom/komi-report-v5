"""Fail-closed release checks for customer data, exports, and secrets.

Findings report only a category and relative path. Secret values are never
included in exceptions or command output.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FORBIDDEN_PARTS = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "customer-data",
    "customer_exports",
    "dist",
    "exports",
    "logs",
    "node_modules",
    "outputs",
    "release",
    "runtime-cache",
    "web-runtime",
}
FORBIDDEN_SUFFIXES = {
    ".csv",
    ".db",
    ".db-shm",
    ".db-wal",
    ".env",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".xls",
    ".xlsx",
}
FORBIDDEN_EXACT_NAMES = {
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_rsa",
    "id_rsa.pub",
}
SECRET_PATTERNS = {
    "private-key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    ),
    "github-token": re.compile(
        rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
    ),
    "aws-access-key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "slack-token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "basic-auth-url": re.compile(rb"https?://[^/\s:@]+:[^@\s/]+@"),
}
MAX_SECRET_SCAN_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class SafetyFinding:
    category: str
    path: str


class ReleaseSafetyError(RuntimeError):
    def __init__(self, findings: Iterable[SafetyFinding]):
        unique = sorted(set(findings), key=lambda item: (item.path, item.category))
        self.findings = unique
        summary = ", ".join(f"{item.category}:{item.path}" for item in unique[:20])
        if len(unique) > 20:
            summary += f", ... (+{len(unique) - 20} more)"
        super().__init__(f"release safety check failed: {summary}")


def _path_findings(relative_name: str) -> list[SafetyFinding]:
    normalized = PurePosixPath(relative_name.replace("\\", "/"))
    parts = tuple(part.casefold() for part in normalized.parts)
    name = normalized.name.casefold()
    suffixes = tuple(suffix.casefold() for suffix in normalized.suffixes)
    findings: list[SafetyFinding] = []

    if any(part in FORBIDDEN_PARTS for part in parts):
        findings.append(SafetyFinding("forbidden-path", normalized.as_posix()))
    if name.startswith(".env") or name in FORBIDDEN_EXACT_NAMES:
        findings.append(SafetyFinding("credential-file", normalized.as_posix()))
    if any(suffix in FORBIDDEN_SUFFIXES for suffix in suffixes):
        findings.append(SafetyFinding("forbidden-file-type", normalized.as_posix()))
    if ("token" in name or "credential" in name) and normalized.suffix.casefold() not in {
        ".py",
        ".ts",
        ".tsx",
    }:
        findings.append(SafetyFinding("credential-file", normalized.as_posix()))
    return findings


def _secret_findings(data: bytes, relative_name: str) -> list[SafetyFinding]:
    if len(data) > MAX_SECRET_SCAN_BYTES or b"\x00" in data[:8192]:
        return []
    return [
        SafetyFinding(category, relative_name)
        for category, pattern in SECRET_PATTERNS.items()
        if pattern.search(data)
    ]


def scan_files(
    files: Iterable[Path],
    *,
    root: Path,
    scan_secrets: bool = True,
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    root = root.resolve()
    for path in files:
        path = path.resolve()
        try:
            relative_name = path.relative_to(root).as_posix()
        except ValueError:
            relative_name = path.name
            findings.append(SafetyFinding("outside-release-root", relative_name))
        findings.extend(_path_findings(relative_name))
        if scan_secrets and path.is_file():
            findings.extend(_secret_findings(path.read_bytes(), relative_name))
    return findings


def assert_release_safe(
    files: Iterable[Path],
    *,
    root: Path,
    scan_secrets: bool = True,
) -> None:
    findings = scan_files(files, root=root, scan_secrets=scan_secrets)
    if findings:
        raise ReleaseSafetyError(findings)


def assert_tree_safe(root: Path, *, scan_secrets: bool = True) -> None:
    assert_release_safe(
        (path for path in root.rglob("*") if path.is_file()),
        root=root,
        scan_secrets=scan_secrets,
    )


def assert_zip_safe(archive: Path, *, scan_secrets: bool = True) -> None:
    findings: list[SafetyFinding] = []
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            if info.is_dir():
                continue
            findings.extend(_path_findings(info.filename))
            if scan_secrets and info.file_size <= MAX_SECRET_SCAN_BYTES:
                findings.extend(_secret_findings(zipped.read(info), info.filename))
    if findings:
        raise ReleaseSafetyError(findings)


def git_identity(project_root: Path) -> tuple[str, str]:
    """Return commit and source state without exposing Git configuration."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return "UNCOMMITTED", "uncommitted"

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return commit, "dirty" if dirty else "clean"
