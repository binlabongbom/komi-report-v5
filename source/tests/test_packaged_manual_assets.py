from pathlib import Path


def test_current_in_app_and_pdf_guide_share_bilingual_screenshots():
    from ui.manual_screens import manual_screen_path
    root = Path(__file__).resolve().parents[2] / "docs"
    guide = (root / "CUSTOMER_GUIDE_V5_2_12_DRAFT.md").read_text(encoding="utf-8")
    for english in (False, True):
        for index in range(1, 14):
            relative = manual_screen_path(index, english=english)
            assert relative in guide
            assert (root / relative).is_file()


def test_app_spec_does_not_bundle_customer_manual():
    source_root = Path(__file__).resolve().parents[1]
    spec = (source_root / "app.spec").read_text(encoding="utf-8")
    assert "docs/customer-guide" not in spec


def test_windows_customer_payload_does_not_bundle_manual():
    source_root = Path(__file__).resolve().parents[1]
    builder = (source_root / "tools" / "build_windows_rc.py").read_text(encoding="utf-8")
    assert "copy_updated_manual" not in builder
    assert '"customer-guide"' not in builder


def test_source_release_packages_manual_assets_for_cross_platform_builds():
    source_root = Path(__file__).resolve().parents[1]
    builder = (source_root / "tools" / "build_local_release.py").read_text(
        encoding="utf-8"
    )

    assert 'PROJECT_ROOT / "docs" / "customer-guide" / "assets-v5.2"' in builder


def test_updated_guide_links_remain_available_after_copy(tmp_path):
    from tools.customer_manual import copy_updated_manual
    from komi_version import APP_VERSION
    source_root = Path(__file__).resolve().parents[1]
    copy_updated_manual(source_root.parent, tmp_path)
    assert (tmp_path/'customer-guide'/f'KOMI_Report_{APP_VERSION}_Source_Guide.pdf').read_bytes().startswith(b'%PDF-')
    guide = tmp_path/f'CUSTOMER_GUIDE_V{APP_VERSION.replace(".", "_")}_DRAFT.md'
    import re
    images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', guide.read_text(encoding='utf-8'))
    assert images and all((tmp_path/image).is_file() for image in images)
