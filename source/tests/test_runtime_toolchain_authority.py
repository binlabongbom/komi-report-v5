"""Keep runtime pins, secure downloads and locked CA tooling in sync."""

from __future__ import annotations

import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

from tools import build_windows_rc as windows
from tools import package_windows_test_kit as portable

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_pins_match_windows_builders_and_web_metadata():
    python_version = (ROOT / ".python-version").read_text().strip()
    node_version = (ROOT / ".node-version").read_text().strip()
    package = json.loads((ROOT / "web/package.json").read_text())
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    assert python_version == portable.PYTHON_VERSION == "3.14.10"
    assert node_version == windows.NODE_VERSION == "24.22.2"
    assert windows.NPM_VERSION == "12.2.2"
    assert package["packageManager"] == f"npm@{windows.NPM_VERSION}"
    assert (
        package["engines"]
        == lock["packages"][""]["engines"]
        == {"node": f">={node_version} <25", "npm": f">={windows.NPM_VERSION} <13"}
    )
    setup = (ROOT / "tools/ci/setup_cloud.sh").read_text()
    assert f"npm@{windows.NPM_VERSION}" in setup
    assert "--locked" in setup


def test_ca_security_tools_remain_locked_with_hashes():
    lock = tomllib.loads((ROOT / "source/uv.lock").read_text())
    packages = {item["name"]: item for item in lock["package"]}
    exported = (ROOT / "source/requirements-dev.lock.txt").read_text()
    for name, version in [("certifi", "2026.10.19"), ("pip", "26.2.2"), ("uv", "0.13.6")]:
        assert packages[name]["version"] == version
        assert f"{name}=={version} \\\n    --hash=sha256:" in exported
        assert all(wheel["hash"].startswith("sha256:") for wheel in packages[name]["wheels"])


def test_python_runtime_checksum_is_verified_before_extraction(tmp_path, monkeypatch):
    archive = tmp_path / "python.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("python314._pth", "#import site\n")
        zipped.writestr("python.exe", b"synthetic runtime")
    data = archive.read_bytes()
    monkeypatch.setattr(portable.urllib.request, "urlretrieve", lambda _url, path: path.write_bytes(data))
    rejected = tmp_path / "rejected"
    with pytest.raises(RuntimeError, match="checksum verification failed"):
        portable.download_python_runtime(rejected)
    assert not list(rejected.iterdir())

    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(portable, "PYTHON_EMBED_SHA256", digest)
    accepted = tmp_path / "accepted"
    assert portable.download_python_runtime(accepted) == digest
    assert (accepted / "python.exe").is_file()
    assert "import site" in (accepted / "python314._pth").read_text()


def test_node_runtime_requires_reviewed_and_downloaded_checksums(tmp_path, monkeypatch):
    archive = tmp_path / "node.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("node/node.exe", b"synthetic runtime")
    data = archive.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    def download(url, path):
        if url == windows.NODE_ARCHIVE_URL:
            path.write_bytes(data)
        else:
            path.write_text(f"{digest}  {windows.NODE_ARCHIVE}\n")

    monkeypatch.setattr(windows, "_download", download)
    rejected = tmp_path / "rejected"
    with pytest.raises(windows.ReleaseContractError, match="checksum verification failed"):
        windows.install_node_runtime(rejected)
    assert not rejected.exists()
    monkeypatch.setattr(windows, "NODE_ARCHIVE_SHA256", digest)
    accepted = tmp_path / "accepted"
    assert windows.install_node_runtime(accepted) == digest
    assert (accepted / "node.exe").is_file()


def test_snmp_decoder_security_patch_is_aligned_in_all_locks():
    lock = tomllib.loads((ROOT / "source/uv.lock").read_text())
    packages = {item["name"]: item for item in lock["package"]}
    assert packages["pyasn1"]["version"] == "0.6.5"
    for name in ("requirements.lock.txt", "requirements-windows-x64.lock.txt", "requirements-dev.lock.txt"):
        exported = (ROOT / "source" / name).read_text()
        assert "pyasn1==0.6.5 \\\n    --hash=sha256:" in exported
        assert "pyasn1==0.6.4" not in exported
