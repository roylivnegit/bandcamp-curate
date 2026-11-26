"""One search box over everything the signed-in user can reach.

The UI behind this is the Ctrl/Cmd+K palette, which used to list only
navigation commands it already had in memory. Searching the actual *content*
can't work that way: a user's feed is tens of thousands of recommendations
spread over every scan they own, and the palette is not going to download them
to filter locally. So the matching happens here.

Two things are searched, each scoped to the caller:

- **collection** — what they own, wishlisted or liked, by title or artist.
- **feed** — recommendations in any scan they own, by title or artist.

Deliberately *not* searched: a user's **scans**. The palette fetches the whole
scan list when it opens — there are a handful of them — so it already filters
those by name locally, with no request and from the first keystroke. Returning
them here too put every matching scan in the list twice. This endpoint covers
exactly what the client cannot hold in memory.

Also not searched: the shared graph (`bands`/`albums`/`tracks` as
such). Those tables are global — every tenant's crawl writes into them — so
querying them unscoped would report records the caller has no relationship
with, and leak what other users have been digging through. Every query below
joins back to `users.id` or `users.fan_id`.

Known limit: matching is a plain case-insensitive substring, so it is
accent-sensitive — "bjork" does not find "Björk" here, though the Collection
page's own client-side search does (`frontend/src/lib/collection.ts`
normalizes NFD). Fixing that server-side needs Postgres `unaccent`, which the
SQLite test database has no equivalent for.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.security import get_current_user
from app.bandcamp.art import art_url
from app.db.models import Album, Band, FanItem, Like, Recommendation, Scan, Track, User
from app.db.session import get_session

router = APIRouter(prefix="/api/search", tags=["search"])

# Below this, a query is not worth running: "a" matches most of a collection,
# which is noise in a 6-row list, and `%a%` is a full scan of every joined row
# to produce it. The palette shows its own navigation commands for short
# queries, so this is not a dead end for the user.
MIN_QUERY_LEN = 2

# Per section, not overall — the sections are rendered as separate groups and a
# shared budget would let a big collection crowd the scans out of the list.
DEFAULT_LIMIT = 6
MAX_LIMIT = 25

# `%` and `_` are wildcards inside LIKE, and `\` escapes them. A user typing
# "100%" means the three characters, so neutralise all three before building
# the pattern. Every `.ilike()`/`.like()` below passes escape="\\" to match.
LIKE_SPECIALS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


def _contains(q: str) -> str:
    return f"%{q.translate(LIKE_SPECIALS)}%"


def _starts_with(q: str) -> str:
    return f"{q.translate(LIKE_SPECIALS)}%"


def _prefix_tier(prefix: str, *cols: ColumnElement) -> ColumnElement:
    """0 when any of `cols` starts with the query, else 1 — the sort key that
    puts "Drukqs" above "The Drukqs Remixes" for the query "drukqs".

    Same idea as the palette's own `rankCommands` tiering, kept in SQL because
    the client only ever sees the already-truncated top few rows and so cannot
    re-rank what it was not sent.
    """
    starts = [func.lower(func.coalesce(c, "")).like(prefix, escape="\\") for c in cols]
    return case((or_(*starts), 0), else_=1)


class SearchHit(BaseModel):
    """One result, in whichever of the three sections it came from.

    Raw fields rather than a rendered label: the frontend composes
    "title — artist" and the hint, exactly as it already does for feed cards
    and collection rows, so the API stays free of presentation.
    """

    kind: str  # collection | feed
    title: str | None
    band_name: str | None = None
    item_type: str | None = None
    album_id: int | None = None
    track_id: int | None = None
    url: str | None = None
    art_url: str | None = None
    # `feed` hits only: the scan whose feed this appeared in, which is what the
    # UI labels the row with and falls back to navigating to.
    scan_id: int | None = None
    scan_name: str | None = None
    # `collection` hits only: which of owned/wishlist/liked matched. The same
    # record can be in more than one, same as GET /api/collection.
    sections: list[str] = []


class SearchOut(BaseModel):
    query: str
    collection: list[SearchHit]
    feed: list[SearchHit]
    # True when any section hit its limit. The UI says "more matches" rather
    # than letting a top-6 list read as the whole truth.
    truncated: bool


def _item_hits(
    model: type[FanItem] | type[Like],
    pattern: str,
    prefix: str,
    limit: int,
    *where: ColumnElement[bool],
) -> Select:
    """Collection rows matching title or artist.

    Same album-or-track flattening as `api/collection._items_query` — one
    query serves both `fan_items` and `likes` because for display purposes
    they are the same shape.
    """
    ab = aliased(Band)
    tb = aliased(Band)
    band_name = func.coalesce(ab.name, tb.name)
    title = func.coalesce(Album.title, Track.title)
    return (
        select(
            model.item_type,
            model.album_id,
            model.track_id,
            title.label("title"),
            band_name.label("band_name"),
            func.coalesce(Album.url, Track.url).label("url"),
            func.coalesce(Album.art_id, Track.art_id).label("art_id"),
        )
        .select_from(model)
        .outerjoin(Album, Album.id == model.album_id)
        .outerjoin(Track, Track.id == model.track_id)
        .outerjoin(ab, ab.id == Album.band_id)
        .outerjoin(tb, tb.id == Track.band_id)
        .where(*where)
        .where(or_(title.ilike(pattern, escape="\\"), band_name.ilike(pattern, escape="\\")))
        # `lower(coalesce(...))` for the same dialect reason as the collection
        # endpoint: Postgres and SQLite disagree on NULL placement and on case.
        .order_by(
            _prefix_tier(prefix, title, band_name),
            func.lower(func.coalesce(band_name, "")),
            func.lower(func.coalesce(title, "")),
            model.id,
        )
        .limit(limit)
    )


def _hit_key(row) -> tuple[str, int | None, int | None]:
    return (row.item_type, row.album_id, row.track_id)


async def _collection_hits(
    session: AsyncSession, user: User, pattern: str, prefix: str, limit: int
) -> tuple[list[SearchHit], bool]:
    """Owned, wishlisted and liked, merged into one list of distinct records.

    Unlike GET /api/collection — which returns the three lists separately so
    the page can show per-tab counts — a search result list wants one row per
    record, labelled with every list it is in. A record you liked and then
    bought is one hit reading "owned · liked", not two rows.
    """
    sources: list[tuple[str, Select]] = []
    if user.fan_id is not None:
        sources.append((
            "owned",
            _item_hits(FanItem, pattern, prefix, limit + 1,
                       FanItem.fan_id == user.fan_id, FanItem.is_wishlist.is_(False)),
        ))
        sources.append((
            "wishlist",
            _item_hits(FanItem, pattern, prefix, limit + 1,
                       FanItem.fan_id == user.fan_id, FanItem.is_wishlist.is_(True)),
        ))
    # Likes hang off the app user, not the Bandcamp fan — someone whose
    # collection scan has not run yet has no fan_id but can already have liked
    # things in the feed. Same split as the collection endpoint.
    sources.append(("liked", _item_hits(Like, pattern, prefix, limit + 1, Like.user_id == user.id)))

    merged: dict[tuple[str, int | None, int | None], SearchHit] = {}
    truncated = False
    for section, stmt in sources:
        rows = (await session.execute(stmt)).all()
        if len(rows) > limit:
            truncated = True
            rows = rows[:limit]
        for row in rows:
            hit = merged.get(_hit_key(row))
            if hit is not None:
                if section not in hit.sections:
                    hit.sections.append(section)
                continue
            merged[_hit_key(row)] = SearchHit(
                kind="collection",
                title=row.title,
                band_name=row.band_name,
                item_type=row.item_type,
                album_id=row.album_id,
                track_id=row.track_id,
                url=row.url,
                art_url=art_url(row.art_id),
                sections=[section],
            )
    hits = list(merged.values())
    # Merging three capped lists can overshoot the cap; cutting here keeps the
    # section the size the caller asked for.
    if len(hits) > limit:
        return hits[:limit], True
    return hits, truncated



async def _feed_hits(
    session: AsyncSession, user: User, pattern: str, prefix: str, limit: int
) -> tuple[list[SearchHit], bool]:
    """Recommendations in any scan the caller owns.

    The join to `scans` is the tenant boundary *and* the label: a hit is only
    useful if it says which feed to go and look in.
    """
    ab = aliased(Band)
    tb = aliased(Band)
    band_name = func.coalesce(ab.name, tb.name)
    title = func.coalesce(Album.title, Track.title)
    stmt = (
        select(
            Recommendation.item_type,
            Recommendation.album_id,
            Recommendation.track_id,
            Recommendation.score,
            Scan.id.label("scan_id"),
            Scan.name.label("scan_name"),
            title.label("title"),
            band_name.label("band_name"),
            func.coalesce(Album.url, Track.url).label("url"),
            func.coalesce(Album.art_id, Track.art_id).label("art_id"),
        )
        .select_from(Recommendation)
        .join(Scan, Scan.id == Recommendation.scan_id)
        .outerjoin(Album, Album.id == Recommendation.album_id)
        .outerjoin(Track, Track.id == Recommendation.track_id)
        .outerjoin(ab, ab.id == Album.band_id)
        .outerjoin(tb, tb.id == Track.band_id)
        .where(Scan.user_id == user.id)
        .where(or_(title.ilike(pattern, escape="\\"), band_name.ilike(pattern, escape="\\")))
        # Score decides within a tier: the point of a feed is its ranking, and a
        # search that ignored it would surface the weakest match first as often
        # as not. `id` last so the order is stable across identical scores.
        .order_by(
            _prefix_tier(prefix, title, band_name),
            Recommendation.score.desc(),
            Recommendation.id,
        )
        .limit(limit + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > limit
    return [
        SearchHit(
            kind="feed",
            title=r.title,
            band_name=r.band_name,
            item_type=r.item_type,
            album_id=r.album_id,
            track_id=r.track_id,
            url=r.url,
            art_url=art_url(r.art_id),
            scan_id=r.scan_id,
            scan_name=r.scan_name,
        )
        for r in rows[:limit]
    ], truncated


@router.get("", response_model=SearchOut)
async def search(
    q: str = Query(..., max_length=200),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> SearchOut:
    text = q.strip()
    if len(text) < MIN_QUERY_LEN:
        # Not a 422: the palette sends whatever is in its input on every
        # keystroke, and a one-letter query is a user mid-word, not a caller
        # error. An empty result is the honest answer and costs nothing.
        return SearchOut(query=text, collection=[], feed=[], truncated=False)

    lowered = text.lower()
    pattern = _contains(lowered)
    prefix = _starts_with(lowered)

    # Sequential, not `asyncio.gather`: the two reads share one AsyncSession,
    # which is not safe for concurrent statements.
    collection, coll_cut = await _collection_hits(session, current_user, pattern, prefix, limit)
    feed, feed_cut = await _feed_hits(session, current_user, pattern, prefix, limit)
    return SearchOut(
        query=text,
        collection=collection,
        feed=feed,
        truncated=coll_cut or feed_cut,
    )
