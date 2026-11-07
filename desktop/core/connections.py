# ---
# purpose: Reachability probes for the sites the converter depends on
# exports: TARGETS, Probe, check(), check_all()
# depends: requests
# gotcha: any HTTP answer below 500 counts as reachable; a 404 still proves the network path works
# ---
import concurrent.futures
import time
from dataclasses import dataclass

import requests

TARGETS = [
    ("Internet (example.com)", "https://example.com/"),
    ("Wayback Machine", "https://archive.org/wayback/available?url=example.com"),
    ("archive.today", "https://archive.ph/"),
    ("Jina Reader", "https://r.jina.ai/"),
    ("X syndication", "https://cdn.syndication.twimg.com/tweet-result?id=20&token=a"),
]


@dataclass
class Probe:
    name: str
    url: str
    ok: bool
    status: int | None = None
    ms: int = 0
    error: str = ""


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def check(name, url, timeout=8.0, get=requests.get) -> Probe:
    t0 = time.monotonic()
    try:
        r = get(url, timeout=timeout, headers={"User-Agent": "url2epub-desktop/1.0"}, stream=True)
    except Exception as e:
        return Probe(name, url, False, ms=_ms(t0), error=f"{type(e).__name__}: {str(e)[:120]}")
    status = r.status_code
    r.close()
    return Probe(name, url, status < 500, status=status, ms=_ms(t0))


def check_all(timeout=8.0, get=requests.get, targets=TARGETS) -> list[Probe]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
        futures = [pool.submit(check, name, url, timeout, get) for name, url in targets]
        return [f.result() for f in futures]
