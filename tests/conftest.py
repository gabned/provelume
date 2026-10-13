import pytest

from provelume.shell_settings import ShellSettingsManager, default_settings


@pytest.fixture(params=["current", "preview"])
def shell_mode_settings(tmp_path, request):
    """Exercise retained Current contracts and the qualified Cura default separately."""
    path = tmp_path / "synthetic-launcher.json"
    manager = ShellSettingsManager(path, default_settings())
    manager.set_interface_mode(request.param, expected_revision=0)
    return request.param, path
