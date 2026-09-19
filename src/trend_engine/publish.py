"""Public views of engine data: source-neutral shapes + optional AES-GCM encryption.

The dashboard never needs to know *where* a signal came from, so everything published
(static site files and the dashboard API) goes through these views, which drop provider
names, publishers and per-source status. Static files are additionally encrypted
(AES-256-GCM, key injected into the built page) so the raw JSON isn't casually readable.
Note: the key ships inside the page, so this hides data from casual inspection — it is not
access control.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VIDEO_SOURCES = ("youtube",)
NEWS_SOURCES = ("google_news",)


def public_report(r: dict[str, Any]) -> dict[str, Any]:
    content = r.get("content", {})
    return {
        "region": r["region"],
        "region_name": r["region_name"],
        "generated_at": r["generated_at"],
        "clusters": [
            {
                "label": c["label"],
                "key": c["key"],
                "score": c["score"],
                "status": c.get("status"),
                "rank_change": c.get("rank_change"),
                "volume": c.get("volume"),
                "category": c.get("category") or "기타",
                "related": c.get("related", []),
                "mentions": [t for titles in c.get("mentions", {}).values() for t in titles],
            }
            for c in r["clusters"]
        ],
        "videos": [
            {"title": v["keyword"], "url": v.get("url"), "category": v.get("category"), "views": v.get("volume")}
            for s in VIDEO_SOURCES for v in content.get(s, [])
        ],
        "news": [{"title": n["keyword"], "url": n.get("url")} for s in NEWS_SOURCES for n in content.get(s, [])],
    }


def public_segments(s: dict[str, Any]) -> dict[str, Any]:
    keep = ("keywords", "segments", "affinity", "relative", "top_by_segment", "labels", "period", "synthetic")
    return {k: s[k] for k in keep if k in s}


def public_shopping(d: dict[str, Any]) -> dict[str, Any]:
    return {k: d[k] for k in ("period", "categories", "segments", "by_segment", "offline") if k in d}


def public_meta(m: dict[str, Any]) -> dict[str, Any]:
    return {"regions": m["regions"], "offline": m.get("offline", False), "static": m.get("static", False)}


# --- encryption ---------------------------------------------------------------------------
def data_key() -> bytes:
    """32-byte key from TREND_ENGINE_DATA_KEY (64 hex chars). Stable across builds so a cached
    page can still read freshly deployed data."""
    hex_key = os.environ.get("TREND_ENGINE_DATA_KEY", "").strip()
    if hex_key:
        key = bytes.fromhex(hex_key)
        if len(key) != 32:
            raise ValueError("TREND_ENGINE_DATA_KEY must be 64 hex chars (32 bytes)")
        return key
    return AESGCM.generate_key(bit_length=256)


def encrypt(obj: Any, key: bytes) -> str:
    """base64(iv[12] || ciphertext+tag) — matches the WebCrypto AES-GCM decrypt in index.html."""
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), None)
    return base64.b64encode(iv + ct).decode()


def decrypt(blob: str, key: bytes) -> Any:
    raw = base64.b64decode(blob)
    return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], None))
