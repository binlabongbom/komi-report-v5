from pathlib import Path

FILES = [
    'source/pyproject.toml',
    'web/package.json',
    'web/package-lock.json',
    'source/app.spec',
    'source/uv.lock',
    'packaging/windows/KOMI_Report_V5.iss',
    'docs/RELEASE_SUPPORT_AND_RECOVERY.md',
    'docs/CUSTOMER_RELEASE_NOTES.md',
    'docs/PILOT_RELEASE_CHECKLIST.md',
    'docs/RELEASE_RUNBOOK.md',
    'docs/CUSTOMER_INSTALL_GUIDE.md',
    'docs/CUSTOMER_GUIDE_V5_2.md',
]

for name in FILES:
    path = Path(name)
    text = path.read_text(encoding='utf-8')
    text = text.replace('5.2.5', '5.2.6').replace('V5_2_5', 'V5_2_6').replace('v5_2_5', 'v5_2_6')
    if name == 'source/app.spec':
        text = text.replace('50205', '50206')
    path.write_text(text, encoding='utf-8')
