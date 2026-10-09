"""S07 host authority and browser boundaries. Public fixtures only."""

import asyncio
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from html import unescape

import pytest
from fastapi.testclient import TestClient

from provelume.ai_contract import digest
from provelume.ai_job_contract import Quote
from provelume.ai_job_runtime import JobOutcome, LocalFailure
from provelume.ai_model_store import SelfTestEvidence
from provelume.ai_provider import Failure
from provelume.ai_runtime import native_selection
from provelume.ai_runtime_contract import MODEL_ID
from provelume.ai_setup import AiSetup
from provelume.scheduler_model import instant_text, utc_instant
from provelume.service import ProvelumeInstance
from provelume.web import create_app


@pytest.fixture
def setup(tmp_path):
    return AiSetup(ProvelumeInstance.initialise(tmp_path / "i"))


def configure(setup, *, valid_seconds=60):
    setup.save({"mode": "local"}, 0)
    # Test-owned evidence/transport; this seam is never available over HTTP.
    setup.local_evidence = digest("public-s07-synthetic-only")
    entry = setup.models.registry.entry(MODEL_ID)
    evidence = SelfTestEvidence(
        MODEL_ID, setup.models._binding(entry, native_selection()), "PASSED",
        time.monotonic() + valid_seconds,
    )
    setup.self_test_evidence = evidence
    setup.models._evidence[MODEL_ID] = evidence
    setup.models._native_runners[MODEL_ID] = setup.runtime
    setup.models._prepare()
    setup.models._write_state({"schema_version": 1, "active": MODEL_ID, "previous": None})
    setup.enable()


@pytest.mark.parametrize("state", ["not_active", "expired", "replaced", "wrong_binding"])
def test_local_route_requires_current_activation_before_consent(setup, state, monkeypatch):
    configure(setup)
    if state == "not_active":
        setup.models._write_state({"schema_version": 1, "active": None, "previous": None})
    elif state == "expired":
        evidence = replace(setup.self_test_evidence, expires=time.monotonic() - 1)
        setup.self_test_evidence = setup.models._evidence[MODEL_ID] = evidence
    elif state == "replaced":
        setup.models._evidence.pop(MODEL_ID)
    else:
        evidence = replace(setup.self_test_evidence, binding=digest("different-session"))
        setup.self_test_evidence = setup.models._evidence[MODEL_ID] = evidence

    def forbidden(*args, **kwargs):
        pytest.fail("planning verified or loaded model/runtime bytes")

    monkeypatch.setattr(setup.models, "_verify", forbidden)
    monkeypatch.setattr(setup.runtime, "validate_installation", forbidden)
    ref, prepared = setup.preview_test()
    assert not any(route.eligible for route in prepared[1].routes)
    with pytest.raises(ValueError):
        setup.approve(ref)
    with pytest.raises(ValueError):
        setup.enqueue(ref)
    assert not setup.jobs.journal.list_jobs()
    assert setup.jobs.status()["accounting"]["units"] == 0


@pytest.mark.parametrize("change", ["deactivate", "expire", "revoke"])
def test_model_activation_change_invalidates_already_approved_preview(setup, change):
    configure(setup)
    ref, _ = setup.preview_test()
    setup.approve(ref)
    if change == "deactivate":
        setup.models._write_state({"schema_version": 1, "active": None, "previous": None})
    elif change == "expire":
        evidence = replace(setup.self_test_evidence, expires=time.monotonic() - 1)
        setup.self_test_evidence = setup.models._evidence[MODEL_ID] = evidence
    else:
        setup.models.allowed_ids = ()
    with pytest.raises(ValueError):
        setup.enqueue(ref)
    assert not setup.jobs.journal.list_jobs()


def test_expired_model_evidence_blocks_queued_job_before_reservation(setup):
    configure(setup)
    ref, _ = setup.preview_test()
    setup.approve(ref)
    job = setup.enqueue(ref)
    evidence = replace(setup.self_test_evidence, expires=time.monotonic() - 1)
    setup.self_test_evidence = setup.models._evidence[MODEL_ID] = evidence
    assert setup.jobs.journal.claim_next(
        worker_id="s07-stale-model", job_id=job["id"], ai_admit=setup.jobs.admit_locked
    ) is None
    stored = setup.jobs.journal.get_job(job["id"])
    assert stored["attempt"] == 0
    assert stored["ai"]["attempts"] == []
    assert setup.jobs.status()["accounting"]["units"] == 0


def test_shutdown_revokes_before_joining_an_ai_task(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    ref, _ = host.preview_test()
    host.approve(ref)
    entered, release = threading.Event(), threading.Event()

    def cycle(**kwargs):
        with host.instance.scheduler._hold_lifecycle("synthetic-shutdown-race"):
            entered.set()
            assert release.wait(10)

    monkeypatch.setattr(host.instance, "run_scheduler_cycle", lambda **kw: None)

    async def start_owned_task():
        task = asyncio.create_task(asyncio.to_thread(cycle))
        app.state.ai_tasks.add(task)
        task.add_done_callback(app.state.ai_tasks.discard)

    def serve():
        with TestClient(app) as client:
            client.portal.call(start_owned_task)
            assert entered.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        closing = pool.submit(serve)
        try:
            assert host.cancel.wait(10)
            assert not host.jobs.session_authorized
            assert not host.previews
            assert not closing.done()
            with pytest.raises(ValueError):
                host.current(ref, 0)
        finally:
            release.set()
        closing.result(timeout=10)
    assert host.jobs._control()["mode"] == "off"
    assert not host.runtime.loaded
    assert not host.jobs.journal.list_jobs()


def test_shutdown_joins_scheduler_before_cancelling_and_settling_ai(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "i")
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    ref, prepared = host.preview_test()
    host.approve(ref)
    job = host.enqueue(ref)
    ai_entered, cycle_entered, release_cycle = (
        threading.Event(), threading.Event(), threading.Event()
    )

    class Transport:
        network_used = False

        def exchange(self, current, *, cancel):
            current().prepare()
            ai_entered.set()
            assert host.cancel.wait(10)
            assert cancel()
            # Test-owned local worker has now stopped. Unknown token consumption
            # remains charged, but confirmed quiescence must be committed.
            return LocalFailure(Failure.CANCELLED)

    host.jobs.adapters = {prepared[3][0].fingerprint: Transport()}
    now = utc_instant()
    host.jobs.quotes = lambda fingerprint: Quote(
        fingerprint, "USD", instant_text(now - timedelta(days=1)),
        instant_text(now + timedelta(days=1)), 0, 8448,
        digest("synthetic-shutdown-zero-cost"), True,
    )

    def cycle(**kwargs):
        assert ai_entered.wait(10)
        with host.instance.scheduler._hold_lifecycle("synthetic-concurrent-shutdown"):
            cycle_entered.set()
            assert release_cycle.wait(10)

    monkeypatch.setattr(host.instance, "run_scheduler_cycle", cycle)

    async def exercise():
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        task = asyncio.create_task(asyncio.to_thread(host.instance.run_ai_job, job["id"]))
        app.state.ai_tasks.add(task)
        task.add_done_callback(app.state.ai_tasks.discard)
        closing = None
        try:
            assert await asyncio.to_thread(cycle_entered.wait, 10)
            closing = asyncio.create_task(context.__aexit__(None, None, None))
            await asyncio.sleep(0)  # Let shutdown reach its first join, not a timed race.
            assert not closing.done()
            assert not host.cancel.is_set()
            assert host.jobs.session_authorized
        finally:
            release_cycle.set()
            if closing is None:
                closing = asyncio.create_task(context.__aexit__(None, None, None))
            await closing
            await task  # Do not hide a completion error behind lifespan's gather.

    asyncio.run(exercise())
    stored = host.jobs.journal.get_job(job["id"])
    attempt = stored["ai"]["attempts"][-1]
    assert attempt["phase"] == "settled"
    assert attempt["quiescent"] is True
    assert attempt["usage_source"] == "LOCAL"
    assert attempt["micros"] == 0
    assert stored["ai"]["terminal"] == "failed"
    assert stored["ai"]["blocked"] == "ai_local_stopped"
    assert host.jobs.status()["accounting"]["active"] == 0
    assert len(host.jobs.journal.list_receipts()) == 1
    assert host.jobs._control()["mode"] == "off"
    assert not host.jobs.session_authorized
    assert not host.previews


def test_failed_shutdown_write_still_revokes_and_closes_runtime(setup, monkeypatch):
    from provelume.scheduler_model import SchedulerBusyError

    configure(setup)
    closed = []

    def busy(**kwargs):
        raise SchedulerBusyError("synthetic competing Instance owner")

    monkeypatch.setattr(setup.jobs, "configure", busy)
    monkeypatch.setattr(setup.runtime, "close", lambda: closed.append(True))
    with pytest.raises(SchedulerBusyError):
        setup.close()
    assert setup.cancel.is_set()
    assert not setup.jobs.session_authorized
    assert not setup.previews
    assert closed == [True]


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


@pytest.mark.parametrize("mutation", ["redaction", "template", "limits", "source", "route"])
def test_in_place_authority_mutation_invalidates_approved_preview(setup, mutation):
    from provelume.ai_context import RedactionConfig, TaskTemplate

    configure(setup)
    ref, prepared = setup.preview_test()
    setup.approve(ref)
    if mutation == "redaction":
        prepared[2]["redaction"] = RedactionConfig(email=False)
    elif mutation == "template":
        prepared[2]["template"] = TaskTemplate("context-check-complete-v1", False)
    elif mutation == "limits":
        prepared[2]["request_limits"] = replace(prepared[2]["request_limits"], max_input_bytes=1)
    elif mutation == "source":
        source = setup.previews[ref]["source"]
        setup.previews[ref]["source"] = replace(
            source, outputs=(replace(source.outputs[0], data=b"changed public fixture"),)
        )
    else:
        prepared[5].clear()
    with pytest.raises(ValueError):
        setup.enqueue(ref)
    assert not setup.jobs.journal.list_jobs()


def test_http_two_tabs_cannot_overwrite_newer_configuration(setup, tmp_path):
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        pages = [client.get("/settings/ai") for _ in range(2)]
        configuration = app.state.ai_setup.configuration()
        values = {
            k: str(v)
            for k, v in configuration.items()
            if k not in {"instance_id", "schema_version"}
        }
        first = client.post("/settings/ai", data={**form(pages[0]), **values, "mode": "local"})
        assert first.status_code == 200
        stale = client.post("/settings/ai", data={**form(pages[1]), **values, "mode": "off"})
        assert stale.status_code == 409
        assert app.state.ai_setup.configuration()["mode"] == "local"
        assert not app.state.ai_setup.jobs.session_authorized


def test_http_concurrent_form_replay_has_one_effect(setup, tmp_path):
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    with TestClient(app) as client:
        values = {**form(client.get("/settings/ai")), "action": "off", "revision": "0"}
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait(timeout=10)
            return client.post(
                "/settings/ai/control", data=values, follow_redirects=False
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: submit(), range(2)))
        assert sorted(outcomes) == [303, 409]


def test_http_local_setup_cancel_remains_requested_until_worker_exits(setup, tmp_path, monkeypatch):
    from provelume.ai_models import ModelError

    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    entered, release = threading.Event(), threading.Event()

    def controlled_import(*args, cancel, **kwargs):
        entered.set()
        assert release.wait(10)
        assert cancel()
        raise ModelError("cancelled")

    monkeypatch.setattr(host.models, "import_offline", controlled_import)
    with TestClient(app) as client:
        try:
            response = client.post(
                "/settings/ai/model",
                data={
                    **form(client.get("/settings/ai")),
                    "action": "import",
                    "path": "public-model.gguf",
                    "acknowledge": "explicit",
                },
            )
            assert response.status_code == 200 and entered.wait(5)
            assert client.get("/search?q=public").status_code == 200
            response = client.post(
                "/settings/ai/model/cancel",
                data={**form(response), "operation_id": host.operation["id"]},
            )
            assert response.status_code == 200
            assert host.operation["cancel_requested"]
            assert host.operation["state"] == "running"
        finally:
            release.set()

        async def complete():
            await asyncio.gather(*tuple(app.state.ai_tasks))

        client.portal.call(complete)
        assert host.operation["state"] == "cancelled"
        assert "public-model.gguf" not in client.get("/settings/ai").text
        assert "import" in host.model_actions()


def test_current_budget_blocks_dispatch_before_model_entry(setup, monkeypatch):
    configure(setup)
    setup.save({"job_units": 1}, 1)
    setup.enable()
    ref, _ = setup.preview_test()
    setup.approve(ref)
    job = setup.enqueue(ref)

    def forbidden(*args, **kwargs):
        pytest.fail("budget denial must precede runtime entry")

    monkeypatch.setattr(setup.runtime, "_infer", forbidden)
    setup.instance.run_ai_job(job["id"])
    current = setup.jobs.public(job["id"])
    assert current["attempt"] == 0
    assert current["ai"]["blocked"] == "ai_budget_exhausted"


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "it", "pt", "ro"])
def test_preview_and_security_errors_use_the_selected_catalog(setup, tmp_path, language):
    from provelume.i18n import translator

    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    host.save({"mode": "local"}, 0)  # Unqualified: preview must explain locality, not execute.
    t = translator(language)
    with TestClient(app) as client:
        page = client.get("/settings/ai", params={"lang": language})
        preview = client.post(
            "/settings/ai/test/preview", params={"lang": language}, data=form(page)
        )
        assert preview.status_code == 200
        assert t("ai.reason_locality") in unescape(preview.text)
        assert t("ai.duration_limit") in unescape(preview.text)
        assert "<dd>60</dd>" in preview.text
        assert "<dd>4224</dd>" in preview.text
        assert "/settings/ai/test/consent" not in preview.text
        invalid = client.post(
            "/settings/ai/control",
            params={"lang": language},
            data={**form(page), "csrf_token": "invalid", "action": "off", "revision": "1"},
        )
        assert invalid.status_code == 403
        assert invalid.json()["detail"] == t("ai.error")


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


@pytest.mark.parametrize("contention", ["none", "brief", "persistent"])
def test_http_preview_consent_job_controls_receipt_are_governed(
    setup, tmp_path, monkeypatch, contention
):
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
            values = {**form(queued), "job_id": job_id, "action": "dispatch",
                      "revision": revision}
            if contention == "none":
                dispatch = client.post("/operations/ai/control", data=values)
            else:
                from provelume.instance_lifecycle import InstanceLifecycleManager

                held, release_lock, claim_started = (
                    threading.Event(), threading.Event(), threading.Event()
                )
                claim = host.instance.scheduler.claim_ai_job

                def observe_claim(selected):
                    claim_started.set()
                    return claim(selected)

                def hold_other_operation():
                    with InstanceLifecycleManager(host.instance.store)._hold(
                        purpose="synthetic-dispatch-contention"
                    ):
                        held.set()
                        assert release_lock.wait(10)

                monkeypatch.setattr(host.instance.scheduler, "claim_ai_job", observe_claim)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    owner = pool.submit(hold_other_operation)
                    try:
                        assert held.wait(5)
                        pending = pool.submit(client.post, "/operations/ai/control", data=values)
                        assert claim_started.wait(5)
                        assert not entered.is_set()
                        if contention == "brief":
                            assert not pending.done()
                            release_lock.set()
                        dispatch = pending.result(timeout=5)
                        if contention == "persistent":
                            assert dispatch.status_code == 409
                            job = host.jobs.public(job_id)
                            assert job["status"] == "queued" and job["attempt"] == 0
                            assert not job["ai"]["attempts"] and not entered.is_set()
                    finally:
                        release_lock.set()
                        owner.result(timeout=5)
                if contention == "persistent":
                    # A fresh explicit request after a visible busy response;
                    # neither the host nor the adapter resends automatically.
                    dispatch = client.post("/operations/ai/control", data={
                        **values, **form(dispatch),
                    })
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


@pytest.mark.parametrize("action", ["consent", "enqueue"])
@pytest.mark.parametrize("contention", ["brief", "persistent", "revoked"])
def test_http_ai_authorization_waits_before_mutating_and_never_replays(
    setup, tmp_path, monkeypatch, action, contention
):
    from provelume import instance_lifecycle

    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    # Hold the real lifecycle lock at a controlled point instead of depending on
    # the timing of the first background scheduler cycle (the Windows failure).
    monkeypatch.setattr(host.instance, "run_scheduler_cycle", lambda **kwargs: None)
    held, attempted, release_lock = threading.Event(), threading.Event(), threading.Event()
    acquire = instance_lifecycle._acquire_os_lock

    def observe_acquire(descriptor):
        try:
            return acquire(descriptor)
        except instance_lifecycle.InstanceLifecycleBusy:
            attempted.set()
            raise

    monkeypatch.setattr(instance_lifecycle, "_acquire_os_lock", observe_acquire)
    with TestClient(app) as client:
        preview = client.post("/settings/ai/test/preview", data=form(client.get("/settings/ai")))
        ref = re.search(r'name="ref" value="([^"]+)"', preview.text)[1]
        values = {**form(preview), "ref": ref}
        if action == "consent":
            values["acknowledge"] = "synthetic-test"
        else:
            host.approve(ref)

        def hold_other_operation():
            with instance_lifecycle.InstanceLifecycleManager(host.instance.store)._hold(
                purpose="synthetic-ai-authorization-contention"
            ):
                held.set()
                assert release_lock.wait(10)
                if contention == "revoked":
                    # A supported authoritative change while owning the barrier.
                    control = host.jobs._control()
                    control["generation"] += 1
                    host.jobs._save_control(control)

        with ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(hold_other_operation)
            try:
                assert held.wait(5)
                started = time.monotonic()
                pending = pool.submit(client.post, f"/settings/ai/test/{action}", data=values)
                assert attempted.wait(5)
                assert not pending.done()
                assert host.previews[ref]["approved"] is (action == "enqueue")
                assert not host.jobs.journal.list_jobs()
                if contention != "persistent":
                    release_lock.set()
                response = pending.result(timeout=5)
                assert time.monotonic() - started < 5
            finally:
                release_lock.set()
                owner.result(timeout=5)
        if contention == "brief":
            assert response.status_code == 200
            assert host.previews[ref]["approved"]
            assert len(host.jobs.journal.list_jobs()) == (action == "enqueue")
        else:
            assert response.status_code == 409
            assert not host.jobs.journal.list_jobs()
            assert host.jobs.status()["accounting"]["units"] == 0
            if action == "consent":
                assert not host.previews[ref]["approved"]
        # The used form cannot repeat a mutation, even after the owner releases.
        assert client.post(f"/settings/ai/test/{action}", data=values).status_code == 409
        assert len(host.jobs.journal.list_jobs()) == (
            action == "enqueue" and contention == "brief"
        )
        assert not app.state.ai_tasks
        assert not host.runtime.loaded


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


@pytest.mark.parametrize("language", ["de", "en", "es", "fr", "it", "pt", "ro"])
def test_document_http_exact_version_private_text_escaping_and_staleness(tmp_path, language):
    from test_representations import _implementation, _seed

    from provelume.representations import RepresentationBundleManager

    instance, version = _seed(tmp_path)
    text = "<script>public</script> ada@example.test"
    bundle = RepresentationBundleManager(instance.store).materialize(
        version,
        recipe_id="s07-public-escape",
        recipe_version="1",
        recipe_settings={},
        output_payloads={"public.txt": ("text/plain", text.encode())},
        implementation=_implementation(),
        anchor_targets=({"kind": "page", "page": 1},),
        created_at="2026-10-05T00:00:00+00:00",
    )
    app = create_app(instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    document = instance.store.list_canonical("documents")[0]
    path = "/documents/" + document["id"] + "/ai"
    choice = (bundle["representation_id"], bundle["outputs"][0]["id"], bundle["anchors"][0]["id"])
    with TestClient(app) as client:
        selection = client.get(path, params={"lang": language})
        assert selection.status_code == 200
        values = {
            "selection": ":".join(choice),
            "version_id": version,
            "start": "0",
            "end": str(len(text)),
        }
        preview = client.post(path, params={"lang": language}, data={**form(selection), **values})
        assert preview.status_code == 200
        assert "&lt;script&gt;public&lt;/script&gt; ada@example.test" in preview.text
        assert "<script>public</script>" not in preview.text
        assert "[REDACTED]" in preview.text
        assert preview.headers["cache-control"] == "no-store"
        assert "/test/consent" not in preview.text and "/test/enqueue" not in preview.text
        assert not host.previews and not host.jobs.journal.list_jobs()
        assert "ada@example.test" not in client.get("/operations/ai").text
        stale = client.get(path, params={"lang": language})
        (tmp_path / "source" / "note.txt").write_text("Changed public version", encoding="utf-8")
        instance.ingest(tmp_path / "source")
        response = client.post(path, params={"lang": language}, data={**form(stale), **values})
        assert response.status_code == 409


def test_operations_hides_dispatch_after_session_revocation(setup, tmp_path):
    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    configure(host)
    ref, _ = host.preview_test()
    host.approve(ref)
    host.enqueue(ref)
    with TestClient(app) as client:
        assert 'value="dispatch"' in client.get("/operations/ai").text
        host.control("off", 1)
        assert 'value="dispatch"' not in client.get("/operations/ai").text


def test_non_cancellable_model_operation_does_not_accept_cancellation(setup):
    identity = setup.begin_operation("runtime")
    with pytest.raises(ValueError):
        setup.cancel_operation(identity)
    assert not setup.operation["cancel_requested"]
    assert "verify" not in setup.model_actions()  # No installed model to verify.


def test_external_preview_names_actual_destination_without_network_or_vault(
    setup, tmp_path, monkeypatch
):
    import socket

    app = create_app(setup.instance.root, shell_settings_file=tmp_path / "shell.json")
    host = app.state.ai_setup
    destination = "https://provider.example.test/v1/chat/completions"
    host.save({"mode": "external", "endpoint": destination, "model": "public-model"}, 0)

    def forbidden(*args, **kwargs):
        pytest.fail("preview must not probe network or credentials")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    host.credentials = forbidden
    with TestClient(app) as client:
        response = client.post("/settings/ai/test/preview", data=form(client.get("/settings/ai")))
        assert response.status_code == 200
        assert destination in response.text
        assert "/test/consent" not in response.text
        assert not host.jobs.journal.list_jobs()
