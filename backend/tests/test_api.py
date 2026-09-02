from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import get_current_user
from app.curation.engine import curate
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    AlbumTag,
    Band,
    Fan,
    FanItem,
    Follow,
    Recommendation,
    Scan,
    Tag,
    Track,
    User,
)
from app.db.session import get_session
from app.enums import BandKind, ItemType, ScanKind, TargetType
from app.main import app


async def _seed(s: AsyncSession) -> User:
    # me owns A1(B1); neighbour f2 SUPPORTS A1 (→ f2 is a taste-neighbour of the
    # collection scan) and owns A1 + A2(B2) + track T2(B2).
    # follow B3 which f2 also owns (A3) → A3 excluded.
    # Returns the User whose fan_id is `me` (the authenticated caller).
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    f2 = Fan(bandcamp_fan_id=2, username="f2", url="https://bandcamp.com/f2")
    b1, b2, b3, b4 = (Band(bandcamp_id=n, name=f"Band{n}", kind=BandKind.ARTIST)
                      for n in (1, 2, 3, 4))
    s.add_all([me, f2, b1, b2, b3, b4])
    await s.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    s.add(user)
    await s.flush()
    a1 = Album(bandcamp_id=11, title="Owned", band_id=b1.id)
    a2 = Album(bandcamp_id=12, title="Recommend Me",
               url="https://b2.bandcamp.com/album/x", band_id=b2.id)
    a3 = Album(bandcamp_id=13, title="Followed", band_id=b3.id)
    t2 = Track(bandcamp_id=22, title="A Track", band_id=b4.id)  # own band → survives dedup
    s.add_all([a1, a2, a3, t2])
    await s.flush()
    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a3.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t2.id),
        Follow(fan_id=me.id, band_id=b3.id, target_type=TargetType.ARTIST),
        # f2 supports my album A1 → f2 is a neighbour of the collection scan.
        AlbumSupporter(album_id=a1.id, fan_id=f2.id),
    ])
    # a2 ("Recommend Me") carries two genres → for the AND-filter test.
    rock, jazz = Tag(name="rock"), Tag(name="jazz")
    s.add_all([rock, jazz])
    await s.flush()
    s.add_all([AlbumTag(album_id=a2.id, tag_id=rock.id), AlbumTag(album_id=a2.id, tag_id=jazz.id)])
    await s.commit()
    return user


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = await _seed(s)
        await curate(s, user=user)  # populate recommendations

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_stats(client: AsyncClient) -> None:
    r = await client.get("/api/stats")
    assert r.status_code == 200
    s = r.json()
    from app.config import get_settings

    assert s["neighbours"] == 1 and s["my_owned"] == 1 and s["follows"] == 1
    assert s["request_budget"] == get_settings().crawl_max_requests
    assert s["recommendations"] >= 1


async def test_recommendations_feed(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    titles = {r["title"] for r in rows}
    assert "Recommend Me" in titles      # neighbour-owned, not mine
    assert "Owned" not in titles          # excluded: I own it
    assert "Followed" not in titles       # excluded: I follow the band
    top = rows[0]
    assert top["rank"] == 1 and top["reasons"]["co_owners"] == 1
    assert top["url"] == "https://b2.bandcamp.com/album/x"


async def test_recommendations_filter_and_paging(client: AsyncClient) -> None:
    albums = (await client.get("/api/recommendations?item_type=album")).json()
    assert all(r["item_type"] == "album" for r in albums)
    tracks = (await client.get("/api/recommendations?item_type=track")).json()
    assert all(r["item_type"] == "track" for r in tracks) and len(tracks) == 1
    # offset past the end → empty
    assert (await client.get("/api/recommendations?offset=999")).json() == []


async def test_recompute_endpoint(client: AsyncClient) -> None:
    r = await client.post("/api/recommendations/recompute")
    assert r.status_code == 200 and r.json()["computed"] >= 1


async def test_recompute_unknown_scan_404(client: AsyncClient) -> None:
    # an unknown scan_id is a 404, not a 500 (curate raises, endpoint maps it)
    r = await client.post("/api/recommendations/recompute?scan_id=999999")
    assert r.status_code == 404


async def test_legacy_ui_route_is_not_served(client: AsyncClient) -> None:
    # The old server-rendered feed is unregistered (see app/main.py): its fetch()
    # calls carry no bearer token, so it would render and then silently 401 on
    # every request. A clean 404 until the React app lands.
    assert (await client.get("/")).status_code == 404


async def test_recommendation_has_band_id(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    assert rows and all(r["band_id"] is not None for r in rows)


async def test_block_prunes_and_lists_then_unblock(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    target = next(r for r in rows if r["title"] == "Recommend Me")
    band_id = target["band_id"]

    # Block the band → gone from feed, listed in blacklist.
    r = await client.post("/api/blacklist", json={"band_id": band_id, "reason": "nope"})
    assert r.status_code == 200 and r.json()["band_id"] == band_id
    after = (await client.get("/api/recommendations")).json()
    assert band_id not in {x["band_id"] for x in after}
    blocked = (await client.get("/api/blacklist")).json()
    assert band_id in {b["band_id"] for b in blocked}

    # A fresh recompute keeps it excluded.
    await client.post("/api/recommendations/recompute")
    assert band_id not in {x["band_id"] for x in (await client.get("/api/recommendations")).json()}

    # Unblock → returns on recompute.
    assert (await client.post(f"/api/blacklist/{band_id}/unblock")).status_code == 200
    await client.post("/api/recommendations/recompute")
    assert band_id in {x["band_id"] for x in (await client.get("/api/recommendations")).json()}


async def test_block_unknown_band_404(client: AsyncClient) -> None:
    assert (await client.post("/api/blacklist", json={"band_id": 999999})).status_code == 404


async def test_block_with_expiry_round_trips(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    target = next(r for r in rows if r["title"] == "Recommend Me")
    band_id = target["band_id"]

    def _naive_utc(iso: str) -> datetime:
        # SQLite (test DB only; Postgres preserves the offset) drops tzinfo
        # on a raw column read-back, so compare wall-clock value only.
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(UTC).replace(tzinfo=None)

    expires_at = "2099-01-01T00:00:00+00:00"
    r = await client.post(
        "/api/blacklist", json={"band_id": band_id, "expires_at": expires_at}
    )
    assert r.status_code == 200
    assert _naive_utc(r.json()["expires_at"]) == _naive_utc(expires_at)

    blocked = (await client.get("/api/blacklist")).json()
    entry = next(b for b in blocked if b["band_id"] == band_id)
    assert _naive_utc(entry["expires_at"]) == _naive_utc(expires_at)

    assert (await client.post(f"/api/blacklist/{band_id}/unblock")).status_code == 200


async def test_label_filter(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    band_id = rows[0]["band_id"]
    only = (await client.get(f"/api/recommendations?label_id={band_id}")).json()
    assert only and all(r["band_id"] == band_id for r in only)
    without = (await client.get(f"/api/recommendations?exclude_label_id={band_id}")).json()
    assert band_id not in {r["band_id"] for r in without}


async def test_multi_tag_filter_is_AND(client: AsyncClient) -> None:
    async def get_titles(qs: str) -> set[str]:
        return {r["title"] for r in (await client.get("/api/recommendations" + qs)).json()}

    assert "Recommend Me" in await get_titles("?tag=rock")
    assert "Recommend Me" in await get_titles("?tag=rock&tag=jazz")   # has BOTH → kept
    assert "Recommend Me" not in await get_titles("?tag=rock&tag=metal")  # AND: lacks metal → gone
    # count endpoint uses the same AND logic
    assert (await client.get("/api/recommendations/count?tag=rock&tag=jazz")).json()["count"] >= 1
    assert (await client.get("/api/recommendations/count?tag=rock&tag=metal")).json()["count"] == 0


async def test_tag_contains_filter(client: AsyncClient) -> None:
    async def get_titles(qs: str) -> set[str]:
        return {r["title"] for r in (await client.get("/api/recommendations" + qs)).json()}

    # substring match, case-insensitive, against the "rock"/"jazz" tags on "Recommend Me".
    assert "Recommend Me" in await get_titles("?tag_contains=roc")
    assert "Recommend Me" in await get_titles("?tag_contains=ROC")
    assert "Recommend Me" not in await get_titles("?tag_contains=xyz")
    # AND across multiple substrings, like the exact-tag filter.
    assert "Recommend Me" in await get_titles("?tag_contains=roc&tag_contains=jaz")
    assert "Recommend Me" not in await get_titles("?tag_contains=roc&tag_contains=xyz")
    # exclude = drop if ANY excluded substring matches.
    assert "Recommend Me" not in await get_titles("?exclude_tag_contains=roc")
    assert "Recommend Me" in await get_titles("?exclude_tag_contains=xyz")
    # count endpoint uses the same logic
    assert (await client.get("/api/recommendations/count?tag_contains=roc")).json()["count"] >= 1
    assert (await client.get("/api/recommendations/count?tag_contains=xyz")).json()["count"] == 0


async def test_recommendations_count_matches_filters(client: AsyncClient) -> None:
    total = (await client.get("/api/recommendations/count")).json()["count"]
    rows = (await client.get("/api/recommendations?limit=200")).json()
    assert total == len(rows)  # unfiltered count == full list

    # filtered count agrees with the filtered list
    albums = (await client.get("/api/recommendations/count?item_type=album")).json()["count"]
    album_rows = (await client.get("/api/recommendations?item_type=album&limit=200")).json()
    assert albums == len(album_rows)

    # a followed band / owned item is excluded, so a bogus label yields 0
    assert (await client.get("/api/recommendations/count?label_id=99999")).json()["count"] == 0


async def test_sort_param(client: AsyncClient) -> None:
    # every valid sort orders on a real column (score) or a reasons-JSON key
    # (co_owners / tag_affinity) — all must return the feed, not error.
    for s in ("score", "neighbours", "affinity"):
        r = await client.get(f"/api/recommendations?sort={s}")
        assert r.status_code == 200 and len(r.json()) >= 1
        assert [x["rank"] for x in r.json()] == list(range(1, len(r.json()) + 1))
    # unknown sort is rejected
    assert (await client.get("/api/recommendations?sort=bogus")).status_code == 422


async def test_sort_missing_json_key_sorts_after_real_zero() -> None:
    # A rec whose reasons lacks tag_affinity must sort AFTER a rec with a real 0
    # (the old COALESCE-to-0 conflated them). Insert missing-key first (lower id)
    # so an id tie-break alone wouldn't produce the right order.
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        b = Band(bandcamp_id=1, name="B", kind=BandKind.ARTIST)
        user = User(username="me", password_hash="!")
        s.add_all([b, user])
        await s.flush()
        # recs need a scan; the feed defaults to the caller's collection scan.
        scan = Scan(user_id=user.id, name="c", kind=str(ScanKind.COLLECTION), status="done")
        s.add(scan)
        await s.flush()
        missing, zero, five = (
            Album(bandcamp_id=100 + i, title=t, band_id=b.id)
            for i, t in enumerate(("missing", "zero", "five"))
        )
        s.add_all([missing, zero, five])
        await s.flush()
        def rec(album, reasons):  # noqa: ANN001,ANN202
            return Recommendation(
                scan_id=scan.id, item_type=ItemType.ALBUM,
                album_id=album.id, score=1.0, reasons=reasons,
            )
        s.add_all([  # insertion order = id order: missing, zero, five
            rec(missing, {}),
            rec(zero, {"tag_affinity": 0.0}),
            rec(five, {"tag_affinity": 5.0}),
        ])
        await s.commit()

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            rows = (await c.get("/api/recommendations?sort=affinity")).json()
        assert [r["title"] for r in rows] == ["five", "zero", "missing"]
    finally:  # guarantee teardown even if the request/assert raises
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_facets(client: AsyncClient) -> None:
    f = (await client.get("/api/facets")).json()
    assert "tags" in f and "labels" in f and "seed_tags" in f
    # Every recommended band shows up as a label facet.
    rec_bands = {r["band_id"] for r in (await client.get("/api/recommendations")).json()}
    facet_bands = {int(x["value"]) for x in f["labels"]}
    assert rec_bands <= facet_bands


async def test_recompute_accepts_seed_tag_exclusion(client: AsyncClient) -> None:
    r = await client.post("/api/recommendations/recompute?exclude_seed_tag=psytrance")
    assert r.status_code == 200
    assert r.json()["excluded_seed_tags"] == ["psytrance"]


async def test_like_removes_and_excludes_then_unlike(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    target = next(r for r in rows if r["title"] == "Recommend Me")
    album_id = target["album_id"]
    assert album_id is not None

    # Like it → gone from feed now, listed under likes, stats.liked bumps.
    r = await client.post("/api/likes", json={"album_id": album_id})
    assert r.status_code == 200 and r.json()["album_id"] == album_id
    after = (await client.get("/api/recommendations")).json()
    assert album_id not in {x["album_id"] for x in after}
    assert (await client.get("/api/stats")).json()["liked"] == 1
    assert album_id in {x["album_id"] for x in (await client.get("/api/likes")).json()}

    # Stays excluded across a recompute.
    await client.post("/api/recommendations/recompute")
    recs = (await client.get("/api/recommendations")).json()
    assert album_id not in {x["album_id"] for x in recs}

    # Unlike → returns on recompute.
    assert (await client.post("/api/likes/unlike", json={"album_id": album_id})).status_code == 200
    await client.post("/api/recommendations/recompute")
    recs = (await client.get("/api/recommendations")).json()
    assert album_id in {x["album_id"] for x in recs}


async def test_like_requires_exactly_one_id(client: AsyncClient) -> None:
    assert (await client.post("/api/likes", json={})).status_code == 422
    assert (await client.post("/api/likes", json={"album_id": 1, "track_id": 2})).status_code == 422
