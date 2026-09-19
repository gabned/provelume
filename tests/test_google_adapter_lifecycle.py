from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

import provelume.google_jobs as google_jobs
from provelume.google_adapters import SyntheticGoogleAdapter
from provelume.google_contract import GooglePage
from provelume.google_jobs import GoogleJobManager
from provelume.service import ProvelumeInstance
from provelume.storage import InstanceStore


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("These adapter lifecycle regressions must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def test_local_service_construction_does_not_initialize_google_transport(tmp_path, monkeypatch):
    def denied():
        pytest.fail("Local Instance startup must not construct the Google transport")

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", denied)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    reopened = ProvelumeInstance(instance.store.paths.root)
    assert reopened.google.list_jobs() == []
    assert instance.google.list_jobs() == []


def test_google_queue_and_execution_initialize_once_and_reuse_adapter(tmp_path, monkeypatch):
    created = []

    class DefaultAdapter:
        def __init__(self):
            self.calls = 0
            created.append(self)

        def fetch_page(self, **kwargs):
            self.calls += 1
            return GooglePage(capability="drive", items=())

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", DefaultAdapter)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    connector = instance.create_google_instance(
        name="Synthetic lazy transport", account_identity="synthetic@example.invalid"
    )["connector"]["id"]
    instance.set_google_connector_state(connector, enabled=True)
    instance.authorize_google_capability(
        connector, "drive", consent=True,
        credential_reference={"kind": "environment", "name": "PROVELUME_TEST_GOOGLE"},
    )
    instance.set_google_capability_state(connector, "drive", state="enabled")
    source = instance.create_google_source(
        connector, name="Synthetic drive", capability="drive",
        selection_kind="file", selectors=["synthetic-file"],
    )
    instance.set_google_source_state(source["id"], state="enabled")
    queued = instance.queue_google_intake(source["id"])
    assert created == []
    instance.scheduler._google_manager_factory = lambda store: instance.google
    result = instance.run_google_job(queued["job"]["id"])
    assert result["status"] == "succeeded"
    assert len(created) == 1 and instance.google.adapter is created[0]
    assert created[0].calls == 1
    second = instance.queue_google_intake(source["id"])
    assert instance.run_google_job(second["job"]["id"])["status"] == "succeeded"
    assert len(created) == 1 and created[0].calls == 2


def test_explicit_falsey_provider_is_preserved_without_default_initialization(
    tmp_path, monkeypatch
):
    class FalseyProvider(SyntheticGoogleAdapter):
        def __bool__(self):
            return False

    def denied():
        pytest.fail("An injected provider must not construct a default transport")

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", denied)
    provider = FalseyProvider({})
    manager = GoogleJobManager(InstanceStore(tmp_path / "instance"), adapter=provider)
    assert manager.adapter is provider


def test_concurrent_first_access_publishes_one_complete_adapter(tmp_path, monkeypatch):
    ready = Barrier(9)
    constructing, release = Event(), Event()
    constructed = []

    class DefaultAdapter:
        def __init__(self):
            constructed.append(self)
            constructing.set()
            assert release.wait(10)
            self.complete = True

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", DefaultAdapter)
    manager = GoogleJobManager(InstanceStore(tmp_path / "instance"))

    def get_adapter():
        ready.wait(10)
        result = manager.adapter
        assert result.complete
        return result

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(get_adapter) for _ in range(8)]
        ready.wait(10)
        assert constructing.wait(10)
        release.set()
        results = [future.result(timeout=10) for future in futures]
    assert len(constructed) == 1 and all(item is constructed[0] for item in results)


def test_failed_construction_is_retried_without_publishing_partial_state(tmp_path, monkeypatch):
    calls = []
    provider = SyntheticGoogleAdapter({})

    def construct():
        calls.append(None)
        if len(calls) == 1:
            raise OSError("synthetic certificate-store failure")
        return provider

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", construct)
    manager = GoogleJobManager(InstanceStore(tmp_path / "instance"))
    with pytest.raises(OSError, match="synthetic certificate-store failure"):
        _ = manager.adapter
    assert manager.adapter is provider and manager.adapter is provider
    assert len(calls) == 2


def test_adapter_assignment_before_and_after_first_use_remains_supported(tmp_path, monkeypatch):
    calls = []

    def construct():
        calls.append(None)
        return SyntheticGoogleAdapter({})

    monkeypatch.setattr(google_jobs, "GoogleApiAdapter", construct)
    manager = GoogleJobManager(InstanceStore(tmp_path / "instance"))
    first, second = SyntheticGoogleAdapter({}), SyntheticGoogleAdapter({})
    manager.adapter = first
    assert manager.adapter is first and calls == []
    manager.adapter = None
    default = manager.adapter
    assert default is not first and len(calls) == 1
    manager.adapter = second
    assert manager.adapter is second and len(calls) == 1
