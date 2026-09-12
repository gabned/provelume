from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume import about, publication
from provelume.service import ProvelumeInstance
from provelume.shell_settings import LauncherSettings, ShellSettingsManager
from provelume.web import create_app


class _Page(HTMLParser):
    """Inspect real markup, retaining navigation and section ownership of links."""

    def __init__(self, markup: str):
        super().__init__()
        self.elements: list[tuple[str, dict]] = []
        self.links: list[dict] = []
        self.stack: list[tuple[str, dict]] = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.elements.append((tag, values))
        if tag == "a":
            self.links.append({**values, "ancestors": list(self.stack)})
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, values))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def tags(self, tag):
        return [attrs for selected, attrs in self.elements if selected == tag]

    def in_class(self, class_name):
        return [
            link
            for link in self.links
            if any(
                class_name in attrs.get("class", "").split() for _tag, attrs in link["ancestors"]
            )
        ]

    def primary(self):
        return [
            link
            for link in self.links
            if any(
                tag == "nav" and attrs.get("aria-label") == "Primary navigation"
                for tag, attrs in link["ancestors"]
            )
        ]


def _policy(response):
    return {
        words[0]: words[1:]
        for directive in response.headers["content-security-policy"].split(";")
        if (words := directive.split())
    }


def _canonical(instance):
    paths = [instance.root / "provelume.yml", instance.root / "instance-manifest.json"]
    for directory in ("knowledge", "originals"):
        paths.extend(p for p in (instance.root / directory).rglob("*") if p.is_file())
    return {p.relative_to(instance.root).as_posix(): p.read_bytes() for p in paths}


@pytest.fixture
def shell_fixture(tmp_path):
    source = tmp_path / "synthetic-source"
    (source / "Projects").mkdir(parents=True)
    original = (
        b"# Orchid\n\nOrchid traceable knowledge.\n\n"
        b'<script src="https://untrusted.invalid/payload.js">alert("document-script")</script>\n'
        b'<img src="x" onerror="alert(1)">\n'
        b'<a href="javascript:alert(2)" onclick="alert(3)">untrusted link</a>\n'
    )
    (source / "Projects/orchid.md").write_bytes(original)
    (source / "notes.txt").write_text("A separate synthetic note.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Synthetic Cura shell")
    assert len(instance.ingest(source, source_name="Synthetic files")) == 2
    document = next(item for item in instance.list_documents() if item["title"] == "orchid.md")
    area = instance.create_hierarchy_node("area", "Projects")
    project = instance.create_hierarchy_node("project", "Orchid study", parent_id=area["id"])
    instance.classify_document(document["id"], project["id"])
    manager = ShellSettingsManager(
        tmp_path / "launcher.json",
        LauncherSettings(instance_path=str(instance.root), language="it", theme="dark"),
    )
    manager.save(manager.defaults)
    client = TestClient(create_app(instance.root, shell_settings_file=manager.path))
    return {
        "instance": instance,
        "manager": manager,
        "client": client,
        "document": document,
        "original": original,
        "area": area,
        "project": project,
    }


def _select(fixture, mode):
    manager = fixture["manager"]
    manager.set_interface_mode(mode, expected_revision=manager.load().settings.revision)


def _get(client, route):
    response = client.get(route)
    assert response.status_code == 200, (route, response.status_code, response.text[:300])
    return response, _Page(response.text)


def test_current_and_preview_keep_routes_authoritative_data_and_canonical_bytes(shell_fixture):
    fixture = shell_fixture
    client = fixture["client"]
    identifier = fixture["document"]["id"]
    read_routes = [
        "/api/v1/documents",
        f"/api/v1/documents/{identifier}",
        f"/api/v1/documents/{identifier}/versions",
        f"/api/v1/documents/{identifier}/provenance",
        "/api/v1/search?q=orchid",
    ]
    expected = {route: client.get(route).json() for route in read_routes}
    before = _canonical(fixture["instance"])
    pages = [
        "/",
        "/browse",
        "/search?q=orchid",
        "/inbox",
        "/attention",
        "/management",
        "/sources",
        "/settings/shell",
        "/about",
        f"/documents/{identifier}",
        f"/documents/{identifier}/provenance",
    ]
    for mode in ("current", "preview", "current"):
        _select(fixture, mode)
        for route in pages:
            _response, page = _get(client, route)
            assert ("cura" in page.tags("html")[0].get("class", "").split()) == (mode == "preview")
        assert {route: client.get(route).json() for route in read_routes} == expected
        for route in ("/browse?lang=en", "/search?q=orchid&lang=en"):
            _response, page = _get(client, route)
            assert any(
                urlsplit(link.get("href", "")).path == f"/documents/{identifier}"
                for link in page.links
            )
    assert _canonical(fixture["instance"]) == before


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_persisted_language_applies_to_bare_get_including_management_security(shell_fixture, mode):
    fixture = shell_fixture
    _select(fixture, mode)
    client = fixture["client"]
    for route in (
        "/",
        "/browse",
        "/search",
        "/management",
        "/settings/shell",
        "/about",
        "/security/installation",
        "/security/network",
    ):
        _response, page = _get(client, route)
        assert page.tags("html")[0]["lang"] == "it", route
    _response, explicit = _get(client, "/?lang=en")
    assert explicit.tags("html")[0]["lang"] == "en"
    assert fixture["manager"].load().settings.language == "it"
    restarted = TestClient(
        create_app(fixture["instance"].root, shell_settings_file=fixture["manager"].path)
    )
    assert _Page(restarted.get("/").text).tags("html")[0]["lang"] == "it"


def test_preview_script_has_exact_response_hash_sri_and_narrow_csp(shell_fixture):
    fixture = shell_fixture
    client = fixture["client"]
    _select(fixture, "preview")
    home, page = _get(client, "/?lang=en")
    scripts = page.tags("script")
    assert len(scripts) == 1
    script = scripts[0]
    assert script["src"] == "/static/cura-shell.js"
    raw = client.get(script["src"])
    assert raw.status_code == 200 and raw.content
    expected = "sha256-" + base64.b64encode(hashlib.sha256(raw.content).digest()).decode("ascii")
    assert script["integrity"] == expected and script["crossorigin"] == "anonymous"
    assert "defer" in script
    assert _policy(home)["script-src"] == [f"'{expected}'"]
    assert _policy(home)["form-action"] == ["'self'"]
    assert "unsafe-inline" not in home.headers["content-security-policy"]
    assert "unsafe-eval" not in home.headers["content-security-policy"]
    google, google_page = _get(client, "/google/connect?lang=en")
    assert _policy(google)["script-src"] == [f"'{expected}'"]
    assert _policy(google)["form-action"] == ["'self'", "https://accounts.google.com"]
    assert google_page.tags("script")[0]["integrity"] == expected
    for route in (
        "/api/v1/documents",
        f"/api/v1/documents/{fixture['document']['id']}/original",
        "/does-not-exist",
        script["src"],
    ):
        response = client.get(route)
        assert _policy(response)["script-src"] == ["'none'"], route
        assert response.headers["cache-control"] == "no-store"
    denied = client.get("/", headers={"host": "untrusted.invalid"})
    assert denied.status_code == 400 and _policy(denied)["script-src"] == ["'none'"]
    _select(fixture, "current")
    current, current_page = _get(client, "/?lang=en")
    assert current_page.tags("script") == []
    assert _policy(current)["script-src"] == ["'none'"]


@pytest.mark.parametrize("mode", ["current", "preview"])
def test_untrusted_document_markup_never_gains_script_execution(shell_fixture, mode):
    fixture = shell_fixture
    _select(fixture, mode)
    client = fixture["client"]
    identifier = fixture["document"]["id"]
    for viewer in ("rendered", "raw", "original"):
        response, page = _get(client, f"/documents/{identifier}?mode={viewer}&lang=en")
        assert "document-script" in response.text
        assert [s.get("src") for s in page.tags("script")] == (
            ["/static/cura-shell.js"] if mode == "preview" else []
        )
        for tag, attrs in page.elements:
            assert not any(key.casefold().startswith("on") for key in attrs), (tag, attrs)
            assert "srcdoc" not in attrs
            for key in ("href", "src"):
                assert not attrs.get(key, "").casefold().startswith("javascript:")
        assert page.tags("iframe") == [] and page.tags("object") == []
    download = client.get(f"/api/v1/documents/{identifier}/original")
    assert download.status_code == 200 and download.content == fixture["original"]
    assert download.headers["content-disposition"].startswith("attachment;")
    assert _policy(download)["script-src"] == ["'none'"]


def test_all_six_navigation_owners_and_specialized_links_reach_real_routes(shell_fixture):
    fixture = shell_fixture
    _select(fixture, "preview")
    client = fixture["client"]
    destinations = {"/", "/browse", "/inbox", "/search", "/attention", "/management"}
    for selected in sorted(destinations):
        _response, page = _get(client, selected + "?lang=en")
        primary = page.primary()
        assert len(primary) == 6
        assert {urlsplit(link["href"]).path for link in primary} == destinations
        assert [
            urlsplit(link["href"]).path for link in primary if link.get("aria-current") == "page"
        ] == [selected]
        assert all(parse_qs(urlsplit(link["href"]).query) == {"lang": ["en"]} for link in primary)
    _response, management = _get(client, "/management?lang=en")
    management_links = management.in_class("cura-management-grid")
    management_paths = {urlsplit(link["href"]).path for link in management_links}
    assert {
        "/sources",
        "/scheduler",
        "/settings",
        "/settings/shell",
        "/security",
        "/about",
    } <= management_paths
    _response, knowledge = _get(client, "/browse?lang=en")
    knowledge_links = knowledge.in_class("cura-special-views")
    knowledge_paths = {urlsplit(link["href"]).path for link in knowledge_links}
    assert {
        "/representations",
        "/photos",
        "/audio",
        "/video",
        "/email",
        "/transcripts",
        "/duplicates",
    } <= knowledge_paths
    assert not management_paths & knowledge_paths
    for link in [*management_links, *knowledge_links]:
        parsed = urlsplit(link["href"])
        assert not parsed.scheme and not parsed.netloc
        _get(client, link["href"])


def _assert_return(fixture, link, expected_path, expected_filters):
    parsed = urlsplit(link)
    assert not parsed.scheme and not parsed.netloc
    back = parse_qs(parsed.query)["return_to"][0]
    target = urlsplit(back)
    assert target.path == expected_path
    assert parse_qs(target.query) == {key: [value] for key, value in expected_filters.items()}
    assert target.fragment == "result-" + fixture["document"]["id"]
    return back


@pytest.mark.parametrize("retrieval", ["/browse", "/search"])
def test_real_result_links_preserve_filters_through_viewer_provenance_and_download(
    shell_fixture, retrieval
):
    fixture = shell_fixture
    _select(fixture, "preview")
    client = fixture["client"]
    doc = fixture["document"]
    filters = {
        "lang": "en",
        "source_id": fixture["instance"].list_sources()[0]["id"],
        "media_type": doc["media_type"],
    }
    if retrieval == "/browse":
        filters.update(area="Projects", hierarchy_id=fixture["project"]["id"], disposition="all")
    else:
        day = doc["current_version"]["acquired_at"][:10]
        filters.update(q="orchid", date_from=day, date_to=day)
    route = retrieval + "?" + urlencode(filters)
    response, results = _get(client, route)
    assert f'id="result-{doc["id"]}"' in response.text
    href = next(
        link["href"]
        for link in results.links
        if urlsplit(link.get("href", "")).path == f"/documents/{doc['id']}"
    )
    back = _assert_return(fixture, href, retrieval, filters)
    _response, document = _get(client, href)
    assert any(link.get("class") == "cura-back" and link["href"] == back for link in document.links)
    owner = "/search" if retrieval == "/search" else "/browse"
    assert [
        urlsplit(link["href"]).path
        for link in document.primary()
        if link.get("aria-current") == "page"
    ] == [owner]
    viewer_links = document.in_class("viewer-toolbar")
    modes = [
        link for link in viewer_links if urlsplit(link["href"]).path == f"/documents/{doc['id']}"
    ]
    assert {parse_qs(urlsplit(link["href"]).query)["mode"][0] for link in modes} == {
        "rendered",
        "raw",
        "original",
    }
    for link in modes:
        assert _assert_return(fixture, link["href"], retrieval, filters) == back
        _response, viewed = _get(client, link["href"])
        provenance = next(
            item["href"]
            for item in viewed.links
            if urlsplit(item.get("href", "")).path == f"/documents/{doc['id']}/provenance"
        )
        assert _assert_return(fixture, provenance, retrieval, filters) == back
        _response, trace = _get(client, provenance)
        assert any(
            item.get("class") == "cura-back" and item["href"] == back for item in trace.links
        )
        document_return = next(
            item["href"]
            for item in trace.links
            if urlsplit(item.get("href", "")).path == f"/documents/{doc['id']}"
        )
        assert _assert_return(fixture, document_return, retrieval, filters) == back
    download_link = next(
        link["href"]
        for link in viewer_links
        if urlsplit(link["href"]).path == f"/api/v1/documents/{doc['id']}/original"
    )
    assert "return_to" not in parse_qs(urlsplit(download_link).query)
    downloaded = client.get(download_link)
    assert downloaded.content == fixture["original"]
    assert hashlib.sha256(downloaded.content).hexdigest() == doc["current_version"]["content_hash"]
    returned, _page = _get(client, back)
    assert f'id="result-{doc["id"]}"' in returned.text


def test_hierarchy_and_individual_filter_links_keep_other_selected_facets(shell_fixture):
    fixture = shell_fixture
    _select(fixture, "preview")
    filters = {
        "lang": "en",
        "source_id": fixture["instance"].list_sources()[0]["id"],
        "media_type": fixture["document"]["media_type"],
        "area": "Projects",
        "disposition": "all",
    }
    _response, page = _get(fixture["client"], "/browse?" + urlencode(filters))
    links = page.in_class("hierarchy-list")
    selected = next(
        link["href"]
        for link in links
        if parse_qs(urlsplit(link["href"]).query).get("hierarchy_id") == [fixture["project"]["id"]]
    )
    assert parse_qs(urlsplit(selected).query) == {
        **{key: [value] for key, value in filters.items()},
        "hierarchy_id": [fixture["project"]["id"]],
    }
    _response, filtered = _get(fixture["client"], selected)
    original = parse_qs(urlsplit(selected).query)
    chips = filtered.in_class("cura-filter-chips")
    assert len(chips) == len(original) - 1
    for chip in chips:
        query = parse_qs(urlsplit(chip["href"]).query)
        removed = set(original) - set(query)
        assert len(removed) == 1 and "lang" not in removed
        assert query == {key: value for key, value in original.items() if key not in removed}
        _get(fixture["client"], chip["href"])


def test_untrusted_return_targets_never_reach_navigation_or_viewer_links(shell_fixture):
    fixture = shell_fixture
    _select(fixture, "preview")
    identifier = fixture["document"]["id"]
    targets = [
        "https://untrusted.invalid/search",
        "//untrusted.invalid/search",
        "javascript:alert(1)",
        "/search\\untrusted",
        "/settings/shell",
        "/%2f%2funtrusted.invalid",
        "/search?q=one&q=two",
        "/search?next=https://untrusted.invalid",
        "/search#not-a-document",
        "/search\n?q=orchid",
        "/search?q=orchid%00hidden",
        "/search?lang=untrusted",
        "/search?q=" + "x" * 501,
        "/search?q=" + "x" * 4100,
    ]
    for target in targets:
        for suffix in ("", "/provenance"):
            response = fixture["client"].get(
                f"/documents/{identifier}{suffix}", params={"lang": "en", "return_to": target}
            )
            assert response.status_code == 200
            page = _Page(response.text)
            assert not any(link.get("class") == "cura-back" for link in page.links), target
            for link in page.links:
                parsed = urlsplit(link.get("href", ""))
                assert "return_to" not in parse_qs(parsed.query), (target, link["href"])
    hostile_query = '"><svg onload="alert(1)">'
    bounded = "/search?" + urlencode({"q": hostile_query, "lang": "en"})
    response = fixture["client"].get(f"/documents/{identifier}", params={"return_to": bounded})
    page = _Page(response.text)
    assert any(link.get("class") == "cura-back" for link in page.links)
    assert not any(any(name.startswith("on") for name in attrs) for _tag, attrs in page.elements)
    back = next(link["href"] for link in page.links if link.get("class") == "cura-back")
    assert parse_qs(urlsplit(back).query)["q"] == [hostile_query]
    assert len(back) <= 4096


def test_missing_publication_evidence_hides_new_without_creating_receipts(
    shell_fixture, tmp_path, monkeypatch
):
    missing = tmp_path / "no-publication-receipt.json"
    monkeypatch.setattr(publication, "default_receipt_path", lambda build: missing)
    assert about.current_about()["publication"]["new"] is False
    assert about.current_about()["publication"]["status"] == "missing"
    _select(shell_fixture, "preview")
    for route in ("/", "/browse", "/management", "/about"):
        response, page = _get(shell_fixture["client"], route)
        assert "data-release-cue" not in response.text
        assert not any(
            "cura-new" in attrs.get("class", "").split() for _tag, attrs in page.elements
        )
    assert not missing.exists()
