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
from app.enums import BandKind, CrawlKind, CrawlStatus, ItemType, TargetType

# JSONB on Postgres; plain JSON elsewhere (e.g. SQLite in tests).
JSONVariant = JSON().with_variant(JSONB, "postgresql")

# ── Core graph ────────────────────────────────────────────────────────────────


class Band(Base, TimestampMixin):
    """A Bandcamp "band" page — either an artist or a label."""

    __tablename__ = "bands"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # Nullable: a band is often discovered by id before its page is scraped.
    url: Mapped[str | None] = mapped_column(String(512), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16), default=BandKind.UNKNOWN, index=True)

    albums: Mapped[list["Album"]] = relationship(back_populates="band")
    tracks: Mapped[list["Track"]] = relationship(back_populates="band")


class Album(Base, TimestampMixin):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    # Nullable: an album may be known only by id (e.g. a track's parent) pre-scrape.
    url: Mapped[str | None] = mapped_column(String(512), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    band_id: Mapped[int | None] = mapped_column(ForeignKey("bands.id"), index=True)

    band: Mapped["Band | None"] = relationship(back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship(back_populates="album")
    tags: Mapped[list["Tag"]] = relationship(secondary="album_tags", back_populates="albums")


class Track(Base, TimestampMixin):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    bandcamp_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    url: Mapped[str | None] = mapped_column(String(512), unique=True, index=True)
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


# ── Social graph ───────────────────────────────────────────────────────────────


class Fan(Base, TimestampMixin):
    """A Bandcamp fan (collector). Your own account is flagged `is_me`."""

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


# ── Curation & control ───────────────────────────────────────────────────────


class Follow(Base, TimestampMixin):
    """An artist/label you already follow — excluded/down-weighted in curation."""

    __tablename__ = "follows"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(16))  # TargetType artist|label
    band_id: Mapped[int] = mapped_column(ForeignKey("bands.id"), unique=True, index=True)


class Blacklist(Base, TimestampMixin):
    """A hidden target. Toggle `active` to un-blacklist without losing history."""

    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(primary_key=True)
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


class Recommendation(Base):
    """A computed feed entry with an explainable score."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("item_type", "album_id", "track_id", name="uq_recommendation_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
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
    """Resumable crawl queue: URLs to fetch and their state."""

    __tablename__ = "crawl_frontier"
    __table_args__ = (UniqueConstraint("url", "kind", name="uq_frontier_url_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(512), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # CrawlKind
    status: Mapped[str] = mapped_column(String(16), default=CrawlStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProviderUsage(Base):
    """One row per scraper request — powers the usage dashboard and cost tracking."""

    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
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
    "Fan",
    "FanItem",
    "AlbumSupporter",
    "Follow",
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
