"""Exercise the same packaged diagnostic entry without pretending Windows exists."""

import pytest

from provelume.review_effects import ReviewError
from provelume.setup_qualification import qualify_setup


def test_explicit_new_synthetic_target_uses_six_distinct_real_routes(tmp_path):
    report = qualify_setup(tmp_path / "new", retention="keep", ocr_required=False,
                           languages=["eng"])
    assert report["result"] == "PASS"
    assert set(report["six_template_responses"]) == {
        "space", "folders", "ocr", "automation", "test", "summary"}
    assert len({row["sha256"] for row in report["six_template_responses"].values()}) == 6
    assert report["documents"][0]["text_kind"] == "embedded"
    assert report["documents"][0]["inbox_outcome"] == "input_kept"
    assert report["sentinel"] == "UNCHANGED"
    assert report["manual_windows_11_home_pro_25h2"] == "NOT_RUN"
    with pytest.raises(ReviewError):
        qualify_setup(tmp_path / "new", retention="keep", ocr_required=False)
