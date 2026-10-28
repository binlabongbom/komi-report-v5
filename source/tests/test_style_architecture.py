"""Contracts for the centralized presentation layer."""
import ast
import importlib
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

import config
from ui.styles import buttons, inputs, reports, text, tokens
from ui.styles.application import build_qss


def test_compatibility_exports_share_the_same_implementations():
    from ui.button_system import ButtonSystem
    from ui.styles.typography import fnt as central_font
    from ui_consistency import ButtonSystem as compatibility_button_system
    from widgets import fnt

    assert config.build_qss is build_qss
    assert fnt is central_font
    assert ButtonSystem is compatibility_button_system
    assert config.SLOT_COLORS is tokens.SLOT_COLORS


def test_theme_preview_edits_the_authoritative_token_file(monkeypatch):
    from tools import preview_colors

    assert preview_colors.CONFIG_PATH.resolve() == Path(tokens.__file__).resolve()
    monkeypatch.setattr(tokens, 'C_BG', '#123456')
    assert '#123456' in build_qss()
    assert preview_colors.build_qss() == build_qss()


@pytest.mark.parametrize('old, new', [
    ('color:#52677D;', text.label('#52677D')),
    ('color:#334155;font-weight:700;border:none;background:transparent;',
     text.label('#334155', font_weight='700', border='none', background='transparent')),
    ('background:#EEF6F9;color:#245268;padding:8px 10px;',
     text.label('#245268', background='#EEF6F9', padding='8px 10px')),
    ('color:#B42318;font-weight:700;border:none;',
     text.label('#B42318', font_weight='700', border='none')),
    ('color:#64748B;font-size:11px;', text.label('#64748B', font_size='11px')),
])
def test_shared_label_rules_render_identically(old, new):
    app = QApplication.instance() or QApplication([])
    images = []
    for style in (old, new):
        label = QLabel('Printer / 123,456')
        label.resize(300, 50)
        label.setStyleSheet(style)
        label.show()
        app.processEvents()
        images.append(label.grab().toImage())
        label.close()
    assert images[0] == images[1]


def test_component_variants_preserve_their_distinct_states():
    normal = buttons.dialog_action()
    assert 'padding: 8px 18px' in normal
    assert 'padding: 7px 16px' in buttons.dialog_action(compact=True)
    assert buttons.dialog_action(pressed=True).startswith(normal)
    assert 'QPushButton:pressed' not in normal
    assert 'QPushButton:pressed' in buttons.dialog_action(pressed=True)
    assert 'color: #999999' not in inputs.legend_checkbox('#123456')
    assert 'color: #999999' in inputs.legend_checkbox('#123456', muted=True)
    assert 'background: #123456' in inputs.legend_checkbox('#123456')
    assert 'cloud_panel_title{font-size:13px;}' in reports.density_qss(True)
    assert 'cloud_panel_title{font-size:15px;}' in reports.density_qss(False)


def test_style_modules_do_not_depend_on_pages_services_or_storage():
    folder = Path(tokens.__file__).parent
    forbidden = {'config', 'database', 'services', 'pages', 'v5_pages', 'app', 'widgets'}
    for path in folder.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if isinstance(node, ast.Import):
                names = [entry.name for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            assert not forbidden.intersection(name.split('.')[0] for name in names), path.name
            if path.name != 'typography.py':
                assert not any(name.startswith('PyQt6') for name in names), path.name


def runtime_source_files(root):
    """Scan application code, not installed packages in a local virtualenv."""
    for directory, children, files in os.walk(root):
        folder = Path(directory)
        children[:] = [name for name in children
                       if name not in {'tests', 'tools', 'styles'}
                       and not (folder / name / 'pyvenv.cfg').is_file()]
        for name in files:
            if name.endswith('.py'):
                yield folder / name


def test_runtime_source_scan_excludes_virtualenv_but_keeps_application_files(tmp_path):
    environment = tmp_path / '.venv'
    environment.mkdir()
    (environment / 'pyvenv.cfg').write_text('home = synthetic\n')
    (environment / 'third_party.py').write_text('widget.setStyleSheet("external")\n')
    app = tmp_path / 'app.py'
    app.write_text('widget.setStyleSheet("application")\n')
    assert list(runtime_source_files(tmp_path)) == [app]


def test_runtime_pages_do_not_duplicate_inline_styles():
    root = Path(tokens.__file__).parents[2]
    for path in runtime_source_files(root):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'setStyleSheet' and node.args):
                continue
            value = node.args[0]
            if not isinstance(value, (ast.Constant, ast.JoinedStr)):
                continue
            if isinstance(value, ast.Constant) and value.value == '':
                continue  # Removing an override is not a style definition.
            pytest.fail(f'Inline stylesheet must live in ui/styles: {path}:{node.lineno}')


def test_all_runtime_style_references_resolve():
    root = Path(tokens.__file__).parents[2]
    for path in runtime_source_files(root):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'ui.styles':
                for entry in node.names:
                    aliases[entry.asname or entry.name] = importlib.import_module('ui.styles.' + entry.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                assert hasattr(aliases[node.value.id], node.attr), f'{path}:{node.lineno}: {ast.unparse(node)}'
