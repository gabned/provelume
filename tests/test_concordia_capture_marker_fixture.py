import pytest

from scripts.concordia_capture_marker_fixture import marked, validate_binding


def test_marker_wrapper_preserves_return_and_exception_and_always_closes():
    events = []
    assert marked(lambda a, *, b: a + b, 1, 2, events.append)(3, b=4) == 7
    assert events == [1, 2]
    error = OSError("synthetic original error")

    def fail():
        raise error

    with pytest.raises(OSError) as observed:
        marked(fail, 3, 4, events.append)()
    assert observed.value is error and events == [1, 2, 3, 4]


def test_binding_requires_exact_raw_window_identity_clock_and_real_capture_checks():
    fixture = {"source": "a" * 40, "pid": 11, "tid": 11,
               "clock_before": {"mono_before": 0, "mono_after": 10, "boot": 10},
               "clock_after": {"mono_before": 90, "mono_after": 110, "boot": 100},
               "markers": [{"code": code, "before": stamp - 1, "after": stamp + 1}
                           for code, stamp in [(9, 5), (1, 10), (2, 20),
                                               (3, 30), (4, 40), (10, 50)]],
               "probe": {"preserved": True, "search_found": True, "product_dispatch_blocked": True}}
    rows = [["M", stamp, 11, code] for code, stamp in
            [(9, 5), (1, 10), (2, 20), (3, 30), (4, 40), (10, 50)]] + [["X", 90, 11]]
    assert validate_binding(rows, fixture)["status"] == "CAPTURE_WINDOW_BINDING_OBSERVED"
    for bad in [rows[1:], [["T", *r[1:]] if r[0] == "M" else r for r in rows],
                [rows[1], rows[0], *rows[2:]]]:
        with pytest.raises(ValueError):
            validate_binding(bad, fixture)
    fixture["probe"]["preserved"] = False
    with pytest.raises(ValueError, match="semantic check"):
        validate_binding(rows, fixture)
