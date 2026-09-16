"""Idempotent authoring follow-up; commits ordinary source changes in CI."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def edit(path: str, old: str, new: str) -> None:
    destination = ROOT / path
    text = destination.read_text(encoding='utf-8')
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected source: {path}')
    result = text.replace(old, new)
    if path.endswith('.py'):
        ast.parse(result, filename=path)
    destination.write_text(result, encoding='utf-8', newline='\n')


def main() -> None:
    edit('source/tests/test_release_builder.py',
         '''    assert 'CFBundleVersion": "50210"' in spec_text''',
         '''    major, minor, patch = map(int, expected.split("."))
    assert f'CFBundleVersion": "{major * 10000 + minor * 100 + patch}"' in spec_text''')
    edit('source/v5_pages.py',
         '''        try:
            runtime.set_mode("online")
            runtime.configuration_changed()''',
         '''        try:
            # Do not acquire the send lock or reset lifecycle while an Online
            # request is already running; observe its eventual result instead.
            if runtime.snapshot().get("mode") != "online":
                runtime.set_mode("online")
            runtime.configuration_changed()''')
    edit('source/services/v5_2_runtime.py',
         '''        self.state_repository = state_repository or V52RuntimeStateRepository()
        self.outbox = outbox or V52OutboxRepository()''',
         '''        self.state_repository = state_repository or V52RuntimeStateRepository()
        if is_offline_edition():
            with registration_state_lock:
                previous = self.state_repository.internal()
                if previous is not None and previous["mode"] != "offline":
                    self.state_repository.set_mode("offline", now=self.clock())
        self.outbox = outbox or V52OutboxRepository()''')
    edit('source/services/v5_2_runtime.py',
         '''        eligible, reason = self.state_repository.usage_eligibility(now=self.clock())''',
         '''        if is_offline_edition():
            state = self.state_repository.internal()
            if state is None or state["mode"] != "offline":
                return False, "offline_license_required"
        eligible, reason = self.state_repository.usage_eligibility(now=self.clock())''')
    print('V5211_FOLLOWUP_APPLIED')

if __name__ == '__main__':
    main()
