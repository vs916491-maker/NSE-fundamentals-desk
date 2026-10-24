"""NSE HTTP client with cookie warm-up. Prefers curl_cffi (browser TLS fingerprint)."""
import time, json, logging

log = logging.getLogger("nse")

try:
    from curl_cffi import requests as _req
    _IMPERSONATE = {"impersonate": "chrome"}
except Exception:  # pragma: no cover
    import requests as _req
    _IMPERSONATE = {}

BASE = "https://www.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
}


class NSE:
    def __init__(self):
        self.s = _req.Session(**_IMPERSONATE)
        self.s.headers.update(HEADERS)
        self.warm()

    def warm(self):
        for url in (BASE, BASE + "/companies-listing/corporate-filings-announcements"):
            try:
                self.s.get(url, timeout=20)
            except Exception as e:
                log.warning("warm-up %s failed: %s", url, e)
            time.sleep(1)

    def get(self, path, params=None, raw=False, tries=4):
        url = path if path.startswith("http") else BASE + path
        last = None
        for i in range(tries):
            try:
                r = self.s.get(url, params=params, timeout=40)
                if r.status_code == 200:
                    if raw:
                        return r.content
                    txt = r.text.strip()
                    return json.loads(txt) if txt else None
                last = f"HTTP {r.status_code}"
                if r.status_code in (401, 403):
                    self.warm()
            except Exception as e:
                last = repr(e)
            time.sleep(2 * (i + 1))
        raise RuntimeError(f"{url} failed: {last}")
