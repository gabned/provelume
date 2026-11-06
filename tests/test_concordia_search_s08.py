"""Search B contracts against real synthetic search; browser focus is separate."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from test_concordia_search_inputs import Page, canonical, filters
from test_concordia_search_inputs import search_fixture as search_fixture

from provelume.i18n import translator
from provelume.instance_lifecycle import InstanceLifecycleBusy
from provelume.search_presentation import media_type_label, type_options
from provelume.service import ProvelumeInstance


class SearchPage(Page):
    def __init__(self, text):
        self.options = {}
        self.option = None
        super().__init__(text)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "option":
            self.option = dict(attrs).get("value", "")
            self.options[self.option] = ""

    def handle_data(self, data):
        if self.option is not None:
            self.options[self.option] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self.option = None

    def ids(self):
        return {a["id"]: a for _, a in self.elements if "id" in a}


@pytest.mark.parametrize("mime,label", [
    ("application/pdf", "PDF"),
    ("text/plain", "Text"),
    ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Spreadsheet (XLSX)"),
    ("application/vnd.oasis.opendocument.spreadsheet", "Spreadsheet (ODS)"),
    ("message/rfc822", "Email (EML)"),
    ("image/png", "Image (PNG)"),
    ("application/octet-stream", "Other file (application/octet-stream)"),
    ("application/x-new-format", "Other file (application/x-new-format)"),
    ("TEXT/PLAIN", "Other file (TEXT/PLAIN)"),
])
def test_type_labels_keep_distinct_formats_and_unknown_identity(mime, label):
    assert media_type_label(mime, translator("en")) == label


def test_options_keep_inventory_and_an_unavailable_selected_type():
    inventory = ["text/plain", "application/x-first"]
    options = type_options(inventory, "application/x-second", translator("en"))
    assert [x["value"] for x in options] == [*inventory, "application/x-second"]
    assert options[-2]["label"] != options[-1]["label"]
    assert inventory == ["text/plain", "application/x-first"]


@pytest.mark.parametrize("language", ["en", "it", "de", "es", "fr", "pt", "ro"])
def test_both_layouts_show_complete_localized_type_and_recovery_copy(search_fixture, language):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    response = client.get("/search", params={"lang": language, "q": "s08nomatch",
                                             "media_type": "text/plain"})
    assert response.status_code == 200
    page = SearchPage(response.text)
    t = translator(language)
    assert page.options["text/plain"] == t("search.type.text")
    assert t("search.edit") in response.text and t("search.remove_filters") in response.text
    assert page.ids()["search-type"]["aria-describedby"] == "search-type-details"
    assert 'id="search-type-details"' in response.text and "text/plain" in response.text
    assert (canonical(instance), manager.path.read_bytes()) == before


@pytest.mark.parametrize("mime", [
    "application/pdf", "application/x-new-type", 'application/x-\"><img src=x onerror="alert(1)">',
])
def test_selected_type_is_retained_escaped_and_sent_unchanged(search_fixture, monkeypatch, mime):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    calls = []
    original = ProvelumeInstance.search

    def observed(self, query, **kwargs):
        calls.append((query, kwargs["media_type"]))
        return original(self, query, **kwargs)

    monkeypatch.setattr(ProvelumeInstance, "search", observed)
    response = client.get("/search", params={"q": "  s08nomatch  ", "lang": "en",
                                             "media_type": mime})
    assert response.status_code == 200
    page = SearchPage(response.text)
    assert calls == [("s08nomatch", mime)]
    assert page.options[mime] == media_type_label(mime, translator("en"))
    assert any(x.get("value") == mime and "selected" in x for x in page.tags("option"))
    assert not any(a.get("src") == "x" for a in page.tags("img"))
    assert not any("onerror" in attrs for _, attrs in page.elements)
    assert (canonical(instance), manager.path.read_bytes()) == before


def test_empty_recovery_retains_words_context_and_clears_only_filters(search_fixture, monkeypatch):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("search navigation admitted OCR work")

    monkeypatch.setattr(ProvelumeInstance, "queue_ocr", forbidden)
    monkeypatch.setattr(ProvelumeInstance, "run_ocr_job", forbidden)
    words = "MiXeD  s08nomatch & words"
    response = client.get("/search", params={**filters(instance), "q": "  " + words + "  "})
    assert response.status_code == 200
    page = SearchPage(response.text)
    assert page.ids()["search-edit"]["href"] == "#search-query"
    assert page.ids()["search-query"]["value"] == words
    assert instance.list_sources()[0]["name"] in response.text
    target = page.ids()["search-remove-filters"]["href"]
    assert urlsplit(target).path == "/search"
    assert parse_qs(urlsplit(target).query) == {"q": [words], "lang": ["en"]}
    cleared = client.get(target)
    assert cleared.status_code == 200
    after = SearchPage(cleared.text)
    assert after.ids()["search-query"]["value"] == words
    assert "search-remove-filters" not in after.ids()
    assert after.inputs()["date_from"]["value"] == after.inputs()["date_to"]["value"] == ""
    assert not any("selected" in option for option in after.tags("option"))
    assert (canonical(instance), manager.path.read_bytes()) == before


def test_words_alone_offer_edit_without_a_misleading_filter_removal(search_fixture):
    _, _, client = search_fixture
    page = SearchPage(client.get("/search", params={"q": "s08nomatch", "lang": "en"}).text)
    assert "search-edit" in page.ids() and "search-remove-filters" not in page.ids()


@pytest.mark.parametrize("words,removable", [
    ("x" * 500, True), ("x" * 501, False), ("字" * 500, False), (r"some\words", False),
])
def test_recovery_never_silently_drops_words_at_existing_context_bounds(
    search_fixture, words, removable,
):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    response = client.get("/search", params={"q": words, "lang": "en", "media_type": "text/plain"})
    assert response.status_code == 200
    page = SearchPage(response.text)
    assert page.ids()["search-query"]["value"] == words
    assert page.ids()["search-edit"]["href"] == "#search-query"
    if removable:
        href = page.ids()["search-remove-filters"]["href"]
        assert parse_qs(urlsplit(href).query) == {"q": [words], "lang": ["en"]}
        recovered = SearchPage(client.get(href).text)
        assert recovered.ids()["search-query"]["value"] == words
    else:
        assert "search-remove-filters" not in page.ids()
        assert "Shorten or correct the search text before removing filters." in response.text
    assert (canonical(instance), manager.path.read_bytes()) == before


def test_friendly_type_chip_removal_preserves_other_filters(search_fixture, request):
    instance, _, client = search_fixture
    parameters = {**filters(instance), "q": "s08nomatch"}
    page = SearchPage(client.get("/search", params=parameters).text)
    chips = [a for a in page.tags("a") if a.get("aria-label", "").startswith("Remove filter: Type")]
    if request.node.callspec.params["search_fixture"] == "current":
        assert chips == []  # Current retains its existing presentation.
    else:
        assert len(chips) == 1
        assert chips[0]["aria-label"].endswith("Text") and chips[0]["title"] == "text/plain"
        assert parse_qs(urlsplit(chips[0]["href"]).query) == {
            k: [v] for k, v in parameters.items() if k != "media_type"}


@pytest.mark.parametrize("state", ["initial", "error", "pending", "matching"])
def test_recovery_does_not_misrepresent_other_search_states(search_fixture, monkeypatch, state):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    params = {**filters(instance), "q": "orchid"}
    if state == "initial":
        params["q"] = "  "
    elif state == "error":
        params["date_from"] = "invalid"
    elif state == "pending":
        def busy(*args, **kwargs):
            raise InstanceLifecycleBusy("synthetic index writer busy")
        monkeypatch.setattr(ProvelumeInstance, "search", busy)
    response = client.get("/search", params=params)
    assert response.status_code == (400 if state == "error" else 200)
    page = SearchPage(response.text)
    assert "search-edit" not in page.ids() and "search-remove-filters" not in page.ids()
    if state != "matching":
        assert "No matching documents." not in response.text
    assert (canonical(instance), manager.path.read_bytes()) == before


def test_language_choice_and_return_validation_remain_intact(search_fixture, monkeypatch):
    instance, manager, client = search_fixture
    before = canonical(instance), manager.path.read_bytes()
    monkeypatch.setattr("provelume.catalog_registry.locale.getlocale", lambda: ("it_IT", "UTF-8"))
    response = client.get("/search", params={"q": "s08nomatch", "lang": "system",
                                             "media_type": "text/plain",
                                             "return_to": "https://hostile.invalid/"})
    assert response.status_code == 200
    page = SearchPage(response.text)
    assert page.options["text/plain"] == "Testo" and "Modifica ricerca" in response.text
    target = page.ids()["search-remove-filters"]["href"]
    assert parse_qs(urlsplit(target).query) == {"q": ["s08nomatch"], "lang": ["it"]}
    assert not any(a.get("href", "").startswith("https://hostile.invalid/") for a in page.tags("a"))
    assert (canonical(instance), manager.path.read_bytes()) == before
