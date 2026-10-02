from dataclasses import replace

import pytest

from provelume.shell_settings import ShellSettingsManager, default_settings


@pytest.fixture(params=["current", "preview"])
def shell_mode_settings(tmp_path, request):
    """Exercise retained Current contracts and the qualified Cura default separately."""
    path = tmp_path / "synthetic-launcher.json"
    ShellSettingsManager(path, default_settings()).save(
        replace(default_settings(), interface_mode=request.param)
    )
    return request.param, path
