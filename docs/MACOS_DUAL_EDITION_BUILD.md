# macOS 5.2.12 Online / Offline

Build natively on Apple Silicon using the pinned Python requirements and Node
24.21.x / npm 12.1.x. Install both runtime and development lock files, run Web
lint/tests and `npm run build` before packaging.

From `source`, run for each edition:

```sh
KOMI_NODE_RUNTIME_BUILD_FILE=/absolute/path/to/node python -m tools.build_macos_customer \
  --edition normal --expected-source-commit FULL_COMMIT --output /absolute/output/Online
KOMI_NODE_RUNTIME_BUILD_FILE=/absolute/path/to/node python -m tools.build_macos_customer \
  --edition offline --expected-source-commit FULL_COMMIT --output /absolute/output/Offline
```

The builder requires committed, clean source. It stages `git archive` in a
temporary directory, changes only the staged immutable edition authority, and
uses separate `source/dist/<edition>` and `source/build/<edition>` paths. Source
edition remains normal. `--skip-build` verifies commit, executable checksum and
the actual edition bytecode in the frozen archive; a receipt alone cannot change
the edition. Artifact filenames include platform, architecture, version and
Online/Offline.

Packaged smoke tests use isolated HOME/config/database/logs and disable discovery.
The packaged Offline executable checks register/status/meter rejection with a
transport that fails if called, checks environment override resistance and rejects
switching runtime mode to online. This is an isolated guard test, not live Host E2E.

Both editions retain signing and joint E2E evidence gates and always produce HOLD.
Offline does not require Host Offline License public keys. Lack of Developer ID
or notarization is reported, never bypassed. Native GUI/tray and synthetic 5.2.4
upgrade results must be recorded separately before customer delivery. Never use
the customer's database as a release test fixture.
