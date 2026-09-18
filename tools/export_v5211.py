"""Export the tested commit without weakening clean-source identity checks."""
from __future__ import annotations
import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'd08fc0b1841323c2aedc3a86acb145a66fe3f64c'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main() -> None:
    commit = os.environ['SOURCE_COMMIT']
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise RuntimeError('Tested commit differs from current checkout')
    out = Path(os.environ['RUNNER_TEMP']) / 'v5211-evidence'
    out.mkdir(parents=True, exist_ok=True)
    # Record generated filenames only; never upload arbitrary test/customer data.
    (out / 'POST_TEST_GIT_STATUS.txt').write_bytes(git('status', '--porcelain'))
    with tempfile.TemporaryDirectory(prefix='komi-v5211-export-') as temporary:
        clean = Path(temporary) / 'source'
        subprocess.run(['git', 'worktree', 'add', '--detach', str(clean), commit], cwd=ROOT, check=True)
        try:
            environment = dict(os.environ, PYTHONPATH=str(clean / 'source'))
            subprocess.run([sys.executable, str(clean / 'source/tools/build_local_release.py')], cwd=clean, env=environment, check=True)
            archive = clean / 'release/KOMI_Report_V5_2_11_Source.zip'
            with zipfile.ZipFile(archive) as z:
                identity_bytes = z.read('SOURCE_ARCHIVE_IDENTITY.json')
                identity = json.loads(identity_bytes)
            if identity['git_commit'] != commit:
                raise RuntimeError('Archive identity does not match tested commit')
            changed = set(git('diff', '--name-only', BASE, commit).decode('utf-8').splitlines())
            allowed = {row['path'] for row in identity['files']}
            paths = sorted(allowed.intersection(changed))
            deleted = git('diff', '--name-only', '--diff-filter=D', BASE, commit).decode('utf-8').splitlines()
            patch = git('diff', '--binary', '--full-index', BASE, commit, '--', *paths)
            compact = {key: value for key, value in identity.items() if key != 'files'}
            compact['file_changes'] = [row for row in identity['files'] if row['path'] in paths]
            compact['deleted_paths'] = deleted
            compact['file_order'] = [row['path'] for row in identity['files']]
            compressed = gzip.compress(patch, mtime=0)
            identity_gz = gzip.compress(json.dumps(compact, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), mtime=0)
            (out / 'source-delta.patch.gz.b64').write_text(base64.b64encode(compressed).decode('ascii'), encoding='ascii')
            (out / 'source-identity.json.gz.b64').write_text(base64.b64encode(identity_gz).decode('ascii'), encoding='ascii')
            (out / 'SOURCE_ARCHIVE_IDENTITY.json').write_bytes(identity_bytes)
            (out / 'SOURCE_COMMIT.txt').write_text(commit + '\n', encoding='ascii')
            (out / 'SOURCE_VALIDATION.json').write_text(json.dumps({'version':'5.2.11','source_commit':commit,'tests_passed':True,'base_commit':BASE,'base_asset_id':549774280,'base_archive_sha256':'ca07302283dbdc260b33858902a798ab0805f7d59338cad969b0ebb336358805','delta_sha256':sha(patch),'delta_gzip_sha256':sha(compressed),'identity_gzip_sha256':sha(identity_gz),'source_archive_sha256':sha(archive.read_bytes()),'production_go':False}, indent=2), encoding='utf-8')
            shutil.copy2(archive, out / archive.name)
            print('SOURCE_VALIDATED', commit, 'delta', len(compressed), 'identity_delta', len(identity_gz))
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(clean)], cwd=ROOT, check=True)

if __name__ == '__main__':
    main()
