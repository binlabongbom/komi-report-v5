from __future__ import annotations

import pytest

from services.web_access import update_web_runtime_values
from services.web_port import read_web_port, validate_web_port


@pytest.mark.parametrize("value", [0, 1023, 65536, 3001, 8766, "abc", "3443.0", "", True, "３４４３"])
def test_web_port_rejects_invalid_and_internal_ports(value):
    with pytest.raises(ValueError):
        validate_web_port(value)


def test_web_port_defaults_and_reads_persisted_custom_port(tmp_path):
    path = tmp_path / ".env.local"
    assert read_web_port(path) == 3000
    update_web_runtime_values(path, {"KOMI_WEB_PORT": "3443"})
    assert read_web_port(path) == 3443
    assert validate_web_port(" 65535 ") == 65535
