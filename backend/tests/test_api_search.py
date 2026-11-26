"""GET /api/search — one box over the caller's scans, collection and feed."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import get_current_user
from app.db.base import Base
from app.db.models import (
    Album,
    Band,
    Fan,
    FanItem,
    Like,
    Recommendation,
    Scan,
    Track,
    User,
)
from app.db.session import get_session
from app.enums import BandKind, ItemType, ScanKind, ScanStatus
from app.main import app


class Seeded:
    user: User
    other_user: User
    my_scan_id: int
    other_scan_id: int


async def _seed(s: AsyncSession) -> Seeded:
    """Two tenants with deliberately colliding names.

    The second tenant owns a scan, a collection item and a recommendation that
    all match the same queries the first tenant's do — so every "does not leak"
    assertion below fails loudly if a join drops its user/fan filter.
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me")
    other = Fan(bandcamp_fan_id=2, username="other", url="https://bandcamp.com/other")
    s.add_all([me, other])
    await s.flush()

    user = User(username="me", password_hash="!", fan_id=me.id)
    other_user = User(username="other", password_hash="!", fan_id=other.id)
    s.add_all([user, other_user])
    await s.flush()

    aphex = Band(bandcamp_id=10, name="Aphex Twin", kind=BandKind.ARTIST)
    boards = Band(bandcamp_id=11, name="Boards of Canada", kind=BandKind.ARTIST)
    s.add_all([aphex, boards])
    await s.flush()

    drukqs = Album(bandcamp_id=100, title="Drukqs", url="https://aphex.bandcamp.com/album/drukqs",
                   band_id=aphex.id, art_id=555)
    # Same query ("drukqs") matches both, and this one is NOT a prefix — it has
    # to come second.
    remixes = Album(bandcamp_id=101, title="The Drukqs Remixes", band_id=aphex.id)
    geogaddi = Album(bandcamp_id=102, title="Geogaddi", band_id=boards.id, art_id=777)
    windowlicker = Track(bandcamp_id=200, title="Windowlicker",
                         url="https://aphex.bandcamp.com/track/windowlicker",
                         band_id=aphex.id, art_id=888)
    # Title is NULL and the band is unknown: every coalesce has to survive it.
    orphan = Album(bandcamp_id=103, title=None, band_id=None)
    # A literal percent sign in a title — the LIKE-wildcard escaping test.
    hundred = Album(bandcamp_id=104, title="100% Silk", band_id=boards.id)
    recommended = Album(bandcamp_id=105, title="Selected Ambient Works",
                        url="https://aphex.bandcamp.com/album/saw", band_id=aphex.id, art_id=999)
    weaker = Album(bandcamp_id=106, title="Ambient Leftovers", band_id=boards.id)
    stranger = Album(bandcamp_id=107, title="Drukqs Bootleg", band_id=aphex.id)
    s.add_all([drukqs, remixes, geogaddi, windowlicker, orphan, hundred,
               recommended, weaker, stranger])
    await s.flush()

    my_scan = Scan(user_id=user.id, name="Ambient dig", kind=ScanKind.CUSTOM,
                   status=ScanStatus.DONE)
    # Matches "ambient" too, but belongs to the other tenant.
    other_scan = Scan(user_id=other_user.id, name="Ambient stranger dig",
                      kind=ScanKind.CUSTOM, status=ScanStatus.DONE)
    s.add_all([my_scan, other_scan])
    await s.flush()

    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=drukqs.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=remixes.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=orphan.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=hundred.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=geogaddi.id, is_wishlist=True),
        FanItem(fan_id=me.id, item_type=ItemType.TRACK, track_id=windowlicker.id),
        FanItem(fan_id=other.id, item_type=ItemType.ALBUM, album_id=stranger.id),
        # Owned AND liked — one merged hit, not two rows.
        Like(user_id=user.id, item_type=ItemType.ALBUM, album_id=drukqs.id),
        Like(user_id=other_user.id, item_type=ItemType.ALBUM, album_id=stranger.id),
        Recommendation(scan_id=my_scan.id, item_type=ItemType.ALBUM,
                       album_id=recommended.id, score=9.0),
        Recommendation(scan_id=my_scan.id, item_type=ItemType.ALBUM,
                       album_id=weaker.id, score=1.0),
        Recommendation(scan_id=other_scan.id, item_type=ItemType.ALBUM,
                       album_id=stranger.id, score=9.9),
    ])
    await s.commit()

    out = Seeded()
    out.user, out.other_user = user, other_user
    out.my_scan_id, out.other_scan_id = my_scan.id, other_scan.id
    return out


def _make_client(box: dict[str, Seeded], maker: async_sessionmaker) -> AsyncClient:
    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: box["seeded"].user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest_asyncio.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, Seeded]]:
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
        yield c, seeded
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_one_query_returns_both_sections(ctx) -> None:
    c, _ = ctx
    r = await c.get("/api/search", params={"q": "ambient"})
    assert r.status_code == 200
    body = r.json()

    # Both of the user's recommendations match. "Ambient Leftovers" starts with
    # the query, so it takes the prefix tier and leads despite scoring 1.0
    # against the other's 9.0 — tier first, score only within a tier.
    assert [h["title"] for h in body["feed"]] == ["Ambient Leftovers", "Selected Ambient Works"]
    assert body["feed"][0]["scan_name"] == "Ambient dig"


async def test_score_decides_between_two_matches_in_the_same_tier(ctx) -> None:
    """Neither title starts with "ambient " as a word here — both are buried
    matches, so the feed's own ranking is what is left to order them by."""
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "mbient"})).json()
    assert [h["title"] for h in body["feed"]] == ["Selected Ambient Works", "Ambient Leftovers"]


async def test_a_title_match_finds_the_collection_row(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "geogaddi"})).json()
    assert [h["title"] for h in body["collection"]] == ["Geogaddi"]
    hit = body["collection"][0]
    assert hit["sections"] == ["wishlist"]
    assert hit["band_name"] == "Boards of Canada"
    assert hit["art_url"] == "https://f4.bcbits.com/img/a777_10.jpg"


async def test_an_artist_name_matches_as_well_as_a_title(ctx) -> None:
    """Searching "aphex" has to find records whose *title* says nothing about
    Aphex Twin — that is most of what a person types into a music search."""
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "aphex"})).json()
    assert {h["title"] for h in body["collection"]} == {
        "Drukqs", "The Drukqs Remixes", "Windowlicker",
    }
    assert [h["title"] for h in body["feed"]] == ["Selected Ambient Works"]


async def test_a_prefix_match_outranks_a_buried_one(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "drukqs"})).json()
    assert [h["title"] for h in body["collection"]] == ["Drukqs", "The Drukqs Remixes"]


async def test_owned_and_liked_merge_into_one_labelled_hit(ctx) -> None:
    """GET /api/collection returns the same record in two lists on purpose.
    A search result list is one row per record, carrying both labels."""
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "drukqs"})).json()
    drukqs = [h for h in body["collection"] if h["title"] == "Drukqs"]
    assert len(drukqs) == 1
    assert drukqs[0]["sections"] == ["owned", "liked"]


async def test_a_track_hit_carries_the_track_side_of_every_coalesce(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "windowlicker"})).json()
    hit = body["collection"][0]
    assert hit["item_type"] == "track"
    assert hit["album_id"] is None and hit["track_id"] is not None
    assert hit["band_name"] == "Aphex Twin"
    assert hit["url"] == "https://aphex.bandcamp.com/track/windowlicker"


async def test_another_tenants_items_and_feed_never_appear(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "drukqs"})).json()
    everything = body["collection"] + body["feed"]
    assert all(h["title"] != "Drukqs Bootleg" for h in everything)


async def test_match_is_case_insensitive(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "APHEX"})).json()
    assert body["collection"]


async def test_a_percent_sign_is_matched_literally_not_as_a_wildcard(ctx) -> None:
    """Unescaped, "100%" would become the pattern `%100%%` — which still works
    by accident. "%" on its own is the real test: as a wildcard it matches the
    entire collection, as text it matches one record."""
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "0% si"})).json()
    assert [h["title"] for h in body["collection"]] == ["100% Silk"]


async def test_a_users_own_scans_are_not_searched_here(ctx) -> None:
    """The palette already holds the whole scan list in memory and filters it
    by name locally. Returning scans here as well is what put every matching
    scan in the result list twice."""
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "ambient"})).json()
    assert "scans" not in body


async def test_a_query_shorter_than_the_minimum_returns_nothing(ctx) -> None:
    """Not an error — the palette sends every keystroke, and "a" mid-word is a
    user still typing, not a bad request."""
    c, _ = ctx
    r = await c.get("/api/search", params={"q": "a"})
    assert r.status_code == 200
    body = r.json()
    assert body["collection"] == [] and body["feed"] == []
    assert body["truncated"] is False


async def test_nothing_matching_is_an_empty_result_not_an_error(ctx) -> None:
    c, _ = ctx
    r = await c.get("/api/search", params={"q": "zzzznope"})
    assert r.status_code == 200
    assert r.json()["truncated"] is False


async def test_truncated_says_so_when_a_section_hits_the_limit(ctx) -> None:
    c, _ = ctx
    body = (await c.get("/api/search", params={"q": "drukqs", "limit": 1})).json()
    assert len(body["collection"]) == 1
    assert body["truncated"] is True


async def test_a_user_whose_collection_scan_has_not_run_still_searches_likes(ctx) -> None:
    """`users.fan_id` is NULL until the collection crawl has read their fan
    page. That is an empty owned/wishlist, not a 500 — and likes hang off the
    app user, so they still match."""
    c, seeded = ctx
    seeded.user.fan_id = None
    r = await c.get("/api/search", params={"q": "drukqs"})
    assert r.status_code == 200
    hits = r.json()["collection"]
    assert [h["sections"] for h in hits] == [["liked"]]


async def test_a_null_title_and_missing_band_do_not_break_the_query(ctx) -> None:
    """The orphan album matches nothing by text, but it is in the joined set of
    every collection query — a coalesce that dropped it would error, and an
    ordering that mishandled NULL would reorder everything around it."""
    c, _ = ctx
    r = await c.get("/api/search", params={"q": "aphex"})
    assert r.status_code == 200
    assert all(h["title"] is not None for h in r.json()["collection"])
