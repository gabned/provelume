"""Vault-locator admission and no ambient-token inheritance; native DPAPI is separate."""

import pytest

from provelume.mirror_contract import MirrorError
from provelume.mirror_credential_context import credential_environment


def test_windows_helper_receives_only_local_native_vault_locator():
    assert credential_environment(
        platform="nt",
        environ={
            "LOCALAPPDATA": r"C:\Synthetic\Vault",
            "SYNTHETIC_TOKEN": "never-forward",
            "DBUS_SESSION_BUS_ADDRESS": "tcp:host=example.invalid",
        },
    ) == {"LOCALAPPDATA": r"C:\Synthetic\Vault"}


@pytest.mark.parametrize("value", [None, "relative", r"\\server\share\vault", "C:\\bad\nvalue"])
def test_missing_remote_or_malformed_windows_vault_context_is_refused(value):
    with pytest.raises(MirrorError, match="credential_context"):
        credential_environment(platform="nt", environ={"LOCALAPPDATA": value})


def test_unix_helper_gets_only_local_bus_and_runtime_context():
    source = {
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/synthetic/bus,guid=synthetic",
        "XDG_RUNTIME_DIR": "/synthetic/runtime",
        "SYNTHETIC_TOKEN": "never-forward",
    }
    assert credential_environment(platform="posix", environ=source) == {
        key: source[key] for key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
    }


@pytest.mark.parametrize(
    "value", ["tcp:host=example.invalid", "unix:path=/a;tcp:host=elsewhere", "unix:path=/a\nextra"]
)
def test_remote_or_multitransport_bus_is_refused_before_helper_starts(value):
    with pytest.raises(MirrorError, match="credential_context"):
        credential_environment(platform="posix", environ={"DBUS_SESSION_BUS_ADDRESS": value})
