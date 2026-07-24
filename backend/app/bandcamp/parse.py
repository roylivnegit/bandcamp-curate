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
_TRALBUM_RE = re.compile(r'data-tralbum="([^"]*)"')
_BAND_RE = re.compile(r'data-band="([^"]*)"')
_COLLECTORS_RE = re.compile(r'id="collectors-data"[^>]*data-blob="([^"]*)"')
_TAG_RE = re.compile(r'<a[^>]*class="tag"[^>]*>([^<]+)</a>')
# Supporter profile links in the album DOM: <a class="fan pic"
# href="https://bandcamp.com/<user>?from=fanthanks">. Fallback when the
# structured #collectors-data blob is absent (it carries fan_id too).
_FAN_PIC_RE = re.compile(r'class="fan pic"\s+href="https://bandcamp\.com/([^"?/]+)')


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


@dataclass(slots=True)
class ParsedTrack:
    track_id: int
    title: str | None = None
    track_num: int | None = None
    duration: float | None = None
    url: str | None = None


@dataclass(slots=True)
class ParsedAlbum:
    album_id: int
    band: ParsedBand
    title: str | None = None
    url: str | None = None
    art_id: int | None = None
    tags: list[str] = field(default_factory=list)
    tracks: list[ParsedTrack] = field(default_factory=list)


@dataclass(slots=True)
class ParsedSupporter:
    username: str
    fan_id: int | None = None
    name: str | None = None
    url: str | None = None


@dataclass(slots=True)
class AlbumSupporters:
    supporters: list[ParsedSupporter] = field(default_factory=list)
    album_id: int | None = None
    album_url: str | None = None
    more_available: bool = False
    last_token: str | None = None


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


def _decode_attr(match: re.Match[str] | None) -> dict | None:
    """Decode an HTML-entity-encoded JSON attribute value, or None if absent."""
    if not match:
        return None
    return json.loads(html.unescape(match.group(1)))


def band_url_from_album_url(album_url: str | None) -> str | None:
    """Derive a band's page URL from an album/track URL (strip the path)."""
    if not album_url:
        return None
    m = re.match(r"(https?://[^/]+)", album_url)
    return m.group(1) if m else None


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


def _iter_collection_payloads(node: object) -> "list[dict]":
    """Recursively find `collection_items`-shaped dicts anywhere in a capture tree.

    Nimble's `network_capture` nests intercepted XHR bodies at an unstable depth, and
    a body may arrive as a dict or as a JSON string. We locate any object that looks
    like a `collection_items` response (an `items` list plus a `last_token`), so the
    parser is robust to the exact wrapper shape (which we haven't pinned to a live
    sample yet).
    """
    found: list[dict] = []
    if isinstance(node, str):
        stripped = node.strip()
        if stripped.startswith("{") and ("collection_items" in node or '"items"' in node):
            try:
                found.extend(_iter_collection_payloads(json.loads(stripped)))
            except (ValueError, TypeError):
                pass
    elif isinstance(node, dict):
        if isinstance(node.get("items"), list) and (
            "last_token" in node or "more_available" in node
        ):
            found.append(node)
        for v in node.values():
            found.extend(_iter_collection_payloads(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_iter_collection_payloads(v))
    return found


def parse_collection_items_capture(
    data: dict,
) -> tuple[list[ParsedItem], str | None, bool]:
    """Parse `collection_items` XHR bodies out of a Nimble capture `data` payload.

    Scans `data["network_capture"]` for intercepted collection-API responses and
    flattens them into (items, last_token, more_available). `last_token` is taken
    from the deepest page seen so pagination can continue from it.
    """
    payloads = _iter_collection_payloads(data.get("network_capture"))
    items: list[ParsedItem] = []
    last_token: str | None = None
    more = False
    for p in payloads:
        page_items, token, page_more = parse_collection_items_api(p)
        items.extend(page_items)
        if token:
            last_token = token
        more = more or page_more
    return items, last_token, more


def parse_album_page(page_html: str) -> ParsedAlbum:
    """Parse an album (or track) page's `data-tralbum` + `data-band` + tag links.

    Bandcamp embeds the album in `data-tralbum` (id, url, item_type, `current.title`,
    `trackinfo[]`) and the band in `data-band` (id, name). Genre tags are plain DOM
    anchors (`<a class="tag">`). The band's page URL is derived from the album URL.
    """
    tralbum = _decode_attr(_TRALBUM_RE.search(page_html))
    if tralbum is None:
        raise ValueError("no data-tralbum blob found in HTML")
    band_blob = _decode_attr(_BAND_RE.search(page_html)) or {}
    current = tralbum.get("current") or {}

    url = tralbum.get("url")
    band = ParsedBand(
        bandcamp_id=band_blob.get("id") or current.get("band_id"),
        name=band_blob.get("name") or tralbum.get("artist"),
        url=band_url_from_album_url(url),
    )

    base = band.url
    tracks: list[ParsedTrack] = []
    for ti in tralbum.get("trackinfo") or []:
        track_id = ti.get("track_id") or ti.get("id")
        if track_id is None:
            continue
        link = ti.get("title_link")
        tracks.append(
            ParsedTrack(
                track_id=track_id,
                title=ti.get("title"),
                track_num=ti.get("track_num"),
                duration=ti.get("duration"),
                url=f"{base}{link}" if base and link else None,
            )
        )

    # Genre tags: normalized to lowercase, de-duped, order preserved.
    seen: set[str] = set()
    tags: list[str] = []
    for raw in _TAG_RE.findall(page_html):
        tag = raw.strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)

    return ParsedAlbum(
        album_id=tralbum["id"],
        band=band,
        title=current.get("title") or tralbum.get("artist"),
        url=url,
        art_id=tralbum.get("art_id"),
        tags=tags,
        tracks=tracks,
    )


def parse_album_supporters(page_html: str) -> AlbumSupporters:
    """Parse an album page's supporters ("supported by" collectors).

    Prefers the structured `#collectors-data` blob (`thumbs[]` with `fan_id`,
    `username`, `name`; `more_thumbs_available`; per-thumb pagination `token`).
    Falls back to scraping `<a class="fan pic">` profile links (username only)
    when that blob is absent.
    """
    tralbum = _decode_attr(_TRALBUM_RE.search(page_html)) or {}
    album_id = tralbum.get("id")
    album_url = tralbum.get("url")

    blob = _decode_attr(_COLLECTORS_RE.search(page_html))
    if blob is not None:
        thumbs = blob.get("thumbs") or []
        supporters = [
            ParsedSupporter(
                username=t["username"],
                fan_id=t.get("fan_id"),
                name=t.get("name"),
                url=f"https://bandcamp.com/{t['username']}",
            )
            for t in thumbs
            if t.get("username")
        ]
        last_token = thumbs[-1].get("token") if thumbs else None
        return AlbumSupporters(
            supporters=supporters,
            album_id=album_id,
            album_url=album_url,
            more_available=bool(blob.get("more_thumbs_available")),
            last_token=last_token,
        )

    # Fallback: DOM fan-pic anchors (username only, no fan_id).
    seen: set[str] = set()
    supporters = []
    for user in _FAN_PIC_RE.findall(page_html):
        if user not in seen:
            seen.add(user)
            supporters.append(
                ParsedSupporter(username=user, url=f"https://bandcamp.com/{user}")
            )
    return AlbumSupporters(
        supporters=supporters, album_id=album_id, album_url=album_url
    )
