import json

import pytest

from tools import build_macos_customer as builder


@pytest.mark.parametrize("edition", ["normal", "offline"])
def test_receipt_rejects_wrong_source_edition_and_changed_binary(tmp_path, monkeypatch, edition):
    bundle = tmp_path / "app.app"
    executable = bundle / "Contents" / "MacOS" / builder.APP_NAME
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture executable")
    (bundle / "Contents" / "Info.plist").write_bytes(b"fixture")
    monkeypatch.setattr(builder, "frozen_edition", lambda _: edition)
    receipt = {"edition": edition, "source_commit": "a" * 40,
               "executable_sha256": builder.sha256_file(executable)}
    receipt_path = tmp_path / "BUILD_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt))
    builder.verify_build_receipt(bundle, edition, "a" * 40)
    with pytest.raises(builder.MacCustomerBuildError):
        builder.verify_build_receipt(bundle, edition, "b" * 40)
    with pytest.raises(builder.MacCustomerBuildError):
        builder.verify_build_receipt(bundle, "offline" if edition == "normal" else "normal", "a" * 40)
    executable.write_bytes(b"replaced executable")
    with pytest.raises(builder.MacCustomerBuildError):
        builder.verify_build_receipt(bundle, edition, "a" * 40)


def test_receipt_alone_cannot_override_actual_frozen_edition(tmp_path, monkeypatch):
    bundle = tmp_path / "app.app"
    executable = bundle / "Contents" / "MacOS" / builder.APP_NAME
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    (bundle / "Contents" / "Info.plist").write_bytes(b"fixture")
    (tmp_path / "BUILD_RECEIPT.json").write_text(json.dumps({
        "edition": "offline", "source_commit": "a" * 40,
        "executable_sha256": builder.sha256_file(executable),
    }))
    monkeypatch.setattr(builder, "frozen_edition", lambda _: "normal")
    with pytest.raises(builder.MacCustomerBuildError):
        builder.verify_build_receipt(bundle, "offline", "a" * 40)


@pytest.mark.parametrize("edition", ["normal", "offline"])
def test_frozen_edition_reads_code_without_executing_it(tmp_path, monkeypatch, edition):
    import PyInstaller.archive.readers

    class Archive:
        def __init__(self, path):
            pass

        def open_embedded_archive(self, name):
            return self

        def extract(self, name):
            return compile(f'BUILD_EDITION = "{edition}"\nraise RuntimeError("must not execute")', "fixture", "exec")

    monkeypatch.setattr(PyInstaller.archive.readers, "CArchiveReader", Archive)
    monkeypatch.setattr(builder, "_main_executable", lambda _: tmp_path)
    assert builder.frozen_edition(tmp_path) == edition


def test_edition_build_paths_do_not_overlap():
    assert builder.edition_bundle("normal") != builder.edition_bundle("offline")
    with pytest.raises(builder.MacCustomerBuildError):
        builder.edition_bundle("invalid")
