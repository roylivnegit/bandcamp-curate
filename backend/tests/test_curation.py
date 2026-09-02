from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.curation.engine import (
    cold_start_diagnostics,
    compute_recommendations,
    curate,
    ensure_collection_scan,
    get_me,
    neighbour_size_report,
)
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    AlbumTag,
    Band,
    BandTag,
    Blacklist,
    Fan,
    FanItem,
    Follow,
    Like,
    Recommendation,
    Scan,
    ScanSeed,
    Tag,
    Track,
    TrackSupporter,
    TrackTag,
    User,
)
from app.enums import BandKind, ItemType, ScanKind, ScanStatus, TargetType


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _recs(s: AsyncSession, user: User, **kw):
    """Compute the collection scan's recommendations (the default feed)."""
    scan = await ensure_collection_scan(s, user)
    return await compute_recommendations(s, scan, user, **kw)


async def _build_graph(s: AsyncSession) -> User:
    """A small world:
      me owns A1(B1, tags rock,jazz) + track T1; wishlists A2; follows B3.
      F2 & F3 both SUPPORT my A1 → both are collection-scan neighbours.
      F2 owns A1, A2, A3(B3), A4(B4, tag rock), T2.
      F3 owns A4, A5(B5).
    Expected recs: A4 (co=2, tag rock matched) > A5 (co=1); T2 (co=1).
    A1 excluded (owned), A2 (wishlist), A3 (band followed). Returns the `User`
    whose `fan_id` is `me`.
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    f2 = Fan(bandcamp_fan_id=2, username="f2", url="https://bandcamp.com/f2")
    f3 = Fan(bandcamp_fan_id=3, username="f3", url="https://bandcamp.com/f3")
    bands = {n: Band(bandcamp_id=n, name=f"B{n}", kind=BandKind.ARTIST) for n in range(1, 6)}
    s.add_all([me, f2, f3, *bands.values()])
    await s.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    s.add(user)
    await s.flush()

    def album(aid, bandnum):
        a = Album(bandcamp_id=aid, title=f"A{aid}", band_id=bands[bandnum].id)
        s.add(a)
        return a

    a1, a2, a3, a4, a5 = album(1, 1), album(2, 2), album(3, 3), album(4, 4), album(5, 5)
    t1 = Track(bandcamp_id=101, title="T1", band_id=bands[1].id)
    t2 = Track(bandcamp_id=102, title="T2", band_id=bands[2].id)
    s.add_all([t1, t2])
    await s.flush()

    rock = Tag(name="rock")
    jazz = Tag(name="jazz")
    s.add_all([rock, jazz])
    await s.flush()
    # my A1 → rock, jazz ; candidate A4 → rock (matches my profile)
    s.add_all([
        AlbumTag(album_id=a1.id, tag_id=rock.id),
        AlbumTag(album_id=a1.id, tag_id=jazz.id),
        AlbumTag(album_id=a4.id, tag_id=rock.id),
    ])

    # ownership edges
    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=me.id, item_type=ItemType.TRACK, track_id=t1.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a2.id, is_wishlist=True),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a3.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a4.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t2.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a4.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a5.id),
        # F2 & F3 support my A1 → they're neighbours of the collection scan.
        AlbumSupporter(album_id=a1.id, fan_id=f2.id),
        AlbumSupporter(album_id=a1.id, fan_id=f3.id),
    ])
    s.add(Follow(fan_id=me.id, band_id=bands[3].id, target_type=TargetType.ARTIST))  # I follow B3
    await s.commit()
    return user


async def test_recommendations_exclude_and_rank(session: AsyncSession) -> None:
    user = await _build_graph(session)
    scored = await _recs(session, user)

    albums = [s for s in scored if s.album_id is not None]
    rec_album_bcids = {}
    for sc in albums:
        a = (await session.execute(select(Album).where(Album.id == sc.album_id))).scalar_one()
        rec_album_bcids[a.bandcamp_id] = sc

    # A1 (owned), A2 (wishlisted), A3 (followed band) are all excluded.
    assert set(rec_album_bcids) == {4, 5}
    # A4 has 2 co-owners (F2,F3) + a matched tag; A5 has 1 → A4 ranks first.
    assert scored[0].album_id == rec_album_bcids[4].album_id
    assert rec_album_bcids[4].reasons["co_owners"] == 2
    assert "rock" in rec_album_bcids[4].reasons["matched_tags"]
    assert rec_album_bcids[4].score > rec_album_bcids[5].score

    # Track T2 (owned by F2) is a candidate; my own T1 is excluded.
    tracks = [s for s in scored if s.track_id is not None]
    assert len(tracks) == 1 and tracks[0].reasons["co_owners"] == 1


async def test_tag_affinity_falls_back_to_band_tags(session: AsyncSession) -> None:
    """Tags mostly live on album *pages*, which the crawl doesn't fetch for most
    albums — an album with zero page-level tags should still pick up its band's
    aggregated tags (`band_tags`), both for MY genre profile and for a
    candidate's matched tags. An album that DOES carry its own page tags must
    keep using only those (no band-tag blending)."""
    me = Fan(bandcamp_fan_id=10, username="me2", url="https://bandcamp.com/me2", is_me=True)
    f2 = Fan(bandcamp_fan_id=11, username="f2b", url="https://bandcamp.com/f2b")
    b1 = Band(bandcamp_id=201, name="B1", kind=BandKind.ARTIST)  # my album's band
    b2 = Band(bandcamp_id=202, name="B2", kind=BandKind.ARTIST)  # untagged candidate's band
    b3 = Band(bandcamp_id=203, name="B3", kind=BandKind.ARTIST)  # own-tagged candidate's band
    session.add_all([me, f2, b1, b2, b3])
    await session.flush()
    user = User(username="me2", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    a1 = Album(bandcamp_id=201, title="A1", band_id=b1.id)  # my own album, no page tags
    a2 = Album(bandcamp_id=202, title="A2", band_id=b2.id)  # candidate, no page tags
    a3 = Album(bandcamp_id=203, title="A3", band_id=b3.id)  # candidate, has its own page tag
    session.add_all([a1, a2, a3])
    await session.flush()

    electronic = Tag(name="electronic")
    jazz = Tag(name="jazz")
    session.add_all([electronic, jazz])
    await session.flush()
    session.add_all([
        BandTag(band_id=b1.id, tag_id=electronic.id),
        BandTag(band_id=b2.id, tag_id=electronic.id),
        BandTag(band_id=b3.id, tag_id=electronic.id),  # must be ignored — A3 has its own tag
        AlbumTag(album_id=a3.id, tag_id=jazz.id),
    ])
    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a3.id),
        AlbumSupporter(album_id=a1.id, fan_id=f2.id),
    ])
    await session.commit()

    scored = await _recs(session, user, min_co_owners=1, weighted_co_owners=False)
    by_bcid = {}
    for sc in scored:
        a = (await session.execute(select(Album).where(Album.id == sc.album_id))).scalar_one()
        by_bcid[a.bandcamp_id] = sc

    # A2: no page tags of its own → falls back to B2's band tag (electronic),
    # which matches my profile (built from A1's band-tag fallback too).
    assert by_bcid[202].reasons["tag_affinity"] == 1
    assert by_bcid[202].reasons["matched_tags"] == ["electronic"]
    # A3: has its own page tag (jazz, not in my profile) → band's "electronic"
    # tag is never consulted, so no affinity and no match.
    assert by_bcid[203].reasons["tag_affinity"] == 0
    assert by_bcid[203].reasons["matched_tags"] == []


async def test_track_tag_affinity_falls_back_to_band_tags(session: AsyncSession) -> None:
    """Same as test_tag_affinity_falls_back_to_band_tags, but for tracks. There's
    no technical difference between an album and a track here — both belong to a
    band and can carry page tags or fall back to band_tags — so a track candidate
    (and a track I own, feeding my own profile) must behave identically to an
    album in the same position, not get silently skipped.

    My owned track's band (B4) is kept separate from my seed album's band (B1),
    with a different tag, so the assertions below can only be explained by the
    OWNED TRACK's contribution — not incidentally by the album's."""
    me = Fan(bandcamp_fan_id=20, username="me3", url="https://bandcamp.com/me3", is_me=True)
    f2 = Fan(bandcamp_fan_id=21, username="f3b", url="https://bandcamp.com/f3b")
    b1 = Band(bandcamp_id=301, name="TB1", kind=BandKind.ARTIST)  # my seed album's band
    b2 = Band(bandcamp_id=302, name="TB2", kind=BandKind.ARTIST)  # untagged candidate track's band
    b3 = Band(bandcamp_id=303, name="TB3", kind=BandKind.ARTIST)  # own-tagged candidate's band
    b4 = Band(bandcamp_id=304, name="TB4", kind=BandKind.ARTIST)  # my owned track's band
    session.add_all([me, f2, b1, b2, b3, b4])
    await session.flush()
    user = User(username="me3", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    a1 = Album(bandcamp_id=301, title="Seed album", band_id=b1.id)  # owned, makes f2 a neighbour
    session.add(a1)
    await session.flush()

    t1 = Track(bandcamp_id=301, title="My track", band_id=b4.id)  # owned, no page tags
    t2 = Track(bandcamp_id=302, title="Candidate no tags", band_id=b2.id)
    t3 = Track(bandcamp_id=303, title="Candidate own tag", band_id=b3.id)
    session.add_all([t1, t2, t3])
    await session.flush()

    downtempo = Tag(name="downtempo")  # A1's band's tag — deliberately not matched below
    electronic = Tag(name="electronic")
    jazz = Tag(name="jazz")
    session.add_all([downtempo, electronic, jazz])
    await session.flush()
    session.add_all([
        BandTag(band_id=b1.id, tag_id=downtempo.id),
        BandTag(band_id=b2.id, tag_id=electronic.id),
        BandTag(band_id=b3.id, tag_id=electronic.id),  # must be ignored — t3 has its own tag
        BandTag(band_id=b4.id, tag_id=electronic.id),  # my owned track's fallback tag
        TrackTag(track_id=t3.id, tag_id=jazz.id),
    ])
    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=me.id, item_type=ItemType.TRACK, track_id=t1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t3.id),
        AlbumSupporter(album_id=a1.id, fan_id=f2.id),
    ])
    await session.commit()

    scored = await _recs(session, user, min_co_owners=1, weighted_co_owners=False)
    by_bcid = {}
    for sc in scored:
        if sc.track_id is None:
            continue
        t = (await session.execute(select(Track).where(Track.id == sc.track_id))).scalar_one()
        by_bcid[t.bandcamp_id] = sc

    # t2: no page tags of its own → falls back to B2's band tag (electronic),
    # which matches my profile — and the ONLY owned item tagged "electronic"
    # (via fallback) is my track t1 (B1/A1's fallback tag is "downtempo").
    # This can only pass if an owned TRACK feeds the profile.
    assert by_bcid[302].reasons["tag_affinity"] == 1
    assert by_bcid[302].reasons["matched_tags"] == ["electronic"]
    # t3: has its own page tag (jazz, not in my profile) → band's "electronic"
    # tag is never consulted, so no affinity and no match.
    assert by_bcid[303].reasons["tag_affinity"] == 0
    assert by_bcid[303].reasons["matched_tags"] == []


async def test_one_recommendation_per_band(session: AsyncSession) -> None:
    user = await _build_graph(session)
    # Give B4 a second candidate album (a6), owned by two neighbours → higher score.
    b4 = (await session.execute(select(Band).where(Band.bandcamp_id == 5))).scalar_one()
    a6 = Album(bandcamp_id=6, title="A6 same band as A5", band_id=b4.id)
    session.add(a6)
    await session.flush()
    f2 = (await session.execute(select(Fan).where(Fan.username == "f2"))).scalar_one()
    f3 = (await session.execute(select(Fan).where(Fan.username == "f3"))).scalar_one()
    session.add_all([
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a6.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a6.id),
    ])
    await session.commit()

    deduped = await _recs(session, user, one_per_band=True)
    band_ids = [s.band_id for s in deduped]
    assert len(band_ids) == len(set(band_ids))  # no band appears twice
    # For band 5, the 2-owner album a6 wins over the 1-owner a5.
    b5_rec = next(s for s in deduped if s.band_id == b4.id)
    assert b5_rec.album_id == a6.id

    full = await _recs(session, user, one_per_band=False)
    assert len(full) > len(deduped)  # dedup actually removed something


async def test_tied_scores_break_ties_deterministically(session: AsyncSession) -> None:
    """Two candidates with the exact same score (same co_owners, zero tag
    affinity on both) must not be left in whatever order the DB happened to
    return their rows in — Postgres doesn't guarantee that order without an
    ORDER BY, so a same-score band of the feed (the common case: "one
    co-owner, no tag data") could silently reshuffle between recomputes. The
    tie should resolve to a stable, reproducible order instead."""
    user = await _build_graph(session)
    b6 = Band(bandcamp_id=6, name="B6", kind=BandKind.ARTIST)
    b7 = Band(bandcamp_id=7, name="B7", kind=BandKind.ARTIST)
    session.add_all([b6, b7])
    await session.flush()
    a10 = Album(bandcamp_id=10, title="A10", band_id=b6.id)
    a11 = Album(bandcamp_id=11, title="A11", band_id=b7.id)
    session.add_all([a10, a11])
    await session.flush()
    f2 = (await session.execute(select(Fan).where(Fan.username == "f2"))).scalar_one()
    # Same single owner, no tags on either → identical co_owners and tag_affinity.
    session.add_all([
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a10.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a11.id),
    ])
    await session.commit()

    scored = await _recs(session, user)
    tied = [s for s in scored if s.album_id in (a10.id, a11.id)]
    assert len(tied) == 2
    assert tied[0].score == tied[1].score
    assert tied[0].reasons["co_owners"] == tied[1].reasons["co_owners"] == 1

    order = [s.album_id for s in tied]
    # Recomputing repeatedly must always reproduce the same order.
    for _ in range(3):
        again = await _recs(session, user)
        again_order = [s.album_id for s in again if s.album_id in (a10.id, a11.id)]
        assert again_order == order


async def test_curate_persists_and_is_idempotent(session: AsyncSession) -> None:
    user = await _build_graph(session)
    scored = await curate(session, user=user)
    assert await _count(session, Recommendation) == len(scored)
    # Re-running replaces, doesn't duplicate.
    again = await curate(session, user=user)
    assert await _count(session, Recommendation) == len(again) == len(scored)


async def test_blacklist_excludes_candidate(session: AsyncSession) -> None:
    user = await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    session.add(
        Blacklist(user_id=user.id, target_type=str(TargetType.ALBUM), album_id=a4.id, active=True)
    )
    await session.commit()

    scored = await _recs(session, user)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a4.id not in rec_album_ids  # blacklisted → gone


async def test_expired_blacklist_stops_excluding(session: AsyncSession) -> None:
    """A "not now" block (expires_at set) must stop excluding once past —
    without anyone unblocking it by hand — while a future or absent expiry
    still suppresses the candidate."""
    user = await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    now = datetime.now(UTC)
    session.add(
        Blacklist(
            user_id=user.id, target_type=str(TargetType.ALBUM), album_id=a4.id,
            active=True, expires_at=now - timedelta(hours=1),
        )
    )
    await session.commit()

    scored = await _recs(session, user)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a4.id in rec_album_ids  # expired → back in the feed


async def test_future_expiry_still_excludes(session: AsyncSession) -> None:
    user = await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    now = datetime.now(UTC)
    session.add(
        Blacklist(
            user_id=user.id, target_type=str(TargetType.ALBUM), album_id=a4.id,
            active=True, expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    scored = await _recs(session, user)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a4.id not in rec_album_ids  # not expired yet → still excluded


async def test_follow_by_label_url_excludes_albums_on_that_page(
    session: AsyncSession,
) -> None:
    # Follow a LABEL (band 3, url label.bandcamp.com). A neighbour owns an album on
    # that label's page whose stored band is a *different* id (the artist). band_id
    # matching would miss it; host matching must catch it.
    user = await _build_graph(session)
    label = (await session.execute(select(Band).where(Band.bandcamp_id == 3))).scalar_one()
    label.url = "https://label.bandcamp.com"
    artist = Band(bandcamp_id=99, name="Artist On Label", kind=BandKind.ARTIST)
    session.add(artist)
    await session.flush()
    # album on the label's page, band = the artist (not followed by id)
    a = Album(bandcamp_id=900, title="On The Label",
              url="https://label.bandcamp.com/album/x", band_id=artist.id)
    session.add(a)
    await session.flush()
    f2 = (await session.execute(select(Fan).where(Fan.username == "f2"))).scalar_one()
    session.add(FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a.id))
    await session.commit()

    scored = await _recs(session, user)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a.id not in rec_album_ids  # excluded via followed label's URL host


async def test_seed_tag_provenance_and_exclusion(session: AsyncSession) -> None:
    # me owns A1 (tagged rock,jazz). f2 supports A1 (from _build_graph) and owns A4.
    # So A4's seed provenance = {rock, jazz}. Excluding "rock" drops A4.
    user = await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()

    scored = await _recs(session, user)
    a4_rec = next(s for s in scored if s.album_id == a4.id)
    assert set(a4_rec.reasons["seed_tags"]) == {"rock", "jazz"}  # provenance recorded

    filtered = await _recs(session, user, exclude_seed_tags={"rock"})
    assert a4.id not in {s.album_id for s in filtered}  # generated-from-rock → gone


async def test_seed_tag_provenance_falls_back_to_band_tags(session: AsyncSession) -> None:
    """A seed album with no page-level tags of its own must still produce "via …"
    provenance from its band's aggregated tags — same fallback
    `_effective_album_tags` already applies when scoring, now applied to the
    *seed* side of provenance too, not just the candidate side."""
    me = Fan(bandcamp_fan_id=30, username="me4", url="https://bandcamp.com/me4", is_me=True)
    f2 = Fan(bandcamp_fan_id=31, username="f4", url="https://bandcamp.com/f4")
    seed_band = Band(bandcamp_id=401, name="SeedBand", kind=BandKind.ARTIST)
    cand_band = Band(bandcamp_id=402, name="CandBand", kind=BandKind.ARTIST)
    session.add_all([me, f2, seed_band, cand_band])
    await session.flush()
    user = User(username="me4", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    seed_album = Album(bandcamp_id=401, title="Seed", band_id=seed_band.id)  # no page tags
    cand_album = Album(bandcamp_id=402, title="Cand", band_id=cand_band.id)
    session.add_all([seed_album, cand_album])
    await session.flush()

    electronic = Tag(name="electronic")
    session.add(electronic)
    await session.flush()
    session.add(BandTag(band_id=seed_band.id, tag_id=electronic.id))  # band-level only

    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=cand_album.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=f2.id),
    ])
    await session.commit()

    scored = await _recs(session, user, min_co_owners=1)
    cand_rec = next(s for s in scored if s.album_id == cand_album.id)
    assert set(cand_rec.reasons["seed_tags"]) == {"electronic"}


async def test_seed_tags_lists_my_album_genres(session: AsyncSession) -> None:
    from app.curation.engine import seed_tags

    user = await _build_graph(session)  # my A1 is tagged rock + jazz
    genres = dict(await seed_tags(session, user))
    assert genres.get("rock") == 1 and genres.get("jazz") == 1


async def test_liked_item_excludes_its_band(session: AsyncSession) -> None:
    user = await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    # A sibling album on the SAME band as a4, owned by a neighbour.
    a7 = Album(bandcamp_id=7, title="Sibling", band_id=a4.band_id)
    session.add(a7)
    await session.flush()
    f3 = (await session.execute(select(Fan).where(Fan.username == "f3"))).scalar_one()
    session.add(FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a7.id))
    await session.commit()

    before = {s.album_id for s in await _recs(session, user)}
    assert a4.id in before  # (a7 shares a4's band → deduped to one, but band present)

    # Liking a4 excludes its whole band → neither a4 nor its sibling a7 appear.
    session.add(Like(user_id=user.id, item_type=str(ItemType.ALBUM), album_id=a4.id))
    await session.commit()
    after = {s.album_id for s in await _recs(session, user)}
    assert a4.id not in after and a7.id not in after


async def test_custom_scan_track_seed_finds_neighbours(session: AsyncSession) -> None:
    # A custom scan seeded by a TRACK (not an album): its neighbours must come
    # from TrackSupporter, or the scan would silently produce zero recs.
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    neighbour = Fan(bandcamp_fan_id=2, username="neighbour", url="https://bandcamp.com/neighbour")
    seed_band = Band(bandcamp_id=10, name="SeedBand", kind=BandKind.ARTIST)
    rec_band = Band(bandcamp_id=20, name="RecBand", kind=BandKind.ARTIST)
    session.add_all([me, neighbour, seed_band, rec_band])
    await session.flush()

    seed_track = Track(
        bandcamp_id=100, title="Seed Track", band_id=seed_band.id,
        url="https://seedband.bandcamp.com/track/seed-track",
    )
    rec_album = Album(
        bandcamp_id=200, title="Rec Album", band_id=rec_band.id,
        url="https://recband.bandcamp.com/album/rec-album",
    )
    session.add_all([seed_track, rec_album])
    await session.flush()

    session.add(TrackSupporter(track_id=seed_track.id, fan_id=neighbour.id))
    session.add(FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=rec_album.id))
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    scan = Scan(
        user_id=user.id, name="track scan",
        kind=str(ScanKind.CUSTOM), status=str(ScanStatus.RUNNING),
    )
    session.add(scan)
    await session.flush()
    session.add(ScanSeed(
        scan_id=scan.id, url=seed_track.url, seed_type="track",
        resolved_track_id=seed_track.id,
    ))
    await session.commit()

    scored = await compute_recommendations(session, scan, user)
    assert len(scored) == 1
    assert scored[0].album_id == rec_album.id
    assert scored[0].reasons["co_owners"] == 1


async def test_custom_scan_mixed_album_and_track_seeds_union_neighbours(
    session: AsyncSession,
) -> None:
    # One neighbour found via an album seed, another via a track seed — both
    # must count toward co-ownership.
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    album_neighbour = Fan(bandcamp_fan_id=2, username="an", url="https://bandcamp.com/an")
    track_neighbour = Fan(bandcamp_fan_id=3, username="tn", url="https://bandcamp.com/tn")
    seed_band_a = Band(bandcamp_id=10, name="SeedBandA", kind=BandKind.ARTIST)
    seed_band_t = Band(bandcamp_id=11, name="SeedBandT", kind=BandKind.ARTIST)
    rec_band = Band(bandcamp_id=20, name="RecBand", kind=BandKind.ARTIST)
    session.add_all([me, album_neighbour, track_neighbour, seed_band_a, seed_band_t, rec_band])
    await session.flush()

    seed_album = Album(
        bandcamp_id=100, title="Seed Album", band_id=seed_band_a.id,
        url="https://seedbanda.bandcamp.com/album/seed-album",
    )
    seed_track = Track(
        bandcamp_id=101, title="Seed Track", band_id=seed_band_t.id,
        url="https://seedbandt.bandcamp.com/track/seed-track",
    )
    rec_album = Album(
        bandcamp_id=200, title="Rec Album", band_id=rec_band.id,
        url="https://recband.bandcamp.com/album/rec-album",
    )
    session.add_all([seed_album, seed_track, rec_album])
    await session.flush()

    session.add(AlbumSupporter(album_id=seed_album.id, fan_id=album_neighbour.id))
    session.add(TrackSupporter(track_id=seed_track.id, fan_id=track_neighbour.id))
    session.add_all([
        FanItem(fan_id=album_neighbour.id, item_type=ItemType.ALBUM, album_id=rec_album.id),
        FanItem(fan_id=track_neighbour.id, item_type=ItemType.ALBUM, album_id=rec_album.id),
    ])
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    scan = Scan(
        user_id=user.id, name="mixed scan",
        kind=str(ScanKind.CUSTOM), status=str(ScanStatus.RUNNING),
    )
    session.add(scan)
    await session.flush()
    session.add_all([
        ScanSeed(scan_id=scan.id, url=seed_album.url, seed_type="album",
                 resolved_album_id=seed_album.id),
        ScanSeed(scan_id=scan.id, url=seed_track.url, seed_type="track",
                 resolved_track_id=seed_track.id),
    ])
    await session.commit()

    scored = await compute_recommendations(session, scan, user)
    assert len(scored) == 1
    assert scored[0].reasons["co_owners"] == 2  # both neighbours counted


async def test_get_me_requires_seed(session: AsyncSession) -> None:
    import pytest

    user = User(username="me", password_hash="!")  # fan_id not set yet
    session.add(user)
    await session.flush()
    with pytest.raises(ValueError, match="collection not yet crawled"):
        await get_me(session, user)


# ── ADR-0002: co-ownership floor + weight ─────────────────────────────────────


async def test_parity_default_floor_and_weighting_off_matches_original_formula(
    session: AsyncSession,
) -> None:
    """floor=1 (no-op) + weighting off must reproduce the pre-ADR score exactly:
    W_CO_OWNER * co_owners + W_TAG_AFFINITY * tag_affinity, no per-neighbour term."""
    user = await _build_graph(session)
    scored = await _recs(session, user, min_co_owners=1, weighted_co_owners=False)

    by_key: dict[tuple[str, int], object] = {}
    for sc in scored:
        if sc.album_id is not None:
            a = (await session.execute(select(Album).where(Album.id == sc.album_id))).scalar_one()
            by_key[("album", a.bandcamp_id)] = sc
        else:
            t = (await session.execute(select(Track).where(Track.id == sc.track_id))).scalar_one()
            by_key[("track", t.bandcamp_id)] = sc

    assert set(by_key) == {("album", 4), ("album", 5), ("track", 102)}
    assert by_key[("album", 4)].reasons["co_owner_weight"] == 2  # == co_owners, no weighting
    assert by_key[("album", 4)].score == 1.0 * 2 + 0.25 * 1  # co_owners=2, tag_affinity=1
    assert by_key[("album", 5)].score == 1.0 * 1  # co_owners=1, no tags
    assert by_key[("track", 102)].score == 1.0 * 1  # co_owners=1


async def test_weighting_reorders_never_shrinks_membership(session: AsyncSession) -> None:
    user = await _build_graph(session)
    off = await _recs(session, user, min_co_owners=1, weighted_co_owners=False)
    on = await _recs(session, user, min_co_owners=1, weighted_co_owners=True)
    ids_off = {(s.item_type, s.album_id, s.track_id) for s in off}
    ids_on = {(s.item_type, s.album_id, s.track_id) for s in on}
    assert ids_off == ids_on  # weighting changes score/order, never who's in the feed


async def _build_mega_vs_tight_graph(session: AsyncSession) -> tuple[User, dict[str, int]]:
    """me owns a seed album (anchors `mega`/`tight` as this scan's neighbours)
    plus 10 other albums (the basis for overlap weighting). `mega` has a LARGE
    collection (20 unrelated albums) but shares only 2 of my 10; `tight` has a
    much smaller collection but shares 8 of my 10. Each also owns one exclusive
    album and one exclusive track that nobody else owns, so any rank difference
    between those exclusives comes purely from the per-neighbour weight — not
    from co-owner count (both are 1) or collection size (mega's is bigger).
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    mega = Fan(bandcamp_fan_id=2, username="mega", url="https://bandcamp.com/mega")
    tight = Fan(bandcamp_fan_id=3, username="tight", url="https://bandcamp.com/tight")
    band_seed = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    band_noise = Band(bandcamp_id=2, name="Noise", kind=BandKind.ARTIST)
    band_x = Band(bandcamp_id=3, name="X", kind=BandKind.ARTIST)
    band_y = Band(bandcamp_id=4, name="Y", kind=BandKind.ARTIST)
    band_tx = Band(bandcamp_id=5, name="TX", kind=BandKind.ARTIST)
    band_ty = Band(bandcamp_id=6, name="TY", kind=BandKind.ARTIST)
    session.add_all([me, mega, tight, band_seed, band_noise, band_x, band_y, band_tx, band_ty])
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=band_seed.id)
    my_extra = [
        Album(bandcamp_id=100 + i, title=f"My{i}", band_id=band_seed.id) for i in range(10)
    ]
    unrelated = [
        Album(bandcamp_id=200 + i, title=f"U{i}", band_id=band_noise.id) for i in range(20)
    ]
    item_x = Album(bandcamp_id=900, title="ItemX", band_id=band_x.id)
    item_y = Album(bandcamp_id=901, title="ItemY", band_id=band_y.id)
    track_x = Track(bandcamp_id=9100, title="TrackX", band_id=band_tx.id)
    track_y = Track(bandcamp_id=9101, title="TrackY", band_id=band_ty.id)
    session.add_all([seed_album, *my_extra, *unrelated, item_x, item_y, track_x, track_y])
    await session.flush()

    session.add_all(
        [
            FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
            *(FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a.id) for a in my_extra),
            AlbumSupporter(album_id=seed_album.id, fan_id=mega.id),
            AlbumSupporter(album_id=seed_album.id, fan_id=tight.id),
            *(
                FanItem(fan_id=mega.id, item_type=ItemType.ALBUM, album_id=a.id)
                for a in unrelated
            ),
            *(
                FanItem(fan_id=mega.id, item_type=ItemType.ALBUM, album_id=a.id)
                for a in my_extra[:2]
            ),
            FanItem(fan_id=mega.id, item_type=ItemType.ALBUM, album_id=item_x.id),
            FanItem(fan_id=mega.id, item_type=ItemType.TRACK, track_id=track_x.id),
            *(
                FanItem(fan_id=tight.id, item_type=ItemType.ALBUM, album_id=a.id)
                for a in my_extra[:8]
            ),
            FanItem(fan_id=tight.id, item_type=ItemType.ALBUM, album_id=item_y.id),
            FanItem(fan_id=tight.id, item_type=ItemType.TRACK, track_id=track_y.id),
        ]
    )
    await session.commit()
    return user, {
        "item_x": item_x.id, "item_y": item_y.id,
        "track_x": track_x.id, "track_y": track_y.id,
    }


async def test_mega_collector_loses_to_tight_overlap_album(session: AsyncSession) -> None:
    user, ids = await _build_mega_vs_tight_graph(session)
    scored = await _recs(session, user, one_per_band=False)

    by_album = {s.album_id: s for s in scored if s.album_id is not None}
    x, y = by_album[ids["item_x"]], by_album[ids["item_y"]]
    assert x.reasons["co_owners"] == y.reasons["co_owners"] == 1  # same raw co-owner count
    assert y.reasons["co_owner_weight"] > x.reasons["co_owner_weight"]  # tight beats mega
    assert y.score > x.score
    assert scored.index(y) < scored.index(x)  # tight's pick ranks above mega's


async def test_mega_collector_loses_to_tight_overlap_track(session: AsyncSession) -> None:
    # The track loop has no tag term (unlike albums), so this repeats the mega-vs-
    # tight assertion independently for the loop most likely to be left behind.
    user, ids = await _build_mega_vs_tight_graph(session)
    scored = await _recs(session, user, one_per_band=False)

    by_track = {s.track_id: s for s in scored if s.track_id is not None}
    x, y = by_track[ids["track_x"]], by_track[ids["track_y"]]
    assert x.reasons["co_owners"] == y.reasons["co_owners"] == 1
    assert y.reasons["co_owner_weight"] > x.reasons["co_owner_weight"]
    assert y.score > x.score
    assert scored.index(y) < scored.index(x)


async def test_floor_cuts_both_loops(session: AsyncSession) -> None:
    """A band whose only candidates are a 1-co-owner album and a 1-co-owner
    track produces zero recs at floor 2 — the floor must apply to both loops,
    not just the album one."""
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    neighbour = Fan(bandcamp_fan_id=2, username="n", url="https://bandcamp.com/n")
    band_seed = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    band_thin = Band(bandcamp_id=2, name="Thin", kind=BandKind.ARTIST)
    session.add_all([me, neighbour, band_seed, band_thin])
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=band_seed.id)
    thin_album = Album(bandcamp_id=2, title="ThinAlbum", band_id=band_thin.id)
    thin_track = Track(bandcamp_id=100, title="ThinTrack", band_id=band_thin.id)
    session.add_all([seed_album, thin_album, thin_track])
    await session.flush()

    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=neighbour.id),
        FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=thin_album.id),
        FanItem(fan_id=neighbour.id, item_type=ItemType.TRACK, track_id=thin_track.id),
    ])
    await session.commit()

    stats: dict = {}
    scan = await ensure_collection_scan(session, user)
    scored = await compute_recommendations(
        session, scan, user, min_co_owners=2, weighted_co_owners=False, stats_out=stats,
    )
    assert scored == []
    assert stats["filtered_by_floor"] == 2  # the album and the track, one each
    assert stats["candidates"] == 2
    assert stats["min_co_owners"] == 2


async def test_filtered_by_floor_counter_excludes_already_excluded_items(
    session: AsyncSession,
) -> None:
    user = await _build_graph(session)
    stats: dict = {}
    scored = await _recs(session, user, min_co_owners=2, stats_out=stats)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()

    # A4 (co=2) survives; A5 (co=1) and T2 (co=1) are cut by the floor. A1/A2/A3
    # never reach the floor check at all — build_exclusions removes them first,
    # so they must not inflate filtered_by_floor.
    assert {s.album_id for s in scored if s.album_id} == {a4.id}
    assert stats["filtered_by_floor"] == 2
    assert stats["candidates"] == 3  # A4, A5, T2 — the only items that reach the floor check


async def test_cold_start_diagnostics_counts_neighbours_candidates_and_reasons(
    session: AsyncSession,
) -> None:
    user = await _build_graph(session)
    scan = await ensure_collection_scan(session, user)
    diag = await cold_start_diagnostics(session, scan, user)

    # f2 & f3 both support my A1 → 2 neighbours.
    assert diag.neighbour_count == 2
    # Distinct items neighbours own, before any exclusion: albums A1-A5 + track T2.
    assert diag.candidates == 6
    # A1 is mine (owned), A2 is wishlisted, A3's band (B3) is followed, none blacklisted.
    assert diag.excluded_by_reason == {
        "owned": 1, "wishlisted": 1, "followed": 1, "blacklisted": 0,
    }


async def test_cold_start_diagnostics_everything_excluded_by_follows(
    session: AsyncSession,
) -> None:
    """A fixture where the neighbour's only candidate is from a band I follow —
    asserts `excluded_by_reason.followed` is nonzero and accounts for every
    candidate, distinguishing "found neighbours but their stuff is all in my
    world already" from "found nothing at all"."""
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    neighbour = Fan(bandcamp_fan_id=2, username="n", url="https://bandcamp.com/n")
    seed_band = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    followed_band = Band(bandcamp_id=2, name="Followed", kind=BandKind.ARTIST)
    session.add_all([me, neighbour, seed_band, followed_band])
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=seed_band.id)
    followed_album = Album(bandcamp_id=2, title="FromFollowed", band_id=followed_band.id)
    session.add_all([seed_album, followed_album])
    await session.flush()

    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=neighbour.id),
        FanItem(fan_id=neighbour.id, item_type=ItemType.ALBUM, album_id=followed_album.id),
        Follow(fan_id=me.id, band_id=followed_band.id, target_type=TargetType.ARTIST),
    ])
    await session.commit()

    scan = await ensure_collection_scan(session, user)
    diag = await cold_start_diagnostics(session, scan, user)

    assert diag.neighbour_count == 1
    assert diag.candidates == 1
    assert diag.excluded_by_reason["followed"] == 1
    assert diag.excluded_by_reason["owned"] == 0
    assert diag.excluded_by_reason["wishlisted"] == 0
    assert diag.excluded_by_reason["blacklisted"] == 0


async def test_cold_start_diagnostics_no_neighbours(session: AsyncSession) -> None:
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    session.add(me)
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.commit()
    scan = await ensure_collection_scan(session, user)

    diag = await cold_start_diagnostics(session, scan, user)
    assert diag.neighbour_count == 0
    assert diag.candidates == 0
    assert diag.excluded_by_reason == {
        "owned": 0, "wishlisted": 0, "followed": 0, "blacklisted": 0,
    }


async def test_settings_reach_engine_with_no_kwargs(session: AsyncSession, monkeypatch) -> None:
    """The four real call sites never pass min_co_owners/weighted_co_owners —
    they all rely on compute_recommendations reading Settings directly. Prove a
    bare call (no kwargs) picks up a patched setting, or the mid-crawl feed and
    the finalized feed could silently disagree."""
    import app.curation.engine as engine
    from app.config import Settings

    user = await _build_graph(session)
    monkeypatch.setattr(
        engine, "get_settings",
        lambda: Settings(curation_min_co_owners=2, curation_weighted_co_owners=False),
    )

    scan = await ensure_collection_scan(session, user)
    scored = await compute_recommendations(session, scan, user)  # no kwargs at all
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    # min_co_owners=2 from the patched settings: A5(co=1)/T2(co=1) are cut.
    assert {s.album_id for s in scored if s.album_id} == {a4.id}
    assert {s.track_id for s in scored if s.track_id} == set()


# ── ADR-0003: bound the co-owner weight (amends ADR-0002) ─────────────────────


async def _build_scale_gap_graph(session: AsyncSession) -> tuple[User, dict[str, int]]:
    """me owns a seed album (anchors neighbours) plus a 200-album overlap pool.
    50 'tight' fans each share only 2 of those 200 but jointly own TightItem (50
    co-owners); one 'whale' fan shares all 200 but is the sole owner of WhaleItem
    (1 co-owner). Unbounded-linear weighting (1 + overlap) scores WhaleItem at
    201 against TightItem's 50 * 3 = 150 — the whale wins, which is exactly the
    inversion ADR-0003 exists to fix. Damped, TightItem must win."""
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    session.add(me)
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)

    band_seed = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    band_pool = Band(bandcamp_id=2, name="Pool", kind=BandKind.ARTIST)
    band_tight = Band(bandcamp_id=3, name="TightBand", kind=BandKind.ARTIST)
    band_whale = Band(bandcamp_id=4, name="WhaleBand", kind=BandKind.ARTIST)
    session.add_all([band_seed, band_pool, band_tight, band_whale])
    await session.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=band_seed.id)
    pool = [Album(bandcamp_id=100 + i, title=f"Pool{i}", band_id=band_pool.id) for i in range(200)]
    tight_item = Album(bandcamp_id=900, title="TightItem", band_id=band_tight.id)
    whale_item = Album(bandcamp_id=901, title="WhaleItem", band_id=band_whale.id)
    session.add_all([seed_album, *pool, tight_item, whale_item])
    await session.flush()

    tight_fans = [
        Fan(bandcamp_fan_id=10 + i, username=f"tight{i}", url=f"https://bandcamp.com/tight{i}")
        for i in range(50)
    ]
    whale = Fan(bandcamp_fan_id=500, username="whale", url="https://bandcamp.com/whale")
    session.add_all([*tight_fans, whale])
    await session.flush()

    rows = [FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id)]
    rows += [FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a.id) for a in pool]
    for f in tight_fans:
        rows.append(AlbumSupporter(album_id=seed_album.id, fan_id=f.id))
        rows.append(FanItem(fan_id=f.id, item_type=ItemType.ALBUM, album_id=pool[0].id))
        rows.append(FanItem(fan_id=f.id, item_type=ItemType.ALBUM, album_id=pool[1].id))
        rows.append(FanItem(fan_id=f.id, item_type=ItemType.ALBUM, album_id=tight_item.id))
    rows.append(AlbumSupporter(album_id=seed_album.id, fan_id=whale.id))
    rows += [FanItem(fan_id=whale.id, item_type=ItemType.ALBUM, album_id=a.id) for a in pool]
    rows.append(FanItem(fan_id=whale.id, item_type=ItemType.ALBUM, album_id=whale_item.id))

    session.add_all(rows)
    await session.commit()
    return user, {"tight_item": tight_item.id, "whale_item": whale_item.id}


async def test_scale_gap_many_tight_beats_one_whale(session: AsyncSession) -> None:
    user, ids = await _build_scale_gap_graph(session)
    scored = await _recs(session, user, one_per_band=False, weighted_co_owners=True)
    by_album = {s.album_id: s for s in scored if s.album_id is not None}
    tight, whale = by_album[ids["tight_item"]], by_album[ids["whale_item"]]
    assert tight.reasons["co_owners"] == 50
    assert whale.reasons["co_owners"] == 1
    assert tight.score > whale.score
    assert scored.index(tight) < scored.index(whale)


async def _build_tag_ceiling_graph(session: AsyncSession) -> tuple[User, dict[str, int]]:
    """me owns a seed album plus 500 albums carrying one genre tag — an extreme
    tag_profile. TaggedItem has 1 co-owner and carries that tag; PlainItem has 3
    co-owners and no matching tag. The tag term must not let TaggedItem outrank
    PlainItem — it is a tie-breaker between items with the SAME co-owner count,
    not a second axis that can outweigh a real second or third co-owner."""
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    session.add(me)
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)

    band_seed = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    band_pool = Band(bandcamp_id=2, name="Pool", kind=BandKind.ARTIST)
    band_tagged = Band(bandcamp_id=3, name="Tagged", kind=BandKind.ARTIST)
    band_plain = Band(bandcamp_id=4, name="Plain", kind=BandKind.ARTIST)
    session.add_all([band_seed, band_pool, band_tagged, band_plain])
    await session.flush()

    tag = Tag(name="megagenre")
    session.add(tag)
    await session.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=band_seed.id)
    pool = [Album(bandcamp_id=100 + i, title=f"Pool{i}", band_id=band_pool.id) for i in range(500)]
    tagged_item = Album(bandcamp_id=900, title="TaggedItem", band_id=band_tagged.id)
    plain_item = Album(bandcamp_id=901, title="PlainItem", band_id=band_plain.id)
    session.add_all([seed_album, *pool, tagged_item, plain_item])
    await session.flush()

    session.add_all(
        [AlbumTag(album_id=a.id, tag_id=tag.id) for a in pool]
        + [AlbumTag(album_id=tagged_item.id, tag_id=tag.id)]
    )

    lone_fan = Fan(bandcamp_fan_id=10, username="one", url="https://bandcamp.com/one")
    trio = [
        Fan(bandcamp_fan_id=20 + i, username=f"three{i}", url=f"https://bandcamp.com/three{i}")
        for i in range(3)
    ]
    session.add_all([lone_fan, *trio])
    await session.flush()

    rows = [FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id)]
    rows += [FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a.id) for a in pool]
    rows.append(AlbumSupporter(album_id=seed_album.id, fan_id=lone_fan.id))
    rows.append(FanItem(fan_id=lone_fan.id, item_type=ItemType.ALBUM, album_id=tagged_item.id))
    for f in trio:
        rows.append(AlbumSupporter(album_id=seed_album.id, fan_id=f.id))
        rows.append(FanItem(fan_id=f.id, item_type=ItemType.ALBUM, album_id=plain_item.id))

    session.add_all(rows)
    await session.commit()
    return user, {"tagged_item": tagged_item.id, "plain_item": plain_item.id}


async def test_tag_ceiling_cannot_outrank_a_second_co_owner(session: AsyncSession) -> None:
    user, ids = await _build_tag_ceiling_graph(session)
    scored = await _recs(session, user, one_per_band=False, weighted_co_owners=True)
    by_album = {s.album_id: s for s in scored if s.album_id is not None}
    tagged, plain = by_album[ids["tagged_item"]], by_album[ids["plain_item"]]
    assert tagged.reasons["co_owners"] == 1
    assert plain.reasons["co_owners"] == 3
    assert tagged.reasons["tag_affinity"] == 500  # the raw sum stays unbounded, only score damps
    assert plain.score > tagged.score
    assert scored.index(plain) < scored.index(tagged)


def test_damped_overlap_weight_is_sublinear_in_overlap() -> None:
    """10x more overlap must not move a co-owner's own weight anywhere near 10x
    — sublinearity is what keeps a deeply-crawled or huge-collection neighbour
    from drowning out many tight-overlap ones (ADR-0003)."""
    from app.curation.engine import _damped_overlap_weight

    for overlap in (5, 20, 50, 100, 500, 1700):
        assert _damped_overlap_weight(overlap * 10) < 2 * _damped_overlap_weight(overlap)


async def _count(session: AsyncSession, model) -> int:
    from sqlalchemy import func

    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _build_neighbour_size_graph(session: AsyncSession) -> User:
    """A small world for `neighbour_size_report`:
      me owns A1(B1) only.
      f_small supports A1 (neighbour) and owns A1 + A2(B2) — collection size 2.
      f_mega supports A1 (neighbour) and owns A1 + A3(B3) + A4(B4) + A5(B5) —
      collection size 4, and 3x f_small's raw candidate votes (A3, A4, A5 vs A2).
    Both share the exact same overlap-with-me (1, from owning A1), so the ADR-0003
    weighted split should come out even between them despite f_mega owning 2x as
    much and casting 3x the raw votes — that gap is exactly what the raw
    `co_owners`/`min_co_owners` floor doesn't correct for.
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    f_small = Fan(bandcamp_fan_id=2, username="small", url="https://bandcamp.com/small")
    f_mega = Fan(bandcamp_fan_id=3, username="mega", url="https://bandcamp.com/mega")
    bands = {n: Band(bandcamp_id=100 + n, name=f"B{n}", kind=BandKind.ARTIST) for n in range(1, 5)}
    session.add_all([me, f_small, f_mega, *bands.values()])
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.flush()

    def album(aid, bandnum):
        a = Album(bandcamp_id=200 + aid, title=f"A{aid}", band_id=bands[bandnum].id)
        session.add(a)
        return a

    a1, a2, a3, a4, a5 = album(1, 1), album(2, 2), album(3, 3), album(4, 4), album(5, 4)
    await session.flush()

    session.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f_small.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f_small.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f_mega.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f_mega.id, item_type=ItemType.ALBUM, album_id=a3.id),
        FanItem(fan_id=f_mega.id, item_type=ItemType.ALBUM, album_id=a4.id),
        FanItem(fan_id=f_mega.id, item_type=ItemType.ALBUM, album_id=a5.id),
        AlbumSupporter(album_id=a1.id, fan_id=f_small.id),
        AlbumSupporter(album_id=a1.id, fan_id=f_mega.id),
    ])
    await session.commit()
    return user


async def test_neighbour_size_report_buckets_by_recorded_collection_size(
    session: AsyncSession,
) -> None:
    user = await _build_neighbour_size_graph(session)
    scan = await ensure_collection_scan(session, user)
    rows = await neighbour_size_report(session, scan, user, buckets=(3,))
    by_bucket = {r["bucket"]: r for r in rows}

    assert set(by_bucket) == {"0-3", "3+"}
    small, mega = by_bucket["0-3"], by_bucket["3+"]

    # f_small (size 2) lands below the boundary, f_mega (size 4) at/above it.
    assert small["neighbours"] == 1
    assert mega["neighbours"] == 1
    assert small["neighbour_share"] == mega["neighbour_share"] == 0.5

    # f_mega casts 3 raw votes (A3, A4, A5) vs f_small's 1 (A2) — its vote share
    # badly outruns its neighbour share, which is the concern the backlog raises.
    assert small["votes"] == 1
    assert mega["votes"] == 3
    assert small["vote_share"] == 0.25
    assert mega["vote_share"] == 0.75

    # Both own exactly one of MY albums (A1), so their overlap-with-me — and
    # therefore the ADR-0003 weighted share — comes out even despite the gap above.
    assert small["raw_overlap"] == mega["raw_overlap"] == 1
    assert small["weighted_share"] == pytest.approx(0.5)
    assert mega["weighted_share"] == pytest.approx(0.5)


async def test_neighbour_size_report_empty_without_neighbours(session: AsyncSession) -> None:
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    session.add(me)
    await session.flush()
    user = User(username="me", password_hash="!", fan_id=me.id)
    session.add(user)
    await session.commit()
    scan = await ensure_collection_scan(session, user)

    assert await neighbour_size_report(session, scan, user) == []
