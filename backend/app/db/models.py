"""ORM models — the baseline schema (M0).

Graph:   bands, albums, tracks, tags, album_tags
Social:  fans, fan_items, album_supporters
Control: follows, blacklist, curation_rules, recommendations
Ops:     crawl_frontier, provider_usage, raw_pages

Enum-typed columns are stored as strings (see app.enums) to keep migrations simple.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.enums import BandKind, CrawlKind, CrawlStatus, ItemType, ScanKind, ScanStatus, TargetType

# JSONB on Postgres; plain JSON elsewhere (e.g. SQLite in tests).
JSONVariant = JSON().with_variant(JSONB, "postgresql")

# ── Core graph ────────────────────────────────────────────────────────────────


class Band(Base, TimestampMixin):
    """A Bandcamp "band" page — either an artist or a label."""

    __tablename__ = "bands"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # Nullable: a band is often discovered by id before its page is scraped. NOT unique —
    # Bandcamp URLs collide across items (single-track albums, remasters, VA comps); the
    # bandcamp_id is the natural key.
    url: Mapped[str | None] = mapped_column(String(512), index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16), default=BandKind.UNKNOWN, index=True)

    albums: Mapped[list["Album"]] = relationship(back_populates="band")
    tracks: Mapped[list["Track"]] = relationship(back_populates="band")


class Album(Base, TimestampMixin):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # Nullable: an album may be known only by id (e.g. a track's parent) pre-scrape.
    # NOT unique (see Band.url) — bandcamp_id is the key.
    url: Mapped[str | None] = mapped_column(String(512), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    band_id: Mapped[int | None] = mapped_column(ForeignKey("bands.id"), index=True)

    band: Mapped["Band | None"] = relationship(back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship(back_populates="album")
    tags: Mapped[list["Tag"]] = relationship(secondary="album_tags", back_populates="albums")


class Track(Base, TimestampMixin):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # NOT unique (see Band.url) — a "track" item can even carry an /album/ URL.
    url: Mapped[str | None] = mapped_column(String(512), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    band_id: Mapped[int | None] = mapped_column(ForeignKey("bands.id"), index=True)

    album: Mapped["Album | None"] = relationship(back_populates="tracks")
    band: Mapped["Band | None"] = relationship(back_populates="tracks")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    albums: Mapped[list["Album"]] = relationship(secondary="album_tags", back_populates="tags")


class AlbumTag(Base):
    __tablename__ = "album_tags"

    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class BandTag(Base):
    """Tags a band carries (aggregated from its releases' album-page tags)."""

    __tablename__ = "band_tags"

    band_id: Mapped[int] = mapped_column(ForeignKey("bands.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class TrackTag(Base):
    """Tags a track carries (inherited from its album page's tags)."""

    __tablename__ = "track_tags"

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


# ── Social graph ───────────────────────────────────────────────────────────────


class Fan(Base, TimestampMixin):
    """A Bandcamp fan (collector). `is_me` is legacy bookkeeping from the single-tenant
    era — the source of truth for "which Fan is this app-user's own account" is now
    `User.fan_id`, not this flag."""

    __tablename__ = "fans"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_fan_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(512), unique=True)
    name: Mapped[str | None] = mapped_column(String(256))
    is_me: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FanItem(Base):
    """Ownership edge: a fan owns an album or a track."""

    __tablename__ = "fan_items"
    __table_args__ = (
        UniqueConstraint("fan_id", "item_type", "album_id", "track_id", name="uq_fan_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fan_id: Mapped[int] = mapped_column(ForeignKey("fans.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(16))  # ItemType
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    # True = wishlisted (not owned). Curation excludes both from recommendations.
    is_wishlist: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AlbumSupporter(Base):
    """Supporter edge: a fan supports (bought) an album."""

    __tablename__ = "album_supporters"

    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id"), primary_key=True)
    fan_id: Mapped[int] = mapped_column(ForeignKey("fans.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TrackSupporter(Base):
    """Supporter edge: a fan supports (bought) a standalone track."""

    __tablename__ = "track_supporters"

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    fan_id: Mapped[int] = mapped_column(ForeignKey("fans.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── App accounts ─────────────────────────────────────────────────────────────


class User(Base, TimestampMixin):
    """An app login. `fan_id` points at the Bandcamp `Fan` row that IS this user
    (set once their collection scan has crawled their fan page) — this is the
    per-tenant replacement for the old global `Fan.is_me` flag. `bandcamp_fan_url`
    is what their collection scan seeds from."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    fan_id: Mapped[int | None] = mapped_column(ForeignKey("fans.id"), unique=True, index=True)
    bandcamp_fan_url: Mapped[str | None] = mapped_column(String(512))


# ── Curation & control ───────────────────────────────────────────────────────


class Follow(Base, TimestampMixin):
    """An artist/label a fan already follows — excluded/down-weighted in curation.
    Scoped per-fan: one tenant following a label must not suppress it for another."""

    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("fan_id", "band_id", name="uq_follow_fan_band"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fan_id: Mapped[int] = mapped_column(ForeignKey("fans.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # TargetType artist|label
    band_id: Mapped[int] = mapped_column(ForeignKey("bands.id"), index=True)


class Like(Base):
    """A recommendation you liked/acted on (wishlisted, followed, bought…). Positive
    dismissal — excluded from future recommendations until your next collection crawl
    reflects the real action."""

    __tablename__ = "likes"
    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "album_id", "track_id", name="uq_like_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(16))  # ItemType
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Blacklist(Base, TimestampMixin):
    """A hidden target. Toggle `active` to un-blacklist without losing history."""

    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(16), index=True)  # TargetType
    band_id: Mapped[int | None] = mapped_column(ForeignKey("bands.id"), index=True)
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)


class CurationRule(Base, TimestampMixin):
    """A named, user-editable rule set (JSON config) applied by the curation engine."""

    __tablename__ = "curation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    config: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Scan(Base, TimestampMixin):
    """A named discovery run with its own seed set. Recommendations are per-scan;
    the exclusion base (collection/wishlist/follows), blocked and liked are shared.
    The row also acts as the job queue: the Mac poller runs `queued` scans."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default=ScanKind.CUSTOM, index=True)
    status: Mapped[str] = mapped_column(String(16), default=ScanStatus.DRAFT, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONVariant, default=dict)  # credits/counts of last run
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seeds: Mapped[list["ScanSeed"]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )


class ScanSeed(Base):
    """A seed source for a scan — a Bandcamp album or track URL, resolved to an
    id once crawled."""

    __tablename__ = "scan_seeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(512))
    seed_type: Mapped[str] = mapped_column(String(16))  # ItemType album|track
    resolved_album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    resolved_track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    scan: Mapped["Scan"] = relationship(back_populates="seeds")


class Recommendation(Base):
    """A computed feed entry with an explainable score. Belongs to one scan."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "scan_id", "item_type", "album_id", "track_id", name="uq_recommendation_item"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(16))  # ItemType
    album_id: Mapped[int | None] = mapped_column(ForeignKey("albums.id"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    reasons: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ── Ops ──────────────────────────────────────────────────────────────────────


class CrawlFrontier(Base, TimestampMixin):
    """Resumable crawl queue: URLs to fetch and their state. **Scoped per scan** —
    each scan walks its own subtree, so one scan can't be held up draining work
    another one queued (a 2026-07-24 operator crawl left 11.5k entries behind, and
    every later scan inherited them).

    The *graph* stays global: bands/albums/tracks/supporters are shared, and an
    entry whose (url, kind) another scan has already crawled completes without
    spending a fetch — its fan-out is replayed from the stored data instead
    (`app.crawl.replay`). So scans are isolated in scheduling, not in knowledge.
    """

    __tablename__ = "crawl_frontier"
    __table_args__ = (
        UniqueConstraint("scan_id", "url", "kind", name="uq_frontier_scan_url_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Required: every entry belongs to exactly one scan. An unowned row is reached
    # by no query and reported by nothing, which is how 11.5k entries sat unnoticed
    # for two weeks. The operator chain resolves a scan too (`crawl.seed`).
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), index=True)
    url: Mapped[str] = mapped_column(String(512), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # CrawlKind
    status: Mapped[str] = mapped_column(String(16), default=CrawlStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # Distance from the seed (seed=0). Bounds the supporter→collection fan-out.
    depth: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    # Resumable-pagination bookmark. A fan collection can run to thousands of items
    # (p90 here is ~1,700), far more than one job should page in one sitting, so a
    # visit pages a bounded slice and parks the next-page tokens here; the entry
    # stays PENDING and the next visit resumes from them instead of restarting.
    # NULL = nothing in flight (never visited, or fully paged).
    # Shape: {"collection": tok|None, "wishlist": tok|None, "follows": tok|None}
    cursor: Mapped[dict | None] = mapped_column(JSONVariant)


class ProviderUsage(Base):
    """One row per scraper request — powers the usage dashboard and cost tracking."""

    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    # Which scan this request was spent on, for per-user budget accounting
    # (`Scan.user_id`). Nullable: rows logged before this column existed, and
    # any fetch not yet attributed at its call site, read as "unattributed"
    # rather than blocking usage logging on having a scan in hand.
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id"), index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    ok: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    quota_remaining: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(String(512))
    parser: Mapped[str | None] = mapped_column(String(128))


class RawPage(Base):
    """Cached parsed payload from a scrape, for reprocessing without re-spending credits."""

    __tablename__ = "raw_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), index=True)
    parser: Mapped[str | None] = mapped_column(String(128), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONVariant)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# Re-export enums for convenience (e.g. `from app.db.models import ItemType`).
__all__ = [
    "Base",
    "Band",
    "Album",
    "Track",
    "Tag",
    "AlbumTag",
    "BandTag",
    "TrackTag",
    "Fan",
    "FanItem",
    "AlbumSupporter",
    "User",
    "Follow",
    "Like",
    "Blacklist",
    "CurationRule",
    "Recommendation",
    "CrawlFrontier",
    "ProviderUsage",
    "RawPage",
    "BandKind",
    "ItemType",
    "TargetType",
    "CrawlKind",
    "CrawlStatus",
]
