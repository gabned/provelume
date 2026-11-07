"""S09 cross-layer journey, with external networking denied before creation."""

import os
import socket

import pytest

from provelume.personal_qualification import qualify_personal
from provelume.review_effects import ReviewError


@pytest.mark.parametrize("retention", ["keep", pytest.param(
    "transit", marks=pytest.mark.skipif(os.name != "nt", reason="Native Inbox exit is Windows"))])
def test_personal_native_offline_error_recovery_and_backup(tmp_path, monkeypatch, retention):
    connect = socket.socket.connect

    def local_only(sock, address):
        if sock.family == getattr(socket, "AF_UNIX", None):
            return connect(sock, address)
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return connect(sock, address)
        pytest.fail("Personal AI-Off journey attempted external networking")

    monkeypatch.setattr(socket.socket, "connect", local_only)
    root = tmp_path / "personal"
    report = qualify_personal(root, retention=retention)
    assert report["result"] == "PASS"
    assert len(report["search_routes"]) == 70
    assert report["consultation_history"] == [True, False, True]
    assert report["backup_restore"] == "PASS"
    assert report["ocr"] == "DEFERRED_NOT_RUN"
    assert report["windows_11_pro_25h2_manual"].endswith("NOT_RUN")
    assert report["build"]["official"] is False
    with pytest.raises(ReviewError):
        qualify_personal(root, retention=retention)
