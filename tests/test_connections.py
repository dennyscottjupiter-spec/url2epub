from core.connections import TARGETS, check, check_all


class FakeResp:
    def __init__(self, status):
        self.status_code = status
        self.closed = False

    def close(self):
        self.closed = True


def fake_get(status, seen=None):
    def get(url, **kwargs):
        if seen is not None:
            seen.append((url, kwargs))
        return FakeResp(status)
    return get


def test_200_is_ok_and_sends_probe_headers():
    seen = []
    p = check("n", "https://x.test/", get=fake_get(200, seen))
    assert p.ok and p.status == 200 and p.error == ""
    url, kwargs = seen[0]
    assert kwargs["headers"]["User-Agent"] == "url2epub-desktop/1.0"
    assert kwargs["stream"] is True


def test_404_still_counts_as_reachable():
    p = check("n", "https://x.test/", get=fake_get(404))
    assert p.ok and p.status == 404


def test_503_is_not_ok():
    p = check("n", "https://x.test/", get=fake_get(503))
    assert not p.ok and p.status == 503


def test_exception_is_not_ok_with_short_error():
    def boom(url, **kwargs):
        raise ConnectionError("no route " + "x" * 300)

    p = check("n", "https://x.test/", get=boom)
    assert not p.ok and p.status is None
    assert p.error.startswith("ConnectionError: no route ")
    assert len(p.error) <= len("ConnectionError: ") + 120


def test_check_all_keeps_target_order():
    targets = [("A", "https://a.test/"), ("B", "https://b.test/"), ("C", "https://c.test/")]

    def get(url, **kwargs):
        return FakeResp(503 if "b.test" in url else 200)

    probes = check_all(get=get, targets=targets)
    assert [p.name for p in probes] == ["A", "B", "C"]
    assert [p.ok for p in probes] == [True, False, True]


def test_default_targets_cover_five_services():
    assert len(TARGETS) == 5
