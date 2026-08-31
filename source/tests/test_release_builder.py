from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pytest

from komi_version import APP_VERSION
from tools.build_local_release import (
    EXCLUDED_PARTS,
    PROJECT_ROOT,
    SOURCE_ARCHIVE_IDENTITY_NAME,
    SOURCE_COMMIT_NAME,
    SourceArchiveIdentityError,
    _included_files,
    assert_extracted_source_archive_identity,
    build_source_archive,
    build_source_archive_identity,
)
from tools.build_macos_customer import packaged_runtime_dependency_roots
from tools.build_windows_rc import source_identity
from tools.package_windows_test_kit import (
    SETUP_CMD,
    START_CMD,
    START_DEBUG_CMD,
    build_kit,
)
from tools.release_safety import (
    FORBIDDEN_SUFFIXES,
    ReleaseSafetyError,
    assert_release_safe,
    assert_zip_safe,
    git_identity,
)


def test_source_release_excludes_runtime_data_dependencies_and_secrets():
    files = _included_files()
    relative_paths = [path.relative_to(PROJECT_ROOT).as_posix() for path in files]

    assert files
    assert any(path.name == "RELEASE_RUNBOOK.md" for path in files)
    assert any(path.name == "KOMI_Report_V5.iss" for path in files)
    for path in files:
        assert not any(part in EXCLUDED_PARTS for part in path.parts)
        assert not path.name.startswith(".env")
        assert path.suffix.casefold() not in {
            ".csv",
            ".db",
            ".key",
            ".komilicense",
            ".komirequest",
            ".log",
            ".p12",
            ".pem",
            ".sqlite",
            ".sqlite3",
            ".xls",
            ".xlsx",
        }
    assert all("node_modules" not in relative for relative in relative_paths)
    assert "web/app/status.css" not in relative_paths
    assert "web/next-env.d.ts" not in relative_paths
    assert "source/overview-v2-preview.png" not in relative_paths
    assert not any(relative.startswith(("outputs/", "exports/")) for relative in relative_paths)
    assert "source/komi-billing-audit-2026-08-21.csv" not in relative_paths
    assert not any(
        path.suffix.casefold() in {".komirequest", ".komilicense"}
        for path in files
    )

    ignore_rules = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.komirequest" in ignore_rules
    assert "*.komilicense" in ignore_rules


@pytest.mark.parametrize("suffix", [".komirequest", ".komilicense"])
def test_offline_license_files_fail_closed_and_are_excluded(tmp_path, suffix):
    offline_file = tmp_path / f"customer{suffix}"
    offline_file.write_text("opaque-offline-artifact\n", encoding="utf-8")

    with pytest.raises(ReleaseSafetyError) as error:
        assert_release_safe([offline_file], root=tmp_path)

    assert suffix in FORBIDDEN_SUFFIXES
    assert [(item.category, item.path) for item in error.value.findings] == [
        ("forbidden-file-type", offline_file.name)
    ]


@pytest.mark.parametrize("suffix", [".komirequest", ".komilicense"])
def test_offline_license_files_make_release_archives_fail_closed(tmp_path, suffix):
    archive = tmp_path / "customer-release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(f"runtime/customer{suffix}", "opaque-offline-artifact\n")

    with pytest.raises(ReleaseSafetyError) as error:
        assert_zip_safe(archive)

    assert [(item.category, item.path) for item in error.value.findings] == [
        ("forbidden-file-type", f"runtime/customer{suffix}")
    ]


def test_macos_zip_allows_only_its_exact_packaged_web_runtime_dependencies(tmp_path):
    archive = tmp_path / "macos-customer.zip"
    app_bundle = tmp_path / "KOMI Report V5.2.1.app"
    roots = packaged_runtime_dependency_roots(app_bundle)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            f"{app_bundle.name}/Contents/Resources/web-runtime-seed/.next/server/app.js",
            "export const runtime = true;\n",
        )
        zipped.writestr(
            f"{app_bundle.name}/Contents/Frameworks/web-runtime-seed/node_modules/next/index.js",
            "export const next = true;\n",
        )
        zipped.writestr(
            f"{app_bundle.name}/Contents/Resources/web-runtime-seed/"
            ".next/static/chunks/next/dist/build/credential-management.js",
            "export const browserFeature = true;\n",
        )
        zipped.writestr(
            f"__MACOSX/{app_bundle.name}/Contents/Resources/web-runtime-seed/"
            "node_modules/next/._index.js",
            "resource fork metadata\n",
        )
        zipped.writestr(
            f"{app_bundle.name}/Contents/Resources/web-runtime-seed/"
            "node_modules/next/dist/compiled/jsonwebtoken/",
            b"",
        )
        zipped.writestr(
            f"__MACOSX/{app_bundle.name}/Contents/Resources/web-runtime-seed/"
            "node_modules/next/dist/compiled/._jsonwebtoken",
            b"directory resource fork metadata",
        )

    with pytest.raises(ReleaseSafetyError, match="forbidden-path"):
        assert_zip_safe(archive)
    assert_zip_safe(archive, allowed_packaged_dependency_roots=roots)


def test_macos_zip_rejects_node_dependencies_outside_exact_runtime_root(tmp_path):
    archive = tmp_path / "macos-customer.zip"
    app_bundle = tmp_path / "KOMI Report V5.2.1.app"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(
            f"{app_bundle.name}/Contents/Resources/other/node_modules/next/index.js",
            "export const unexpected = true;\n",
        )

    with pytest.raises(ReleaseSafetyError, match="forbidden-path"):
        assert_zip_safe(
            archive,
            allowed_packaged_dependency_roots=packaged_runtime_dependency_roots(app_bundle),
        )


@pytest.mark.parametrize(
    ("relative_path", "content", "expected_category"),
    [
        ("node_modules/next/customer.db", b"sqlite-like", "forbidden-file-type"),
        ("node_modules/next/logs/runtime.txt", b"log", "forbidden-path"),
        ("node_modules/next/customer-data/export.txt", b"customer", "forbidden-path"),
        ("node_modules/next/.env", b"SETTING=value", "credential-file"),
        ("node_modules/next/credentials.json", b"{}", "credential-file"),
        (
            "node_modules/next/server.js",
            ("token=" + "gh" + "p_" + ("A" * 32)).encode(),
            "github-token",
        ),
    ],
)
def test_macos_runtime_allowance_never_waives_sensitive_content(
    tmp_path,
    relative_path,
    content,
    expected_category,
):
    archive = tmp_path / "macos-customer.zip"
    app_bundle = tmp_path / "KOMI Report V5.2.1.app"
    runtime_root = (
        f"{app_bundle.name}/Contents/Resources/web-runtime-seed/{relative_path}"
    )
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(runtime_root, content)

    with pytest.raises(ReleaseSafetyError) as error:
        assert_zip_safe(
            archive,
            allowed_packaged_dependency_roots=packaged_runtime_dependency_roots(app_bundle),
        )

    assert expected_category in {finding.category for finding in error.value.findings}


def test_git_identity_marks_untracked_files_dirty(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Test"],
        cwd=repository,
        check=True,
    )
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repository, check=True)

    _commit, source_state = git_identity(repository)
    assert source_state == "clean"

    (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    _commit, source_state = git_identity(repository)
    assert source_state == "dirty"


def _initialize_git_repository(repository):
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Test"],
        cwd=repository,
        check=True,
    )
    source_file = repository / "source" / "runtime.py"
    source_file.parent.mkdir()
    source_file.write_text("VALUE = 'clean-source'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "release source"], cwd=repository, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source_file, commit


def _configure_source_builder(monkeypatch, repository, release_dir):
    monkeypatch.setattr("tools.build_local_release.PROJECT_ROOT", repository)
    monkeypatch.setattr(
        "tools.build_local_release.INCLUDE_ROOTS",
        (repository / "source",),
    )
    monkeypatch.setattr("tools.build_local_release.RELEASE_DIR", release_dir)
    monkeypatch.setattr(
        "tools.build_local_release.assert_v5_2_version_alignment",
        lambda: None,
    )


def _write_extracted_identity(repository, extracted):
    source_file = repository / "source" / "runtime.py"
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    identity = build_source_archive_identity(
        [source_file],
        project_root=repository,
        commit=commit,
    )
    extracted_file = extracted / "source" / "runtime.py"
    extracted_file.parent.mkdir(parents=True)
    shutil.copy2(source_file, extracted_file)
    (extracted / SOURCE_COMMIT_NAME).write_text(commit + "\n", encoding="ascii")
    (extracted / SOURCE_ARCHIVE_IDENTITY_NAME).write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return extracted_file, commit


def test_release_safety_gate_proves_forbidden_file_and_secret_failures(tmp_path):
    export = tmp_path / "outputs" / "customer-report.csv"
    export.parent.mkdir()
    export.write_text("customer,data\n", encoding="utf-8")
    with pytest.raises(ReleaseSafetyError) as forbidden_error:
        assert_release_safe([export], root=tmp_path)
    assert {item.category for item in forbidden_error.value.findings} >= {
        "forbidden-path",
        "forbidden-file-type",
    }

    secret = tmp_path / "safe" / "settings.txt"
    secret.parent.mkdir()
    fake_token = "gh" + "p_" + ("A" * 32)
    secret.write_text(f"token={fake_token}\n", encoding="utf-8")
    with pytest.raises(ReleaseSafetyError) as secret_error:
        assert_release_safe([secret], root=tmp_path)
    assert [item.category for item in secret_error.value.findings] == ["github-token"]


def test_release_versions_are_aligned_to_5_2_1():
    expected = APP_VERSION
    config_text = (PROJECT_ROOT / "source" / "config.py").read_text(encoding="utf-8")
    spec_text = (PROJECT_ROOT / "source" / "app.spec").read_text(encoding="utf-8")
    project = tomllib.loads(
        (PROJECT_ROOT / "source" / "pyproject.toml").read_text(encoding="utf-8")
    )
    web_package = json.loads(
        (PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    web_lock = json.loads(
        (PROJECT_ROOT / "web" / "package-lock.json").read_text(encoding="utf-8")
    )

    assert "APP_VER   = APP_VERSION" in config_text
    assert "PACKAGE_VERSION = APP_VERSION" in config_text
    assert project["project"]["version"] == expected
    assert web_package["version"] == expected
    assert web_lock["version"] == expected
    assert web_lock["packages"][""]["version"] == expected
    assert f'CFBundleShortVersionString": "{expected}"' in spec_text
    assert 'CFBundleVersion": "50201"' in spec_text
    assert "KOMI Report V5.1.app" not in spec_text


def test_source_release_manifest_contains_traceability_fields(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    _initialize_git_repository(repository)
    release_dir = tmp_path / "release-output"
    _configure_source_builder(monkeypatch, repository, release_dir)

    archive, digest, count = build_source_archive()
    manifest = json.loads((release_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(archive) as packaged:
        names = set(packaged.namelist())
        archive_identity = json.loads(packaged.read(SOURCE_ARCHIVE_IDENTITY_NAME))

    assert count > 0
    assert count == manifest["file_count"]
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["version"] == APP_VERSION
    assert manifest["contract_version"] == "v5.2-shared-2026-08-25-r2"
    assert manifest["contract_sha256"] == "4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd"
    assert manifest["artifact"] == archive.name
    assert manifest["artifact_identity"].startswith(
        f"komi-report-v5-source-{APP_VERSION}-"
    )
    assert manifest["git_commit"]
    assert manifest["source_state"] in {"clean", "dirty", "uncommitted"}
    assert manifest["source_state"] == "clean"
    assert manifest["source_git_tree"] == archive_identity["git_tree"]
    assert manifest["source_archive_tree_sha256"] == archive_identity["archive_tree_sha256"]
    assert names == {
        "source/runtime.py",
        SOURCE_COMMIT_NAME,
        SOURCE_ARCHIVE_IDENTITY_NAME,
    }
    assert manifest["build_time"]
    assert manifest["sha256"] == digest


@pytest.mark.parametrize("dirty_kind", ["modified", "staged", "untracked"])
def test_source_release_rejects_any_dirty_git_state(tmp_path, monkeypatch, dirty_kind):
    repository = tmp_path / "repository"
    source_file, _commit = _initialize_git_repository(repository)
    _configure_source_builder(monkeypatch, repository, tmp_path / "release-output")
    if dirty_kind in {"modified", "staged"}:
        source_file.write_text("VALUE = 'modified'\n", encoding="utf-8")
        if dirty_kind == "staged":
            subprocess.run(["git", "add", "source/runtime.py"], cwd=repository, check=True)
    else:
        (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(SourceArchiveIdentityError, match="clean Git tree"):
        build_source_archive()


def test_extracted_source_identity_accepts_exact_archive_and_build_dependencies(tmp_path):
    repository = tmp_path / "repository"
    _initialize_git_repository(repository)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    _file, commit = _write_extracted_identity(repository, extracted)
    cache = extracted / "source" / "__pycache__" / "runtime.cpython-311.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated cache")
    (extracted / "source" / ".venv" / "Scripts").mkdir(parents=True)
    (extracted / "source" / ".venv" / "Scripts" / "python.exe").write_bytes(
        b"build interpreter"
    )
    node_module = extracted / "web" / "node_modules" / "next" / "package.json"
    node_module.parent.mkdir(parents=True)
    node_module.write_text('{"name":"next"}\n', encoding="utf-8")

    identity = assert_extracted_source_archive_identity(extracted)

    assert identity["git_commit"] == commit


def test_windows_builder_accepts_only_verified_extracted_archive(
    tmp_path,
    monkeypatch,
):
    repository = tmp_path / "repository"
    _initialize_git_repository(repository)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    extracted_file, commit = _write_extracted_identity(repository, extracted)
    monkeypatch.setattr("tools.build_windows_rc.PROJECT_ROOT", extracted)

    assert source_identity(commit) == (commit, "archive-clean")
    with pytest.raises(RuntimeError, match="does not match"):
        source_identity("b" * 40)

    extracted_file.write_text("VALUE = 'tampered'\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity verification failed"):
        source_identity(commit)


@pytest.mark.parametrize("tamper_kind", ["modified", "missing", "injected"])
def test_extracted_source_identity_rejects_content_tampering(tmp_path, tamper_kind):
    repository = tmp_path / "repository"
    _initialize_git_repository(repository)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    extracted_file, _commit = _write_extracted_identity(repository, extracted)
    if tamper_kind == "modified":
        extracted_file.write_text("VALUE = 'tampered'\n", encoding="utf-8")
    elif tamper_kind == "missing":
        extracted_file.unlink()
    else:
        (extracted / "source" / "injected.py").write_text(
            "VALUE = 'injected'\n",
            encoding="utf-8",
        )

    with pytest.raises(SourceArchiveIdentityError, match="archive identity"):
        assert_extracted_source_archive_identity(extracted)


def test_release_builder_uses_semantic_version_bumps():
    from build import bump

    assert bump("5.1.0", "patch") == "5.1.1"
    assert bump("5.1.0", "minor") == "5.2.0"
    assert bump("5.1.0", "major") == "6.0.0"


def test_macos_bundle_disables_runtime_bytecode_writes():
    spec = (PROJECT_ROOT / "source" / "app.spec").read_text(encoding="utf-8")
    hook = PROJECT_ROOT / "source" / "runtime_hooks" / "no_bytecode.py"

    assert "runtime_hooks=['runtime_hooks/no_bytecode.py']" in spec
    assert "'distutils'" not in spec
    assert "FORBIDDEN_SUFFIXES" in spec
    assert "a.datas = [" in spec
    assert "sys.dont_write_bytecode = True" in hook.read_text(encoding="utf-8")


def test_macos_archive_keeps_secret_scanning_enabled():
    packager = (PROJECT_ROOT / "source" / "tools" / "package_macos_release.py").read_text(
        encoding="utf-8"
    )

    assert "assert_zip_safe(ARCHIVE)" in packager
    assert "scan_secrets=False" not in packager


def test_windows_portable_launchers_support_unc_redirected_folders():
    for launcher in (SETUP_CMD, START_CMD, START_DEBUG_CMD):
        assert 'pushd "%~dp0"' in launcher
        assert 'cd /d "%~dp0"' not in launcher
        assert "popd" in launcher

    assert 'set "KOMI_LAUNCH_DIR=%~dp0"' in START_CMD
    assert 'if "%KOMI_LAUNCH_DIR:~0,2%"=="\\\\"' in START_CMD
    assert 'start "" /wait "runtime\\pythonw.exe" "app.py"' in START_CMD


def test_windows_portable_build_removes_macos_metadata(tmp_path, monkeypatch):
    def fake_runtime(destination):
        destination.mkdir(parents=True)
        (destination / "python.exe").write_bytes(b"runtime")
        (destination / ".DS_Store").write_bytes(b"metadata")
        return "runtime-sha"

    def fake_wheelhouse(destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "dependency.whl").write_bytes(b"wheel")

    def fake_install(_wheelhouse, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "._dependency.py").write_bytes(b"metadata")
        (destination / "dependency.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "tools.package_windows_test_kit.download_python_runtime", fake_runtime
    )
    monkeypatch.setattr(
        "tools.package_windows_test_kit.download_wheelhouse", fake_wheelhouse
    )
    monkeypatch.setattr(
        "tools.package_windows_test_kit.install_windows_dependencies", fake_install
    )

    kit_root, _archive, manifest = build_kit(tmp_path)

    assert manifest["file_count"] > 0
    assert not list(kit_root.rglob(".DS_Store"))
    assert not [path for path in kit_root.rglob("*") if path.name.startswith("._")]
    for required in (
        "i18n.py",
        "migrations.py",
        "observability.py",
        "runtime_config.py",
        "ui_consistency.py",
        "requirements.lock.txt",
        "requirements-windows-x64.lock.txt",
        "ui/cloud_reports.py",
        "ui/common_dialogs.py",
        "tools/db_recovery.py",
    ):
        assert (kit_root / required).is_file()

    environment = os.environ.copy()
    environment.update(
        {
            "KOMI_APP_HOME": str(tmp_path / "runtime-home"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(kit_root),
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    subprocess.run(
        [sys.executable, "-c", "import app; import web_api"],
        cwd=kit_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
