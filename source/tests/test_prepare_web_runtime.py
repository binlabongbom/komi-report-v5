from __future__ import annotations

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
