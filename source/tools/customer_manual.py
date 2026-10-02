"""Copy the maintained manual files; never builds an application or installer."""
from pathlib import Path
import shutil

from komi_version import APP_VERSION


def copy_updated_manual(project_root, destination):
    source = Path(project_root) / 'docs'
    destination = Path(destination)
    names = (f'CUSTOMER_GUIDE_V{APP_VERSION.replace(".", "_")}_DRAFT.md',
             f'customer-guide/KOMI_Report_{APP_VERSION}_Source_Guide.pdf',
             f'customer-guide/assets-v{APP_VERSION}-source')
    for name in names:
        if not (source / name).exists():
            raise FileNotFoundError(f'Updated customer guide is missing: {name}')
    for name in names:
        src, target = source / name, destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
