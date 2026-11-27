import json

import pytest

from provelume import mirror_gitea_server_qualification as driver
from provelume.mirror_contract import MirrorError, require


@pytest.mark.parametrize(
    "prior_code", ["git_unavailable", "SYNTHETIC_SECRET/private/path", ["SYNTHETIC_SECRET"]]
)
def test_actual_server_interruption_retains_only_a_closed_prior_error(
    tmp_path, monkeypatch, prior_code
):
    def failed(*_args, **_kwargs):
        try:
            error = MirrorError("git_unavailable")
            error.code = prior_code
            raise error
        except MirrorError as original:
            require(original.code == "deadline", "gitea_fixture_interruption")

    monkeypatch.setattr(driver, "_qualify_gitea_server", failed)
    with pytest.raises(driver.GiteaQualificationFailure) as caught:
        driver.qualify_gitea_server(tmp_path, tmp_path / "Synthetic binary")
    assert caught.value.code == "gitea_fixture_interruption"
    assert caught.value.evidence["result"] == "UNKNOWN"
    context = caught.value.evidence["interruption"]
    assert context["phase"] == "interrupted_publication_error"
    assert context["prior_error_code"] == (
        "git_unavailable" if prior_code == "git_unavailable" else "OTHER"
    )
    assert context["raw_credential_output"] == "EXCLUDED"
    rendered = json.dumps(caught.value.evidence)
    assert "SYNTHETIC_SECRET" not in rendered and str(tmp_path) not in rendered
    assert driver.COMMAND_EVIDENCE.get() is None and driver.COMMAND_SECRETS.get() is None


def test_missing_injected_exception_still_fails_with_closed_stage(tmp_path, monkeypatch):
    def failed(*_args, **_kwargs):
        require(False, "gitea_fixture_interruption")

    monkeypatch.setattr(driver, "_qualify_gitea_server", failed)
    with pytest.raises(driver.GiteaQualificationFailure) as caught:
        driver.qualify_gitea_server(tmp_path, tmp_path / "Synthetic binary")
    assert caught.value.code == "gitea_fixture_interruption"
    assert caught.value.evidence["result"] == "UNKNOWN"
    assert caught.value.evidence["interruption"]["phase"] == "interrupted_publication_missing_error"
