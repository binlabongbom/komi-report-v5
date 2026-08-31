from __future__ import annotations

from tools import prepare_web_runtime
from tools.prepare_web_runtime import source_hash, sync_web_source


def test_sync_web_source_preserves_generated_runtime_and_excludes_shared_secret(tmp_path):
    source = tmp_path / "web-source"
    runtime = tmp_path / "web-runtime"
    (source / "app").mkdir(parents=True)
    (source / "app" / "page.tsx").write_text("export default 1\n", encoding="utf-8")
    (source / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (source / ".env.local").write_text("SECRET=shared\n", encoding="utf-8")
    (source / ".next").mkdir()
    (source / ".next" / "BUILD_ID").write_text("source-build\n", encoding="utf-8")

    (runtime / "node_modules").mkdir(parents=True)
    (runtime / "node_modules" / "keep.js").write_text("keep\n", encoding="utf-8")
    (runtime / ".next").mkdir()
    (runtime / ".next" / "BUILD_ID").write_text("runtime-build\n", encoding="utf-8")
    (runtime / ".env.local").write_text("SECRET=local\n", encoding="utf-8")

    copied = sync_web_source(source, runtime)

    assert copied == ("app/page.tsx", "package-lock.json")
    assert (runtime / "node_modules" / "keep.js").is_file()
    assert (runtime / ".next" / "BUILD_ID").read_text(encoding="utf-8") == "runtime-build\n"
    assert (runtime / ".env.local").read_text(encoding="utf-8") == "SECRET=local\n"
    assert len(source_hash(source)) == 64


def test_prepare_prebuilt_runtime_does_not_require_npm(tmp_path, monkeypatch):
    source = tmp_path / "web-source"
    runtime = tmp_path / "web-runtime"
    source.mkdir()
    runtime.mkdir()
    (source / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (source / "page.tsx").write_text("export default 1\n", encoding="utf-8")
    (runtime / "node_modules").mkdir()
    (runtime / ".next").mkdir()
    (runtime / ".next" / "BUILD_ID").write_text("prebuilt\n", encoding="utf-8")
    (runtime / prepare_web_runtime.DEPENDENCY_STAMP).write_text(
        prepare_web_runtime._sha256(source / "package-lock.json") + "\n",
        encoding="utf-8",
    )
    (runtime / prepare_web_runtime.BUILD_STAMP).write_text(
        source_hash(source) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        prepare_web_runtime,
        "ensure_web_access",
        lambda *_args, **_kwargs: {"KOMI_WEB_USER": "admin"},
    )
    monkeypatch.setattr(prepare_web_runtime, "read_web_runtime_values", lambda *_args: {})
    monkeypatch.setattr(
        prepare_web_runtime,
        "resolve_lan_tls",
        lambda *_args, **_kwargs: type(
            "Material",
            (),
            {
                "source": "generated-local",
                "certificate_path": tmp_path / "cert.pem",
                "private_key_path": tmp_path / "key.pem",
                "fingerprint_sha256": "a" * 64,
            },
        )(),
    )
    monkeypatch.setattr(prepare_web_runtime, "update_web_runtime_values", lambda *_args: None)
    monkeypatch.setattr(
        prepare_web_runtime,
        "_npm_command",
        lambda: (_ for _ in ()).throw(AssertionError("npm must not be required")),
    )

    prepare_web_runtime.prepare(source, runtime)
