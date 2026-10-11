"""GET /api/collection — the user's own owned / wishlisted / liked items."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import get_current_user
from app.db.base import Base
from app.db.models import Album, Band, Fan, FanItem, Like, Track, User
from app.db.session import get_session
from app.enums import BandKind, ItemType
from app.main import app


class Seeded:
    """The ids a test needs to assert against, filled in by `_seed`."""

    user: User
    other_user: User
    stranger_album_id: int
    owned_album_id: int
    liked_album_id: int
    liked_track_id: int


async def _seed(s: AsyncSession) -> Seeded:
    """One fan with a deliberately awkward collection, plus a second tenant.

    Band names are chosen to catch dialect differences: "aphex twin" lowercase
    vs "Boards of Canada" capitalised (byte order would put every capital
    first), and one album whose band is missing entirely (NULL band_name).
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me")
    other = Fan(bandcamp_fan_id=2, username="other", url="https://bandcamp.com/other")
    s.add_all([me, other])
    await s.flush()

    user = User(username="me", password_hash="!", fan_id=me.id)
    other_user = User(username="other", password_hash="!", fan_id=other.id)
    s.add_all([user, other_user])
    await s.flush()

    aphex = Band(bandcamp_id=10, name="aphex twin", kind=BandKind.ARTIST)
    boards = Band(bandcamp_id=11, name="Boards of Canada", kind=BandKind.ARTIST)
    s.add_all([aphex, boards])
    await s.flush()

    # Owned: one with art, one whose band is unknown and whose title is NULL.
    drukqs = Album(bandcamp_id=100, title="Drukqs", url="https://aphex.bandcamp.com/album/drukqs",
                   band_id=aphex.id, art_id=555)
    orphan = Album(bandcamp_id=101, title=None, band_id=None)
    # Wishlisted.
    geogaddi = Album(bandcamp_id=102, title="Geogaddi", band_id=boards.id, art_id=777)
    # A standalone track, owned — exercises the track side of every coalesce.
    windowlicker = Track(bandcamp_id=200, title="Windowlicker",
                         url="https://aphex.bandcamp.com/track/windowlicker",
                         band_id=aphex.id, art_id=888)
    # Only the OTHER tenant owns this one.
    stranger = Album(bandcamp_id=103, title="Not Yours", band_id=boards.id)
    s.add_all([drukqs, orphan, geogaddi, windowlicker, stranger])
    await s.flush()

    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=drukqs.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=orphan.id),
        FanItem(fan_id=me.id, item_type=ItemType.TRACK, track_id=windowlicker.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=geogaddi.id, is_wishlist=True),
        FanItem(fan_id=other.id, item_type=ItemType.ALBUM, album_id=stranger.id),
        # The overlap case the frontend merges: owned AND liked.
        Like(user_id=user.id, item_type=ItemType.ALBUM, album_id=drukqs.id),
        Like(user_id=user.id, item_type=ItemType.TRACK, track_id=windowlicker.id),
        Like(user_id=other_user.id, item_type=ItemType.ALBUM, album_id=stranger.id),
    ])
    await s.commit()

    out = Seeded()
    out.user, out.other_user = user, other_user
    out.stranger_album_id = stranger.id
    out.owned_album_id = drukqs.id
    out.liked_album_id = drukqs.id
    out.liked_track_id = windowlicker.id
    return out


def _make_client(seeded_box: dict[str, Seeded], maker: async_sessionmaker) -> AsyncClient:
    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: seeded_box["seeded"].user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, Seeded, async_sessionmaker]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        seeded = await _seed(s)

    box = {"seeded": seeded}
    async with _make_client(box, maker) as c:
        yield c, seeded, maker
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_sections_hold_the_right_rows(ctx) -> None:
    c, _, _ = ctx
    r = await c.get("/api/collection")
    assert r.status_code == 200
    body = r.json()

    assert {i["title"] for i in body["owned"]} == {"Drukqs", None, "Windowlicker"}
    assert [i["title"] for i in body["wishlist"]] == ["Geogaddi"]
    # Liked carries both the album and the standalone track.
    assert {i["title"] for i in body["liked"]} == {"Drukqs", "Windowlicker"}


async def test_other_tenants_rows_never_leak(ctx) -> None:
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    everything = body["owned"] + body["wishlist"] + body["liked"]
    assert all(i["title"] != "Not Yours" for i in everything)


async def test_track_row_flattens_from_the_track_side(ctx) -> None:
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    track = next(i for i in body["owned"] if i["title"] == "Windowlicker")
    assert track["item_type"] == "track"
    assert track["album_id"] is None          # a fan_items track row has no album_id
    assert track["track_id"] is not None
    assert track["band_name"] == "aphex twin"  # resolved via the track's own band
    assert track["url"] == "https://aphex.bandcamp.com/track/windowlicker"


async def test_null_title_and_missing_band_do_not_error(ctx) -> None:
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    orphan = next(i for i in body["owned"] if i["title"] is None)
    assert orphan["band_name"] is None
    assert orphan["url"] is None
    assert orphan["art_id"] is None and orphan["art_url"] is None


async def test_art_url_is_built_from_art_id(ctx) -> None:
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    drukqs = next(i for i in body["owned"] if i["title"] == "Drukqs")
    assert drukqs["art_id"] == 555
    assert drukqs["art_url"] == "https://f4.bcbits.com/img/a555_10.jpg"
    # Liked rows carry art too, so the Liked tab does not look broken next to
    # the others — this is why the liked list is not served by `_like_rows`.
    liked = next(i for i in body["liked"] if i["title"] == "Drukqs")
    assert liked["art_url"] == "https://f4.bcbits.com/img/a555_10.jpg"


async def test_ordering_is_case_insensitive_and_null_band_sorts_predictably(ctx) -> None:
    """Byte-order sorting would put "Boards of Canada" before "aphex twin";
    case-insensitive collation puts aphex first. The NULL band becomes "" and
    therefore sorts first, identically on SQLite and Postgres."""
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    bands = [i["band_name"] for i in body["owned"]]
    assert bands == [None, "aphex twin", "aphex twin"]
    # Within one band, title decides: Drukqs before Windowlicker.
    assert [i["title"] for i in body["owned"][1:]] == ["Drukqs", "Windowlicker"]


async def test_an_item_both_owned_and_liked_appears_in_both_lists(ctx) -> None:
    """The API must NOT pre-deduplicate across the three lists — the frontend
    merges them so it can show a combined "owned · liked" label."""
    c, _, _ = ctx
    body = (await c.get("/api/collection")).json()
    assert any(i["title"] == "Drukqs" for i in body["owned"])
    assert any(i["title"] == "Drukqs" for i in body["liked"])


async def test_uncrawled_user_gets_empty_fan_lists_but_keeps_likes(ctx) -> None:
    """`users.fan_id` is NULL until the collection scan has read the user's own
    fan page. That must be an empty collection, not a 500 — and likes hang off
    the app user, so they survive."""
    c, seeded, _ = ctx
    seeded.user.fan_id = None
    r = await c.get("/api/collection")
    assert r.status_code == 200
    body = r.json()
    assert body["owned"] == [] and body["wishlist"] == []
    assert {i["title"] for i in body["liked"]} == {"Drukqs", "Windowlicker"}


async def test_limit_caps_each_list_and_reports_the_cut(ctx) -> None:
    c, _, _ = ctx
    body = (await c.get("/api/collection?limit=1")).json()
    assert len(body["owned"]) == 1 and len(body["liked"]) == 1
    # Silently returning a short list would make the tab counts read as totals
    # and a search miss items that exist.
    assert body["truncated"] is True


async def test_a_collection_under_the_cap_is_not_flagged_truncated(ctx) -> None:
    c, _, _ = ctx
    assert (await c.get("/api/collection")).json()["truncated"] is False


async def test_limit_above_the_ceiling_is_rejected(ctx) -> None:
    c, _, _ = ctx
    assert (await c.get("/api/collection?limit=20001")).status_code == 422
