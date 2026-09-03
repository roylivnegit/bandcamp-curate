"""Auth + multi-tenancy tests.

The isolation tests are the point of this file: with real accounts, one user must
never be able to see or act on another's scans/feed/likes/blocks, and curation must
never leak one tenant's exclusions (follows/likes/blocks) into another's feed.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.security import (
    ALGORITHM,
    create_access_token,
    hash_password,
    verify_password,
)
from app.config import Settings, get_settings
from app.curation.engine import compute_recommendations
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    Band,
    Blacklist,
    Fan,
    FanItem,
    Follow,
    Like,
    Scan,
    ScanSeed,
    User,
)
from app.db.session import get_session
from app.enums import BandKind, ItemType, ScanKind, ScanStatus, TargetType
from app.main import app

INVITE = "let-me-in"
# >=32 bytes: PyJWT warns below that for HS256.
SECRET = "test-secret-key-that-is-long-enough-for-hs256"


def _settings() -> Settings:
    return Settings(auth_secret_key=SECRET, auth_invite_code=INVITE)


@pytest_asyncio.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(maker) -> AsyncIterator[AsyncClient]:  # noqa: ANN001
    """A real, unauthenticated client — auth is exercised end-to-end (no
    get_current_user override), so these tests cover the actual token path."""
    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_settings] = _settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _signup(c: AsyncClient, username: str, *, invite: str = INVITE) -> str:
    r = await c.post("/api/auth/signup", json={
        "username": username, "password": "hunter22",
        "bandcamp_fan_url": f"https://bandcamp.com/{username}", "invite_code": invite,
    })
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── password hashing ──────────────────────────────────────────────────────────


def test_password_hash_round_trip() -> None:
    h = hash_password("correct horse")
    assert h != "correct horse"  # actually hashed
    assert verify_password("correct horse", h)
    assert not verify_password("wrong horse", h)


def test_verify_password_rejects_garbage_hash() -> None:
    # The migration-backfilled operator row carries "!" as an unusable placeholder.
    assert not verify_password("anything", "!")


# ── signup / login / me ───────────────────────────────────────────────────────


async def test_signup_creates_user_and_collection_scan(client: AsyncClient, maker) -> None:  # noqa: ANN001
    token = await _signup(client, "alice")

    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    assert me["username"] == "alice"
    assert me["bandcamp_fan_url"] == "https://bandcamp.com/alice"
    assert me["has_crawled"] is False  # fan_id not set until the crawl runs
    # Signup queues the collection scan for the crawl worker to pick up.
    assert me["collection_scan"]["status"] == str(ScanStatus.QUEUED)

    async with maker() as s:
        scan = (await s.execute(select(Scan))).scalar_one()
        assert scan.kind == str(ScanKind.COLLECTION)
        # A collection scan has no ScanSeed rows — it seeds from the user's fan url.
        seeds = (
            await s.execute(select(ScanSeed).where(ScanSeed.scan_id == scan.id))
        ).scalars().all()
        assert seeds == []


async def test_signup_requires_valid_invite_code(client: AsyncClient) -> None:
    r = await client.post("/api/auth/signup", json={
        "username": "mallory", "password": "hunter22",
        "bandcamp_fan_url": "https://bandcamp.com/mallory", "invite_code": "guessed",
    })
    assert r.status_code == 403 and "invite" in r.json()["detail"]


async def test_signup_rejects_duplicate_username(client: AsyncClient) -> None:
    await _signup(client, "alice")
    r = await client.post("/api/auth/signup", json={
        "username": "alice", "password": "other", "invite_code": INVITE,
        "bandcamp_fan_url": "https://bandcamp.com/alice2",
    })
    assert r.status_code == 409


async def test_login_returns_token_and_rejects_bad_credentials(client: AsyncClient) -> None:
    await _signup(client, "alice")

    ok = await client.post("/api/auth/login", json={"username": "alice", "password": "hunter22"})
    assert ok.status_code == 200 and ok.json()["access_token"]

    bad_pw = await client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert bad_pw.status_code == 401
    no_user = await client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert no_user.status_code == 401


# ── login lockout ──────────────────────────────────────────────────────────────
# `_settings()`'s defaults apply here: 5 attempts, 15-minute lockout.


async def test_login_locks_out_after_max_failed_attempts(client: AsyncClient) -> None:
    await _signup(client, "alice")
    bad = {"username": "alice", "password": "nope"}

    for _ in range(5):
        r = await client.post("/api/auth/login", json=bad)
        assert r.status_code == 401

    # The 6th attempt is locked out — even with the CORRECT password, so a
    # locked-out attacker can't use a 401-vs-429 split to learn anything.
    r = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter22"}
    )
    assert r.status_code == 429


async def test_successful_login_resets_the_failed_attempt_counter(
    client: AsyncClient, maker,  # noqa: ANN001
) -> None:
    await _signup(client, "alice")
    bad = {"username": "alice", "password": "nope"}
    ok = {"username": "alice", "password": "hunter22"}

    for _ in range(3):  # below the 5-attempt threshold
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401
    assert (await client.post("/api/auth/login", json=ok)).status_code == 200

    async with maker() as s:
        user = (await s.execute(select(User).where(User.username == "alice"))).scalar_one()
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    # The counter actually reset, not just capped: 3 more failures (not 2)
    # are needed to reach the threshold again.
    for _ in range(3):
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401
    assert (await client.post("/api/auth/login", json=ok)).status_code == 200  # still not locked


async def test_lockout_clears_once_its_window_has_passed(
    client: AsyncClient, maker,  # noqa: ANN001
) -> None:
    await _signup(client, "alice")
    bad = {"username": "alice", "password": "nope"}
    for _ in range(5):
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401
    assert (await client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter22"}
    )).status_code == 429

    # Same "write a past timestamp directly" convention as
    # test_expired_blacklist_stops_excluding — no clock mocking.
    async with maker() as s:
        user = (await s.execute(select(User).where(User.username == "alice"))).scalar_one()
        user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()

    r = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "hunter22"}
    )
    assert r.status_code == 200 and r.json()["access_token"]


async def test_lockout_threshold_comes_from_settings(maker) -> None:  # noqa: ANN001
    """Not hardcoded: a deployment can tune `auth_login_max_attempts` without a
    code change."""
    async def _override():  # noqa: ANN202
        async with maker() as s:
            yield s

    def _tight_settings() -> Settings:
        return Settings(auth_secret_key=SECRET, auth_invite_code=INVITE, auth_login_max_attempts=2)

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_settings] = _tight_settings
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            await _signup(c, "alice")
            bad = {"username": "alice", "password": "nope"}
            assert (await c.post("/api/auth/login", json=bad)).status_code == 401
            assert (await c.post("/api/auth/login", json=bad)).status_code == 401
            # Locked after just 2, not the usual 5.
            locked = await c.post(
                "/api/auth/login", json={"username": "alice", "password": "hunter22"}
            )
            assert locked.status_code == 429
    finally:
        app.dependency_overrides.clear()


# ── token validation ──────────────────────────────────────────────────────────


async def test_protected_routes_require_a_valid_token(client: AsyncClient) -> None:
    assert (await client.get("/api/scans")).status_code == 401          # no header
    assert (await client.get("/api/scans", headers=_auth("nonsense"))).status_code == 401
    assert (await client.get("/api/stats", headers=_auth("nonsense"))).status_code == 401


async def test_token_signed_with_another_secret_is_rejected(client: AsyncClient) -> None:
    await _signup(client, "alice")
    forged = jwt.encode(
        {"sub": "1"}, "a-different-secret-of-a-perfectly-fine-length", algorithm=ALGORITHM
    )
    assert (await client.get("/api/auth/me", headers=_auth(forged))).status_code == 401


async def test_token_for_deleted_user_is_rejected(client: AsyncClient) -> None:
    token = create_access_token(9999, _settings())  # no such user row
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 401


# ── cross-tenant isolation (the point of multi-tenancy) ───────────────────────


async def test_users_cannot_see_or_touch_each_others_scans(client: AsyncClient) -> None:
    alice = await _signup(client, "alice")
    bob = await _signup(client, "bob")

    made = await client.post(
        "/api/scans",
        json={"name": "alice dig", "seeds": ["https://x.bandcamp.com/album/y"]},
        headers=_auth(alice),
    )
    assert made.status_code == 201
    sid = made.json()["id"]

    # Alice sees her scan; Bob's list contains only his own collection scan.
    alice_scans = (await client.get("/api/scans", headers=_auth(alice))).json()
    assert sid in {s["id"] for s in alice_scans}
    bob_scans = (await client.get("/api/scans", headers=_auth(bob))).json()
    assert sid not in {s["id"] for s in bob_scans}

    # Bob gets 404 (not 403) everywhere — never leak that the scan exists.
    assert (await client.get(f"/api/scans/{sid}", headers=_auth(bob))).status_code == 404
    assert (await client.post(f"/api/scans/{sid}/run", headers=_auth(bob))).status_code == 404
    assert (await client.delete(f"/api/scans/{sid}", headers=_auth(bob))).status_code == 404
    # …and the scan is untouched.
    assert (await client.get(f"/api/scans/{sid}", headers=_auth(alice))).status_code == 200


async def test_feed_endpoints_reject_another_users_scan_id(client: AsyncClient) -> None:
    alice = await _signup(client, "alice")
    bob = await _signup(client, "bob")
    sid = (await client.post(
        "/api/scans",
        json={"name": "alice dig", "seeds": ["https://x.bandcamp.com/album/y"]},
        headers=_auth(alice),
    )).json()["id"]

    for path in ("/api/stats", "/api/recommendations", "/api/recommendations/count", "/api/facets"):
        r = await client.get(f"{path}?scan_id={sid}", headers=_auth(bob))
        assert r.status_code == 404, f"{path} leaked another user's scan"
    r = await client.post(f"/api/recommendations/recompute?scan_id={sid}", headers=_auth(bob))
    assert r.status_code == 404


async def test_likes_and_blocks_are_per_user(client: AsyncClient, maker) -> None:  # noqa: ANN001
    alice = await _signup(client, "alice")
    bob = await _signup(client, "bob")
    async with maker() as s:
        band = Band(bandcamp_id=1, name="Shared Band", kind=BandKind.ARTIST)
        s.add(band)
        await s.flush()
        album = Album(bandcamp_id=10, title="Shared Album", band_id=band.id)
        s.add(album)
        await s.commit()
        band_id, album_id = band.id, album.id

    assert (await client.post(
        "/api/likes", json={"album_id": album_id}, headers=_auth(alice)
    )).status_code == 200
    assert (await client.post(
        "/api/blacklist", json={"band_id": band_id}, headers=_auth(alice)
    )).status_code == 200

    # Alice sees both; Bob sees neither.
    assert len((await client.get("/api/likes", headers=_auth(alice))).json()) == 1
    assert len((await client.get("/api/blacklist", headers=_auth(alice))).json()) == 1
    assert (await client.get("/api/likes", headers=_auth(bob))).json() == []
    assert (await client.get("/api/blacklist", headers=_auth(bob))).json() == []

    # Bob can't unlike/unblock what he doesn't own.
    assert (await client.post(
        "/api/likes/unlike", json={"album_id": album_id}, headers=_auth(bob)
    )).status_code == 404
    assert (await client.post(
        f"/api/blacklist/{band_id}/unblock", headers=_auth(bob)
    )).status_code == 404
    # Alice's own like/block survived Bob's attempts.
    assert len((await client.get("/api/likes", headers=_auth(alice))).json()) == 1


async def test_stats_are_scoped_to_the_caller(client: AsyncClient, maker) -> None:  # noqa: ANN001
    """Regression: /api/stats used to resolve "me" via a global `Fan.is_me` query,
    which returns an arbitrary tenant's fan once there's more than one user."""
    await _signup(client, "alice")
    bob = await _signup(client, "bob")
    async with maker() as s:
        alice_user = (
            await s.execute(select(User).where(User.username == "alice"))
        ).scalar_one()
        alice_fan = Fan(bandcamp_fan_id=1, username="alice_bc",
                        url="https://bandcamp.com/alice_bc", is_me=True)
        s.add(alice_fan)
        await s.flush()
        alice_user.fan_id = alice_fan.id
        album = Album(bandcamp_id=10, title="Alice's")
        s.add(album)
        await s.flush()
        s.add(FanItem(fan_id=alice_fan.id, item_type=ItemType.ALBUM, album_id=album.id))
        await s.commit()

    # Bob's collection is empty — Alice's owned item must not show up in his stats.
    bob_stats = (await client.get("/api/stats", headers=_auth(bob))).json()
    assert bob_stats["my_owned"] == 0 and bob_stats["my_wishlist"] == 0


async def test_neighbour_count_does_not_exclude_other_tenants(
    client: AsyncClient, maker,  # noqa: ANN001
) -> None:
    """Regression: neighbours was `count(Fan where is_me == False)`. Each tenant's
    own collection crawl sets THEIR fan is_me=True, so that predicate dropped every
    other user's fan — under-counting by one per tenant. Neighbours means "every
    crawled collector but me", so only the caller's own fan should be excluded."""
    alice = await _signup(client, "alice")
    await _signup(client, "bob")
    async with maker() as s:
        users = {
            u.username: u for u in (await s.execute(select(User))).scalars().all()
        }
        # Both tenants get crawled: each ends up with an is_me=True fan of their own.
        for name in ("alice", "bob"):
            fan = Fan(bandcamp_fan_id=hash(name) % 10000, username=f"{name}_bc",
                      url=f"https://bandcamp.com/{name}_bc", is_me=True)
            s.add(fan)
            await s.flush()
            users[name].fan_id = fan.id
        # Plus one ordinary crawled collector who belongs to nobody.
        s.add(Fan(bandcamp_fan_id=999, username="stranger",
                  url="https://bandcamp.com/stranger", is_me=False))
        await s.commit()

    stats = (await client.get("/api/stats", headers=_auth(alice))).json()
    # 3 fans total (alice_bc, bob_bc, stranger); from Alice's seat 2 are neighbours.
    assert stats["fans"] == 3
    assert stats["neighbours"] == 2, (
        "bob's fan was excluded because it carries is_me=True — the old global "
        "is_me predicate is back"
    )


async def test_one_users_follows_do_not_suppress_anothers_feed(maker) -> None:  # noqa: ANN001
    """Regression: `follows` had no fan scoping (globally unique on band_id), so one
    user following a label silently removed it from every other user's feed."""
    async with maker() as s:
        # Two tenants, each with their own Fan, both neighbouring the same album.
        a_fan = Fan(bandcamp_fan_id=1, username="a", url="https://bandcamp.com/a", is_me=True)
        b_fan = Fan(bandcamp_fan_id=2, username="b", url="https://bandcamp.com/b", is_me=True)
        neighbour = Fan(bandcamp_fan_id=3, username="n", url="https://bandcamp.com/n")
        seed_band = Band(bandcamp_id=10, name="Seed", kind=BandKind.ARTIST)
        rec_band = Band(bandcamp_id=20, name="Rec", kind=BandKind.ARTIST)
        s.add_all([a_fan, b_fan, neighbour, seed_band, rec_band])
        await s.flush()

        a_user = User(username="a", password_hash="!", fan_id=a_fan.id)
        b_user = User(username="b", password_hash="!", fan_id=b_fan.id)
        s.add_all([a_user, b_user])
        await s.flush()

        seed_album = Album(bandcamp_id=100, title="Seed Album", band_id=seed_band.id)
        rec_album = Album(bandcamp_id=200, title="Rec Album", band_id=rec_band.id)
        s.add_all([seed_album, rec_album])
        await s.flush()

        # Both tenants own the seed album; the neighbour supports it and owns the candidate.
        s.add_all([
            FanItem(fan_id=a_fan.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
            FanItem(fan_id=b_fan.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
            FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=rec_album.id),
            AlbumSupporter(album_id=seed_album.id, fan_id=neighbour.id),
        ])
        # Only user A follows the recommended band.
        s.add(Follow(fan_id=a_fan.id, band_id=rec_band.id, target_type=TargetType.ARTIST))

        a_scan = Scan(user_id=a_user.id, name="A", kind=str(ScanKind.COLLECTION), status="done")
        b_scan = Scan(user_id=b_user.id, name="B", kind=str(ScanKind.COLLECTION), status="done")
        s.add_all([a_scan, b_scan])
        await s.commit()

        a_recs = await compute_recommendations(s, a_scan, a_user)
        b_recs = await compute_recommendations(s, b_scan, b_user)

    # A follows the band → excluded for A only. B must still get the recommendation.
    assert rec_album.id not in {r.album_id for r in a_recs}
    assert rec_album.id in {r.album_id for r in b_recs}


async def test_one_users_likes_and_blocks_do_not_suppress_anothers_feed(maker) -> None:  # noqa: ANN001
    async with maker() as s:
        a_fan = Fan(bandcamp_fan_id=1, username="a", url="https://bandcamp.com/a", is_me=True)
        b_fan = Fan(bandcamp_fan_id=2, username="b", url="https://bandcamp.com/b", is_me=True)
        neighbour = Fan(bandcamp_fan_id=3, username="n", url="https://bandcamp.com/n")
        seed_band = Band(bandcamp_id=10, name="Seed", kind=BandKind.ARTIST)
        liked_band = Band(bandcamp_id=20, name="Liked", kind=BandKind.ARTIST)
        blocked_band = Band(bandcamp_id=30, name="Blocked", kind=BandKind.ARTIST)
        s.add_all([a_fan, b_fan, neighbour, seed_band, liked_band, blocked_band])
        await s.flush()

        a_user = User(username="a", password_hash="!", fan_id=a_fan.id)
        b_user = User(username="b", password_hash="!", fan_id=b_fan.id)
        s.add_all([a_user, b_user])
        await s.flush()

        seed_album = Album(bandcamp_id=100, title="Seed Album", band_id=seed_band.id)
        liked_album = Album(bandcamp_id=200, title="Liked Album", band_id=liked_band.id)
        blocked_album = Album(bandcamp_id=300, title="Blocked Album", band_id=blocked_band.id)
        s.add_all([seed_album, liked_album, blocked_album])
        await s.flush()

        s.add_all([
            FanItem(fan_id=a_fan.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
            FanItem(fan_id=b_fan.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
            FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=liked_album.id),
            FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=blocked_album.id),
            AlbumSupporter(album_id=seed_album.id, fan_id=neighbour.id),
        ])
        # A likes one candidate and blocks the other's band — both A-only preferences.
        s.add_all([
            Like(user_id=a_user.id, item_type=str(ItemType.ALBUM), album_id=liked_album.id),
            Blacklist(user_id=a_user.id, target_type=str(TargetType.ARTIST),
                      band_id=blocked_band.id, active=True),
        ])

        a_scan = Scan(user_id=a_user.id, name="A", kind=str(ScanKind.COLLECTION), status="done")
        b_scan = Scan(user_id=b_user.id, name="B", kind=str(ScanKind.COLLECTION), status="done")
        s.add_all([a_scan, b_scan])
        await s.commit()

        a_ids = {r.album_id for r in await compute_recommendations(s, a_scan, a_user)}
        b_ids = {r.album_id for r in await compute_recommendations(s, b_scan, b_user)}

    assert liked_album.id not in a_ids and blocked_album.id not in a_ids
    assert liked_album.id in b_ids and blocked_album.id in b_ids  # B unaffected


# ── collection-scan wiring ────────────────────────────────────────────────────


async def test_curate_before_collection_crawl_is_a_clean_404(client: AsyncClient) -> None:
    # A fresh signup has no fan_id yet (the crawl hasn't run) — recompute should
    # explain itself, not 500.
    token = await _signup(client, "alice")
    r = await client.post("/api/recommendations/recompute", headers=_auth(token))
    assert r.status_code == 404 and "collection" in r.json()["detail"]


async def test_get_me_rejects_a_dangling_fan_id(maker) -> None:  # noqa: ANN001
    from app.curation.engine import get_me

    async with maker() as s:
        user = User(username="a", password_hash="!", fan_id=4242)  # no such Fan
        s.add(user)
        await s.flush()
        with pytest.raises(ValueError, match="no longer exists"):
            await get_me(s, user)


async def test_every_read_endpoint_survives_a_fresh_signup(client: AsyncClient) -> None:
    """The first page a new user loads, before their collection has been crawled.
    /api/facets used to 500 here (seed_tags -> get_me raises on a null fan_id)."""
    token = await _signup(client, "alice")
    for path in ("/api/stats", "/api/recommendations", "/api/recommendations/count",
                 "/api/facets", "/api/likes", "/api/blacklist", "/api/scans"):
        r = await client.get(path, headers=_auth(token))
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"

    facets = (await client.get("/api/facets", headers=_auth(token))).json()
    assert facets["seed_tags"] == []  # nothing crawled yet, but not an error


# ── misconfiguration / hostile input (must not 500) ───────────────────────────


def _unconfigured() -> Settings:
    return Settings(auth_secret_key="", auth_invite_code=INVITE)


async def test_auth_routes_503_when_no_signing_key_is_set(maker) -> None:  # noqa: ANN001
    """PyJWT refuses an empty HMAC key, so without this guard signup would commit
    the user + scan and *then* fail — leaving an account nobody can log into."""
    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_settings] = _unconfigured
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/auth/signup", json={
                "username": "alice", "password": "pw", "invite_code": INVITE,
                "bandcamp_fan_url": "https://bandcamp.com/alice",
            })
            assert r.status_code == 503
            assert (await c.post(
                "/api/auth/login", json={"username": "alice", "password": "pw"}
            )).status_code == 503
    finally:
        app.dependency_overrides.clear()

    # Critically: nothing was persisted, so a later correctly-configured signup works.
    async with maker() as s:
        assert (await s.execute(select(User))).scalars().all() == []


async def test_token_with_a_non_integer_subject_is_401_not_500(client: AsyncClient) -> None:
    await _signup(client, "alice")
    for bad_sub in ("not-a-number", None, {"nested": 1}):
        token = jwt.encode({"sub": bad_sub}, SECRET, algorithm=ALGORITHM)
        r = await client.get("/api/auth/me", headers=_auth(token))
        assert r.status_code == 401, f"sub={bad_sub!r} -> {r.status_code}"


async def test_signup_maps_a_db_uniqueness_violation_to_409(
    client: AsyncClient, maker, monkeypatch,  # noqa: ANN001
) -> None:
    """The SELECT pre-check races: under concurrent signups the DB constraint is
    what actually rejects the duplicate, and that surfaces as IntegrityError on
    flush. Forced directly here — a real race can't be reproduced against SQLite's
    single shared test connection. Must be 409, and must not half-create a user."""
    import app.api.auth as auth_module

    async def _boom(session, user):  # noqa: ANN001,ANN202
        raise IntegrityError("INSERT INTO users ...", {}, Exception("duplicate key"))

    monkeypatch.setattr(auth_module, "create_collection_scan", _boom)

    r = await client.post("/api/auth/signup", json={
        "username": "alice", "password": "pw12345", "invite_code": INVITE,
        "bandcamp_fan_url": "https://bandcamp.com/alice",
    })
    assert r.status_code == 409, f"got {r.status_code}: {r.text[:200]}"

    async with maker() as s:  # rolled back — no orphaned account left behind
        assert (await s.execute(select(User))).scalars().all() == []


# ── token lifetime is configurable ────────────────────────────────────────────


def test_token_ttl_comes_from_settings() -> None:
    short = Settings(auth_secret_key=SECRET, auth_token_ttl_days=1)
    long = Settings(auth_secret_key=SECRET, auth_token_ttl_days=90)
    exp_short = jwt.decode(
        create_access_token(1, short), SECRET, algorithms=[ALGORITHM]
    )["exp"]
    exp_long = jwt.decode(create_access_token(1, long), SECRET, algorithms=[ALGORITHM])["exp"]
    assert exp_long - exp_short == pytest.approx(89 * 86400, abs=5)
