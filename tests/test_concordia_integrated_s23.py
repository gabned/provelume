"""The integrated synthetic journey uses one Instance and actual local transports."""

from provelume.concordia_qualification import qualify_concordia


def test_integrated_identity_revocation_local_mirrors_and_actual_restore(tmp_path):
    report = qualify_concordia(tmp_path / "Synthetic integrated trial")
    assert report["result"] == "PASS"
    assert report["google_grants"] == 6 and report["task_identities"] == 4
    assert report["provider_execution"] == "SYNTHETIC_ONLY"
    assert report["live_providers"] == report["remote_destinations"] == "NOT_RUN"
