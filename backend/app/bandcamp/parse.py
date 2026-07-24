"""Parse Bandcamp's Nimble-fetched output into normalized records.

Bandcamp embeds a large JSON blob in the fan page as `<div id="pagedata"
data-blob="&hellip;">` (HTML-entity-encoded). Its `item_cache.collection` holds the
first page of owned items and `following_bands` the artists/labels the fan follows;
`collection_data.last_token` + `fan_data.fan_id` drive pagination via the
`collection_items` API, whose item objects share the same shape as the cache values.

These are pure functions (no I/O) so they can be unit-tested against saved fixtures.
"""

import html
import json
import re
from dataclasses import dataclass, field

_PAGEDATA_RE = re.compile(r'id="pagedata"[^>]*data-blob="([^"]*)"')


# ── Normalized records ───────────────────────────────────────────────────────


@dataclass(slots=True)
class ParsedBand:
    bandcamp_id: int | None
    name: str | None = None
    url: str | None = None


@dataclass(slots=True)
class ParsedItem:
    item_id: int
    item_type: str  # "album" | "track"
    band: ParsedBand
    title: str | None = None
    url: str | None = None
    album_id: int | None = None  # parent album (tracks only)
    album_title: str | None = None
    art_id: int | None = None
    also_collected_count: int | None = None


@dataclass(slots=True)
class ParsedFan:
    fan_id: int
    username: str
    name: str | None = None
    url: str | None = None


@dataclass(slots=True)
class FanCollection:
    fan: ParsedFan
    items: list[ParsedItem] = field(default_factory=list)
    follows: list[ParsedBand] = field(default_factory=list)
    total_count: int | None = None
    last_token: str | None = None
    more_available: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────


def band_url_from_hints(hints: dict | None) -> str | None:
    if not hints:
        return None
    if hints.get("custom_domain") and hints.get("custom_domain_verified"):
        return f"https://{hints['custom_domain']}"
    subdomain = hints.get("subdomain")
    return f"https://{subdomain}.bandcamp.com" if subdomain else None


def extract_pagedata_blob(page_html: str) -> dict:
    """Extract and decode the `#pagedata` JSON blob from fan-page HTML."""
    match = _PAGEDATA_RE.search(page_html)
    if not match:
        raise ValueError("no #pagedata data-blob found in HTML")
    return json.loads(html.unescape(match.group(1)))


# ── Parsers ──────────────────────────────────────────────────────────────────


def parse_collection_item(obj: dict) -> ParsedItem:
    """Map one collection item object (from the page cache or the API) to ParsedItem."""
    item_type = "album" if obj.get("item_type") == "album" else "track"
    band = ParsedBand(
        bandcamp_id=obj.get("band_id"),
        name=obj.get("band_name"),
        url=band_url_from_hints(obj.get("url_hints")),
    )

    album_id: int | None = None
    album_title: str | None = None
    if item_type == "track":
        album_id = obj.get("album_id")
        player_album = (obj.get("player_data") or {}).get("album") or {}
        if isinstance(player_album, dict):
            album_title = player_album.get("title")
            album_id = album_id or player_album.get("id")

    return ParsedItem(
        item_id=obj["item_id"],
        item_type=item_type,
        band=band,
        title=obj.get("item_title"),
        url=obj.get("item_url"),
        album_id=album_id,
        album_title=album_title,
        art_id=obj.get("item_art_id"),
        also_collected_count=obj.get("also_collected_count"),
    )


def parse_fan_page(page_html: str) -> FanCollection:
    """Parse a fan page's embedded blob into a FanCollection (first page + follows)."""
    blob = extract_pagedata_blob(page_html)
    fd = blob.get("fan_data") or {}
    fan = ParsedFan(
        fan_id=fd["fan_id"],
        username=fd["username"],
        name=fd.get("name"),
        url=fd.get("trackpipe_url"),
    )

    cache = blob.get("item_cache") or {}
    collection = cache.get("collection") or {}
    items = [parse_collection_item(v) for v in collection.values()]

    following = cache.get("following_bands") or {}
    follows = [
        ParsedBand(
            bandcamp_id=v.get("band_id"),
            name=v.get("name"),
            url=band_url_from_hints(v.get("url_hints")),
        )
        for v in following.values()
    ]

    cd = blob.get("collection_data") or {}
    last_token = cd.get("last_token")
    return FanCollection(
        fan=fan,
        items=items,
        follows=follows,
        total_count=blob.get("collection_count") or cd.get("item_count"),
        last_token=last_token,
        more_available=bool(last_token),
    )


def parse_collection_items_api(payload: dict) -> tuple[list[ParsedItem], str | None, bool]:
    """Parse a `collection_items` API response → (items, last_token, more_available)."""
    items = [parse_collection_item(o) for o in payload.get("items", [])]
    return items, payload.get("last_token"), bool(payload.get("more_available"))
