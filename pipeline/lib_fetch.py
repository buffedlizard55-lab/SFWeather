"""Shared fetch helpers for the SFWeather pipeline.

Every network call in this project goes through :func:`get` so that the exact
URL, HTTP status, byte count, SHA-256 and retrieval timestamp can be recorded
in the provenance manifest.  Nothing in this repository is ever hand-typed:
if a value is not in the manifest, it is not in the site.

The pipeline runs on GitHub Actions runners, which have unrestricted egress to
NOAA/NWS/NCEI/CPC hosts.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

# NOAA asks that automated clients identify themselves.
USER_AGENT = (
    "SFWeather/1.0 (open-source project; +https://github.com/buffedlizard55-lab/SFWeather) "
    "python-urllib"
)

DEFAULT_TIMEOUT = 120
_RETRIES = 3


# Encodings to try, in order, for publishers whose CSV exports are not
# consistently UTF-8.  NCEI's Storm Events detail files are the known case:
# curly quotes and degree signs appear as single CP1252 bytes.
CSV_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def decode_text(body, encodings=CSV_ENCODINGS):
    """Decode a publisher's text body, preferring strict UTF-8.

    Returns ``(text, encoding_used)``.  Decoding with ``errors="replace"``
    straight away - which this pipeline used to do - silently turns every
    non-UTF-8 byte into U+FFFD and commits the corrupted text to the dataset.
    Trying UTF-8 strictly first, then the publisher's legacy encoding, keeps
    the published characters intact; the caller records which encoding was
    used so the substitution is never hidden.
    """
    if body is None:
        return "", "none"
    for enc in encodings:
        try:
            return body.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode(encodings[-1], "replace"), encodings[-1] + "+replace"


#: Characters that are, by definition, already-destroyed content.  U+FFFD is
#: the Unicode replacement character - a publisher's file that contains one has
#: already lost the original character before this project saw the bytes, and no
#: amount of re-decoding brings it back.  NUL carries no content and breaks
#: consumers.
#:
#: This project does not guess at what the lost character was (NCEI's Storm
#: Events file for 2022 contains U+FFFD where a typographic inch mark belongs in
#: the 31 Dec 2022 narrative; replacing it with a double quote would be a guess
#: dressed up as a repair).  It removes the characters and publishes how many
#: were removed, so the text a reader sees is verbatim-minus-the-lost-glyphs and
#: the loss is disclosed rather than hidden.
UNREPRESENTABLE = "\ufffd\u0000"


def strip_unrepresentable(text):
    """Remove already-lost characters from published text.

    Returns ``(clean_text, removed_count, contexts)`` where ``contexts`` holds
    up to five short verbatim snippets around each removal, so a reviewer can
    see exactly which sentence was affected and check it against the source file.
    """
    if not text:
        return text, 0, []
    if not any(ch in text for ch in UNREPRESENTABLE):
        return text, 0, []
    removed, contexts = 0, []
    out = []
    for ch in text:
        if ch in UNREPRESENTABLE:
            removed += 1
            continue
        out.append(ch)
    clean = "".join(out)
    # The snippets that document the loss are written with a VISIBLE marker
    # rather than the raw character.  Two reasons: the ledger check that nothing
    # published contains U+FFFD stays absolute (no exception carve-out for the
    # evidence block, which would be a hole big enough to drive the original bug
    # through), and a reader of the JSON sees "<U+FFFD>" instead of a glyph that
    # renders as a black diamond in half the terminals on earth.
    for i, ch in enumerate(text):
        if ch in UNREPRESENTABLE and len(contexts) < 5:
            snippet = text[max(0, i - 40):i + 40]
            for bad in UNREPRESENTABLE:
                snippet = snippet.replace(bad, "<U+%04X>" % ord(bad))
            contexts.append(snippet)
    return clean, removed, contexts


class FetchResult:
    """Outcome of one HTTP GET."""

    def __init__(self, url, ok, status=None, body=None, error=None,
                 content_type=None, elapsed=None):
        self.url = url
        self.ok = ok
        self.status = status
        self.body = body            # bytes, or None on failure
        self.error = error
        self.content_type = content_type
        self.elapsed = elapsed
        self.retrieved_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # -- convenience -----------------------------------------------------
    @property
    def size(self):
        return len(self.body) if self.body is not None else 0

    @property
    def sha256(self):
        if self.body is None:
            return None
        return hashlib.sha256(self.body).hexdigest()

    def text(self, encoding="utf-8", errors="replace"):
        if self.body is None:
            return ""
        return self.body.decode(encoding, errors)

    def provenance(self, note=None, **extra):
        """A provenance record suitable for inclusion in the manifest."""
        rec = {
            "url": self.url,
            "http_status": self.status,
            "ok": self.ok,
            "bytes": self.size,
            "sha256": self.sha256,
            "content_type": self.content_type,
            "retrieved_utc": self.retrieved_utc,
            "elapsed_s": round(self.elapsed, 3) if self.elapsed is not None else None,
        }
        if self.error:
            rec["error"] = self.error
        if note:
            rec["note"] = note
        rec.update(extra)
        return rec

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<FetchResult {self.status} {self.size}B {self.url}>"


def get(url, timeout=DEFAULT_TIMEOUT, headers=None, retries=_RETRIES,
        accept=None, sleep=3.0):
    """GET *url* and return a :class:`FetchResult`.  Never raises."""
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if accept:
        hdrs["Accept"] = accept
    if headers:
        hdrs.update(headers)

    last = None
    for attempt in range(1, retries + 1):
        started = time.time()
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type")
                return FetchResult(url, True, resp.status, body, None, ctype,
                                   time.time() - started)
        except urllib.error.HTTPError as exc:
            body = None
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001
                pass
            last = FetchResult(url, False, exc.code, body,
                               f"HTTP {exc.code} {exc.reason}",
                               None, time.time() - started)
        except Exception as exc:  # noqa: BLE001 - network flakiness is expected
            last = FetchResult(url, False, None, None,
                               f"{type(exc).__name__}: {exc}", None,
                               time.time() - started)
        if attempt < retries:
            time.sleep(sleep * attempt)
    return last


def get_json(url, **kwargs):
    """GET *url* and parse JSON.  Returns ``(obj, FetchResult)``."""
    res = get(url, accept="application/geo+json, application/ld+json, application/json",
              **kwargs)
    if not res.ok or not res.body:
        return None, res
    try:
        return json.loads(res.text()), res
    except Exception as exc:  # noqa: BLE001
        res.error = f"JSON parse error: {exc}"
        res.ok = False
        return None, res


def get_text(url, **kwargs):
    """GET *url* and return ``(text, FetchResult)``."""
    res = get(url, **kwargs)
    return res.text(), res


def gunzip(data: bytes) -> bytes:
    """Decompress gzip bytes (handles the members' concatenation)."""
    return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data)


def save_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def iso_utc(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
