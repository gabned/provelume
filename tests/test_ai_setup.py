"""S07 host authority and browser boundaries. Public fixtures only."""

import asyncio
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html import unescape

import pytest
from fastapi.testclient import TestClient

from provelume.ai_contract import digest
from provelume.ai_job_contract import Quote
from provelume.ai_job_runtime import JobOutcome
from provelume.ai_setup import AiSetup
from provelume.scheduler_model import instant_text, utc_instant
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.fixture
def setup(tmp_path):
    return AiSetup(ProvelumeInstance.initialise(tmp_path / "i"))


def configure(setup):
    setup.save({"mode": "local"}, 0)
    # Test-owned evidence/transport; this seam is never available over HTTP.
    setup.local_evidence = digest("public-s07-synthetic-only")
    setup.enable()


def form(response):
    return {
        key: unescape(re.search(r'name="' + key + r'" value="([^"]+)"', response.text)[1])
        for key in ("csrf_token", "mutation_nonce", "instance_id")
    }


def test_first_read_is_off_and_has_no_model_or_provider_effects(setup, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("read performed an active operation")

    monkeypatch.setattr(setup.models, "status", forbidden)
    monkeypatch.setattr(setup.runtime, "validate_installation", forbidden)
    setup.credentials = forbidden
    for _ in range(2):
        view = setup.read()
        assert view["configuration"]["mode"] == "off"
        assert view["control"]["session_authorized"] is False
    setup.close()
    assert not setup.path.exists()
    assert not setup.models.root.exists()
    assert not setup.jobs.journal.list_jobs()


def test_consent_enqueue_and_dispatch_are_distinct(setup):
    configure(setup)
    ref, prepared = setup.preview_test()
    assert prepared[1].outcome == "planned"
    assert "ada@example.test" not in setup.payload(prepared)
    with pytest.raises(ValueError):
        setup.enqueue(ref)
    setup.approve(ref)
    assert not setup.jobs.journal.list_jobs()
    first = setup.enqueue(ref)
    assert setup.enqueue(ref)["id"] == first["id"]
    assert first["attempt"] == 0
    setup.instance.run_scheduler_cycle()
    assert setup.jobs.public(first["id"])["attempt"] == 0

    class Transport:
        network_used = False

        def exchange(self, current, *, cancel):
            current().prepare()
            assert not cancel()
            return JobOutcome(
                {"kind": "untrusted_text", "value": "Public synthetic test."},
                units=10,
                micros=0,
                usage_source="LOCAL",
            )

    setup.jobs.adapters = {prepared[3][0].fingerprint: Transport()}
    now = utc_instant()
    setup.jobs.quotes = lambda fingerprint: Quote(
        fingerprint,
        "USD",
        instant_text(now - timedelta(days=1)),
        instant_text(now + timedelta(days=1)),
        0,
        8448,
        digest("synthetic-free-fixture"),
        True,
    )
    result = setup.instance.run_ai_job(first["id"])
    assert result["status"] == "succeeded"
    assert "result" not in result["ai"]
    assert len(setup.jobs.journal.list_receipts()) == 1


@pytest.mark.parametrize("mutation", ["configuration", "off", "evidence", "expired"])
def test_preview_revocation_is_checked_by_server(setup, mutation):
    configure(setup)
    ref, _ = setup.preview_test()
    setup.approve(ref)
    if mutation == "configuration":
        setup.save({"job_units": 100}, 1)
    elif mutation == "off":
        setup.control("off", 1)
    elif mutation == "evidence":
        setup.local_evidence = None
    else:
        setup.previews[ref]["created"] -= 601
    with pytest.raises(ValueError):
        setup.enqueue(ref)
    assert not setup.jobs.journal.list_jobs()


def test_concurrent_enqueue_has_one_owner(setup):
    configure(setup)
    ref, _ = setup.preview_test()
    setup.approve(ref)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: setup.enqueue(ref)["id"], range(2)))
    assert len(set(values)) == 1
    assert len(setup.jobs.journal.list_jobs()) == 1


def test_reopen_does_not_restore_consent_or_enablement(setup):
    configure(setup)
    ref, _ = setup.preview_test()
    setup.approve(ref)
    reopened = AiSetup(ProvelumeInstance(setup.instance.root))
    assert not reopened.read()["control"]["session_authorized"]
    with pytest.raises(ValueError):
        reopened.enqueue(ref)


def test_browser_csrf_instance_replay_and_no_adapter_seam(setup, tmp_path):
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        page = client.get("/settings/ai?lang=it")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        data = {**form(page), "action": "off", "revision": "0"}
        assert (
            client.post("/settings/ai/control", data={**data, "csrf_token": "bad"}).status_code
            == 403
        )
        assert (
            client.post("/settings/ai/control", data={**data, "instance_id": "wrong"}).status_code
            == 409
        )
        assert (
            client.post("/settings/ai/control", data=data, follow_redirects=False).status_code
            == 303
        )
        assert client.post("/settings/ai/control", data=data).status_code == 409
        assert client.post("/settings/ai/qualify", data=data).status_code == 404
        assert client.get("/operations/ai").status_code == 200


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "it", "pt", "ro"])
def test_all_catalogs_render(setup, tmp_path, language):
    client = TestClient(
        create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    )
    for path in ("/settings/ai", "/operations/ai"):
        response = client.get(path, params={"lang": language})
        assert response.status_code == 200
        assert "ai." not in re.sub(r"<[^>]*>", "", response.text)


def test_http_preview_consent_job_controls_receipt_are_governed(setup, tmp_path):
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    entered, release = threading.Event(), threading.Event()

    class Transport:
        network_used = False

        def exchange(self, current, *, cancel):
            current().prepare()
            entered.set()
            assert release.wait(10)
            assert not cancel()
            return JobOutcome(
                {"kind": "untrusted_text", "value": "<script>private</script>"},
                units=10,
                micros=0,
                usage_source="LOCAL",
            )

    profiles = host.profiles(host.configuration())[0]
    host.jobs.adapters = {profiles[0].fingerprint: Transport()}
    now = utc_instant()
    host.jobs.quotes = lambda fingerprint: Quote(
        fingerprint,
        "USD",
        instant_text(now - timedelta(days=1)),
        instant_text(now + timedelta(days=1)),
        0,
        8448,
        digest("synthetic-zero-cost"),
        True,
    )
    with TestClient(app) as client:
        settings = client.get("/settings/ai")
        preview = client.post("/settings/ai/test/preview", data=form(settings))
        assert preview.status_code == 200
        assert "[REDACTED]" in preview.text and "ada@example.test" not in preview.text
        ref = re.search(r'name="ref" value="([^"]+)"', preview.text)[1]
        consent = client.post(
            "/settings/ai/test/consent",
            data={
                **form(preview),
                "ref": ref,
                "acknowledge": "synthetic-test",
            },
        )
        assert consent.status_code == 200
        queued = client.post("/settings/ai/test/enqueue", data={**form(consent), "ref": ref})
        assert queued.status_code == 200
        assert not entered.is_set()
        job_id = host.previews[ref]["job"]
        revision = re.search(r'name="revision" value="([^"]+)"', queued.text)[1]
        try:
            dispatch = client.post(
                "/operations/ai/control",
                data={
                    **form(queued),
                    "job_id": job_id,
                    "action": "dispatch",
                    "revision": revision,
                },
            )
            assert dispatch.status_code == 200
            assert entered.wait(5)
            assert client.get("/search?q=synthetic").status_code == 200
            assert client.get("/settings/ai").status_code == 200
        finally:
            release.set()

        async def completed():
            await asyncio.gather(*tuple(app.state.ai_tasks))

        client.portal.call(completed)
        receipt = client.get("/operations/ai")
        assert host.jobs.public(job_id)["status"] == "succeeded"
        assert "private" not in receipt.text
        assert "<script>private</script>" not in receipt.text
        assert len(host.jobs.journal.list_receipts()) == 1


def test_exact_document_selection_is_private_and_not_executable(setup, tmp_path):
    from test_representations import _materialize

    source = tmp_path / "source"
    source.mkdir()
    (source / "public.txt").write_text("Public source", encoding="utf-8")
    setup.instance.ingest(source)
    document = setup.instance.store.list_canonical("documents")[0]
    version = setup.instance.get_document(document["id"])["current_version"]["id"]
    bundle = _materialize(setup.instance, version)
    configure(setup)
    selected, choices = setup.document_choices(document["id"])
    assert selected["current_version"]["id"] == version
    choice = next(c for c in choices if c[0] == bundle["representation_id"])
    prepared, _ = setup.document_preview(
        document["id"],
        representation_id=choice[0],
        output_id=choice[1],
        anchor_id=choice[2],
        start=0,
        end=7,
    )
    assert prepared[0].manifest.version.version_id == version
    assert prepared[0].manifest.coverage == "partial"
    assert not setup.previews
    assert not setup.jobs.journal.list_jobs()
