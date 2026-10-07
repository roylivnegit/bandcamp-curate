"""The signed-in user's own items: owned, wishlisted and liked.

All three lists come back in one response because the client searches across
them at once and shows a per-section match count.

Two scoping keys, easy to confuse: owned/wishlist are per Bandcamp fan
(`users.fan_id`); likes are per app user (`users.id`).
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.bandcamp.art import art_url
from app.db.models import Album, Band, FanItem, Like, Track, User
from app.db.session import get_session

router = APIRouter(prefix="/api/collection", tags=["collection"])

# A collection is one person's, so it is bounded by reality rather than by
# paging. This is a safety valve against a pathological fan exhausting the
# (512 MB, free tier) API instance, not a feature — nobody is expected to hit it.
MAX_ITEMS = 20_000


class CollectionItemOut(BaseModel):
    """Deliberately shaped like `LikeOut` plus art, so the frontend can hold
    owned/wishlisted/liked rows in one list and merge duplicates across them.

    No row id: the same item legitimately appears in more than one list (you
    liked it in the feed, then bought it), and the client merges those into one
    row keyed on the item identity (`item_type` + album/track id) so it can show
    a combined "owned · liked" label. A row id would defeat that by making every
    copy look distinct.
    """

    item_type: str
    album_id: int | None
    track_id: int | None
    title: str | None
    band_name: str | None
    url: str | None
    # Bandcamp's opaque art asset id, same as RecommendationOut — not a URL.
    art_id: int | None
    art_url: str | None


class CollectionOut(BaseModel):
    owned: list[CollectionItemOut]
    wishlist: list[CollectionItemOut]
    liked: list[CollectionItemOut]
    # True when a list hit the cap and rows were left behind. Without it the cap
    # would be silently wrong rather than merely limiting: the tab counts would
    # read as totals, and a search would report "nothing matches" for a record
    # the user definitely owns.
    truncated: bool = False


def _items_query(
    model: type[FanItem] | type[Like], limit: int, *where: ColumnElement[bool]
) -> Select:
    """Flatten album-or-track edges into one display row each.

    `FanItem` and `Like` are the same shape for this purpose — both carry
    `item_type` plus exactly one of `album_id`/`track_id` — so one query serves
    all three lists and they are guaranteed to sort and render identically.
    This is the same outer-join shape as `likes._like_rows`, which stays as it
    is: it orders by recency for the feed's side panel, where this view needs
    artist A-Z, and it predates stored art.
    """
    ab = Band.__table__.alias("ab")
    tb = Band.__table__.alias("tb")
    band_name = func.coalesce(ab.c.name, tb.c.name)
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
        .outerjoin(ab, ab.c.id == Album.band_id)
        .outerjoin(tb, tb.c.id == Track.band_id)
        .where(*where)
        # `lower(coalesce(...))` rather than a bare ORDER BY: Postgres sorts
        # NULLs last and collates case-insensitively, SQLite sorts NULLs first
        # and compares raw bytes (so every uppercase letter sorts before every
        # lowercase one). Without normalising, the SQLite tests would assert an
        # order production does not produce. `id` last makes it deterministic.
        .order_by(
            func.lower(func.coalesce(band_name, "")),
            func.lower(func.coalesce(title, "")),
            model.id,
        )
        .limit(limit)
    )


async def _items(
    session: AsyncSession, model: type[FanItem] | type[Like], limit: int,
    *where: ColumnElement[bool],
) -> tuple[list[CollectionItemOut], bool]:
    """The section's rows, and whether the cap cut any off.

    Asks for one row past the limit purely to answer that second question.
    """
    rows = (await session.execute(_items_query(model, limit + 1, *where))).all()
    truncated = len(rows) > limit
    return [
        CollectionItemOut(
            item_type=r.item_type,
            album_id=r.album_id,
            track_id=r.track_id,
            title=r.title,
            band_name=r.band_name,
            url=r.url,
            art_id=r.art_id,
            art_url=art_url(r.art_id),
        )
        for r in rows[:limit]
    ], truncated


@router.get("", response_model=CollectionOut)
async def collection(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = Query(MAX_ITEMS, ge=1, le=MAX_ITEMS),
) -> CollectionOut:
    me = current_user.fan_id
    owned: list[CollectionItemOut] = []
    wishlist: list[CollectionItemOut] = []
    cut = False
    if me is not None:
        owned, owned_cut = await _items(
            session, FanItem, limit, FanItem.fan_id == me, FanItem.is_wishlist.is_(False)
        )
        wishlist, wish_cut = await _items(
            session, FanItem, limit, FanItem.fan_id == me, FanItem.is_wishlist.is_(True)
        )
        cut = owned_cut or wish_cut
    # Likes are NOT gated on fan_id: they hang off the app user, so someone who
    # signed up minutes ago, whose collection scan is still running, has no
    # owned/wishlist rows yet but can already have liked things in the feed.
    liked, liked_cut = await _items(session, Like, limit, Like.user_id == current_user.id)
    return CollectionOut(
        owned=owned, wishlist=wishlist, liked=liked, truncated=cut or liked_cut
    )
