"""HTML-search input/recovery contracts on synthetic state, not browser receipts."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def tags(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]

    def inputs(self):
        return {attrs["name"]: attrs for attrs in self.tags("input") if "name" in attrs}


def canonical(instance):
    files = [instance.root / "provelume.yml", instance.root / "instance-manifest.json"]
    for directory in ["knowledge", "originals"]:
        files.extend(p for p in (instance.root / directory).rglob("*") if p.is_file())
    return {str(p.relative_to(instance.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


@pytest.fixture(params=["current", "preview"])
def search_fixture(tmp_path, request):
    source = tmp_path / "source"
    source.mkdir()
    (source / "alpha.txt").write_text("Synthetic orchid zephyronly content.\n")
    (source / "orchid-title.txt").write_text("A separate synthetic document.\n")
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    assert len(instance.ingest(source, source_name="Synthetic source")) == 2
    manager = ShellSettingsManager(tmp_path / "shell.json", LauncherSettings(
        instance_path=str(instance.root), language="en", theme="dark",
    ))
    manager.save(manager.defaults)
    manager.set_interface_mode(request.param, expected_revision=0)
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    return instance, manager, client


def filters(instance):
    day = instance.list_documents()[0]["current_version"]["acquired_at"][:10]
    return {"lang": "en", "source_id": instance.list_sources()[0]["id"],
            "media_type": "text/plain", "date_from": day, "date_to": day}


@pytest.mark.parametrize("query", [None, "", "   ", "\t\n"])
@pytest.mark.parametrize("filtered", [False, True])
def test_initial_state_never_searches_or_shows_false_zero(search_fixture, monkeypatch,
                                                        query, filtered):
    instance, manager, client = search_fixture
    params = filters(instance) if filtered else {"lang": "en"}
    if query is not None:
        params["q"] = query
    before = canonical(instance), manager.path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("initial state executed a search")

    monkeypatch.setattr(ProvelumeInstance, "search", forbidden)
    response = client.get("/search", params=params)
    assert response.status_code == 200
    page = Page(response.text)
    assert page.inputs()["q"]["value"] == ""
    assert "No matching documents." not in response.text
    assert 'class="cura-result-count"' not in response.text
    assert "Words:" not in response.text
    if filtered:
        assert page.inputs()["date_from"]["value"] == params["date_from"]
        assert page.inputs()["date_to"]["value"] == params["date_to"]
        selected = {a.get("value") for a in page.tags("option") if "selected" in a}
        assert {params["source_id"], params["media_type"]} <= selected
    assert (canonical(instance), manager.path.read_bytes()) == before


@pytest.mark.parametrize("bad", ["2023-02-29", "2026-13-01", "2026-02-30", "2026-2-01",
                                 "2026-W01-1", "2026-01-01T12:00:00Z", " "])
@pytest.mark.parametrize("field", ["date_from", "date_to"])
def test_invalid_dates_are_recoverable_html_not_empty_results(search_fixture, monkeypatch,
                                                            bad, field):
    instance, manager, client = search_fixture
    params = {**filters(instance), "q": "  orchid  ", field: bad}
    before = canonical(instance), manager.path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("invalid dates reached the search domain")

    monkeypatch.setattr(ProvelumeInstance, "search", forbidden)
    response = client.get("/search", params=params)
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "No matching documents." not in response.text
    assert 'class="cura-result-count"' not in response.text
    assert "Enter a valid date" in response.text and "UTC" in response.text
    page = Page(response.text)
    assert any(a.get("role") == "alert" for _, a in page.elements)
    inputs = page.inputs()
    assert inputs["q"]["value"] == "orchid"
    assert inputs[field]["value"] == ""
    assert inputs[field]["aria-invalid"] == "true"
    assert inputs[field]["id"] + "-error" in inputs[field]["aria-describedby"]
    assert "autofocus" in inputs[field] and "autofocus" not in inputs["q"]
    other = "date_to" if field == "date_from" else "date_from"
    assert inputs[other]["value"] == params[other]
    assert f'#{inputs[field]["id"]}' in {a.get("href") for a in page.tags("a")}
    assert (canonical(instance), manager.path.read_bytes()) == before


@pytest.mark.parametrize("query", ["", "orchid"])
def test_reversed_dates_remain_visible_and_can_be_corrected(search_fixture, query):
    instance, manager, client = search_fixture
    params = {**filters(instance), "q": query, "date_from": "2030-01-01",
              "date_to": "2000-01-01"}
    before = canonical(instance), manager.path.read_bytes()
    response = client.get("/search", params=params)
    assert response.status_code == 400 and "No matching documents." not in response.text
    inputs = Page(response.text).inputs()
    for field in ["date_from", "date_to"]:
        assert inputs[field]["value"] == params[field] and inputs[field]["aria-invalid"] == "true"
    assert "autofocus" in inputs["date_from"] and "autofocus" not in inputs["date_to"]
    repaired = client.get("/search", params={**filters(instance), "q": "orchid"})
    assert repaired.status_code == 200 and 'class="empty"' not in repaired.text
    assert (canonical(instance), manager.path.read_bytes()) == before


@pytest.mark.parametrize("query", ["orchid", "ORCHID", "  orchid  ", "zephyronly"])
def test_effective_query_and_result_return_are_consistent(search_fixture, query):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    params = {**filters(instance), "q": query}
    response = client.get("/search", params=params)
    assert response.status_code == 200
    page = Page(response.text)
    assert page.inputs()["q"]["value"] == query.strip()
    links = [a["href"] for a in page.tags("a")
             if a.get("href", "").startswith("/documents/doc_")
             and not urlsplit(a["href"]).path.endswith("/provenance")]
    assert len(links) == (1 if query == "zephyronly" else 2)
    for link in links:
        back = parse_qs(urlsplit(link).query)["return_to"][0]
        target = urlsplit(back)
        assert parse_qs(target.query) == {k: [v] for k, v in {**params, "q": query.strip()}.items()}
        assert target.fragment == "result-" + urlsplit(link).path.rsplit("/", 1)[1]
        document = client.get(link)
        assert document.status_code == 200
        assert back in {a.get("href") for a in Page(document.text).tags("a")}
        provenance = next(a["href"] for a in Page(document.text).tags("a")
                          if urlsplit(a.get("href", "")).path.endswith("/provenance"))
        assert back in {a.get("href") for a in Page(client.get(provenance).text).tags("a")}
        original = client.get(urlsplit(link).path.replace("/documents/", "/api/v1/documents/")
                              + "/original")
        assert original.content in {b"Synthetic orchid zephyronly content.\n",
                                    b"A separate synthetic document.\n"}
        assert client.get(back).status_code == 200
    assert (canonical(instance), manager.path.read_bytes()) == before


def test_hostile_inputs_are_inert_and_bad_return_targets_stay_rejected(search_fixture):
    _, _, client = search_fixture
    hostile = '<script>alert("date")</script>'
    response = client.get("/search", params={"q": '  <img src=x onerror="alert(1)">  ',
                                            "date_to": hostile, "return_to": "https://evil.test/"})
    assert response.status_code == 400 and hostile not in response.text
    assert "&lt;script&gt;" in response.text
    assert not Page(response.text).tags("img") or all(
        "onerror" not in a for a in Page(response.text).tags("img"))
    assert not any(a.get("href", "").startswith("https://evil.test/")
                   for a in Page(response.text).tags("a"))


@pytest.mark.parametrize("language", ["system", "en", "it", "de", "es", "fr", "pt", "ro"])
def test_validation_copy_is_complete_without_preference_writes(search_fixture, language):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    response = client.get("/search", params={
        "q": "orchid", "date_from": "invalid", "lang": language,
    })
    assert response.status_code == 400 and "UTC" in response.text
    assert "search.invalid_date" not in response.text
    assert "search.input_error_title" not in response.text
    assert (canonical(instance), manager.path.read_bytes()) == before


@pytest.mark.parametrize(("dates", "count"), [
    ({}, 2), ({"date_from": "", "date_to": ""}, 2),
    ({"date_from": "0001-01-01"}, 2), ({"date_to": "9999-12-31"}, 2),
    ({"date_from": "2024-02-29"}, 2), ({"date_to": "2024-02-29"}, 0),
    ({"date_from": "2024-02-29", "date_to": "9999-12-31"}, 2),
])
def test_valid_open_calendar_ranges_execute_with_unchanged_day_filters(search_fixture,
                                                                      monkeypatch, dates, count):
    instance, _, client = search_fixture
    calls = []
    original = ProvelumeInstance.search

    def record(self, query, **kwargs):
        calls.append((query, kwargs))
        return original(self, query, **kwargs)

    monkeypatch.setattr(ProvelumeInstance, "search", record)
    response = client.get("/search", params={"q": "  orchid  ", **dates})
    assert response.status_code == 200
    assert len(calls) == 1 and calls[0][0] == "orchid"
    assert calls[0][1]["date_from"] == dates.get("date_from")
    assert calls[0][1]["date_to"] == dates.get("date_to")
    assert len([a for a in Page(response.text).tags("a")
                if a.get("href", "").startswith("/documents/doc_")
                and not urlsplit(a["href"]).path.endswith("/provenance")]) == count


def test_utc_day_boundaries_and_other_callers_keep_existing_semantics(tmp_path, monkeypatch):
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    for index, instant in enumerate(["2024-02-28T23:59:59.999999+00:00",
                                     "2024-02-29T00:00:00+00:00",
                                     "2024-02-29T23:59:59.999999+00:00",
                                     "2024-03-01T00:00:00+00:00"]):
        source = tmp_path / f"boundary-{index}.txt"
        source.write_text(f"Synthetic orchid boundary {index}.\n")
        with monkeypatch.context() as clock:
            clock.setattr("provelume.ingest.utc_now", lambda instant=instant: instant)
            instance.ingest(source)
    settings = tmp_path / "shell.json"
    client = TestClient(create_app(instance.root, shell_settings_file=settings))
    params = {"q": "orchid", "date_from": "2024-02-29", "date_to": "2024-02-29"}
    assert len(client.get("/api/v1/search", params=params).json()["results"]) == 2
    response = client.get("/search", params=params)
    assert response.status_code == 200
    assert len([a for a in Page(response.text).tags("a")
                if a.get("href", "").startswith("/documents/doc_")
                and not urlsplit(a["href"]).path.endswith("/provenance")]) == 2
    timestamps = {"q": "orchid", "date_from": "2024-02-29T00:00:00+00:00",
                  "date_to": "2024-02-29T23:59:59.999999+00:00"}
    assert len(client.get("/api/v1/search", params=timestamps).json()["results"]) == 2
    assert client.get("/search", params=timestamps).status_code == 400
    assert client.get("/browse").status_code == 200
