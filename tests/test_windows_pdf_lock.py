from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.resolve_windows_pdf_lock import PDF_VERSION, pins, replace_pdf


def test_pdf_proposal_preserves_every_other_current_pin_and_hash():
    raw = (Path(__file__).parents[1] /
           "build-lock/windows-py312-x86_64.requirements.txt").read_text()
    changed = replace_pdf(raw, "a" * 64)
    assert pins(changed) == {**pins(raw), "pypdf": PDF_VERSION}
    block = r"(?m)^pypdf==[^\n]*\n(?:[ \t]+[^\n]*\n)*"
    # All non-PDF package text, including every original hash, survives byte for byte.
    assert re.sub(block, "", changed).endswith(re.sub(block, "", raw))
    assert replace_pdf(changed, "a" * 64) == changed


@pytest.mark.parametrize("raw", ["other==1\n", "pypdf==1\npypdf==2\n",
                                 "pypdf==1\nother_pkg==1\nother-pkg==2\n"])
def test_ambiguous_or_missing_lock_identity_refuses_a_proposal(raw):
    with pytest.raises(ValueError):
        replace_pdf(raw, "a" * 64)


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 64 + "\n", "A" * 64])
def test_only_an_exact_wheel_digest_can_enter_the_proposed_lock(digest):
    with pytest.raises(ValueError):
        replace_pdf("pypdf==1\n", digest)
