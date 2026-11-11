import errno
import json
import subprocess

import pytest

from provelume import mirror_git_runtime as runtime
from provelume import mirror_git_windows as windows
from provelume import mirror_gitea_qualification as synthetic
from provelume import mirror_gitea_server_qualification as actual
from provelume.mirror_contract import require


@pytest.mark.parametrize("qualifier", ["actual", "synthetic", "interruption"])
@pytest.mark.parametrize("kind", ["missing", "sharing", "subprocess", "unrecognized"])
def test_git_os_context_survives_qualification_without_private_values(
    tmp_path, monkeypatch, qualifier, kind
):
    secret = "SYNTHETIC_SECRET/private/path"
    if kind == "missing":
        original = FileNotFoundError(errno.ENOENT, secret, secret)
    elif kind == "sharing":
        original = PermissionError(errno.EACCES, secret, secret)
        original.winerror = 32
    elif kind == "subprocess":
        original = subprocess.SubprocessError(secret)
    else:
        original = OSError(secret)
        original.errno = [secret]
        original.winerror = secret

    def fail_start(*_args, **_kwargs):
        raise original

    session = runtime.GitSession(tmp_path)
    monkeypatch.setattr(runtime.subprocess, "Popen", fail_start)
    monkeypatch.setattr(windows, "WindowsGitProcess", fail_start)

    def fail_qualification(*_args, **_kwargs):
        if qualifier == "interruption":
            try:
                session.run(["hash-object", secret])
            except ValueError as error:
                require(error.code == "deadline", "gitea_fixture_interruption")
        else:
            session.run(["hash-object", secret])

    if qualifier == "synthetic":
        monkeypatch.setattr(synthetic, "_qualify_gitea_mirror", fail_qualification)
        with pytest.raises(synthetic.GiteaMirrorQualificationFailure) as caught:
            synthetic.qualify_gitea_mirror(tmp_path)
    else:
        monkeypatch.setattr(actual, "_qualify_gitea_server", fail_qualification)
        with pytest.raises(actual.GiteaQualificationFailure) as caught:
            actual.qualify_gitea_server(tmp_path, tmp_path / "Synthetic binary")
    evidence = caught.value.evidence
    assert caught.value.code == (
        "gitea_fixture_interruption" if qualifier == "interruption" else "git_unavailable"
    )
    assert evidence["result"] == "UNKNOWN"
    detail = evidence["git_runtime"]
    assert detail["operation"] == "hash-object"
    assert detail["errno"] == (2 if kind == "missing" else 13 if kind == "sharing" else None)
    assert detail["winerror"] == (32 if kind == "sharing" else None)
    assert detail["error_type"] == (
        "FileNotFoundError" if kind == "missing" else "PermissionError" if kind == "sharing"
        else "SubprocessError" if kind == "subprocess" else "OSError"
    )
    assert "session_run" in detail["sites"]
    assert detail["raw_message_and_arguments"] == "EXCLUDED"
    rendered = json.dumps(evidence)
    assert secret not in rendered and str(tmp_path) not in rendered
