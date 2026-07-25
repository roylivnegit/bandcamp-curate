"""Shared string-valued enums.

Stored as plain strings in Postgres (not native enum types) to keep migrations
simple — adding a new value never requires a schema migration.
"""

from enum import StrEnum


class BandKind(StrEnum):
    ARTIST = "artist"
    LABEL = "label"
    UNKNOWN = "unknown"


class ItemType(StrEnum):
    ALBUM = "album"
    TRACK = "track"


class TargetType(StrEnum):
    ARTIST = "artist"
    LABEL = "label"
    ALBUM = "album"
    TRACK = "track"


class CrawlKind(StrEnum):
    FAN_COLLECTION = "fan_collection"
    ALBUM = "album"
    TRACK = "track"
    SUPPORTERS = "supporters"


class CrawlStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"


class ScanKind(StrEnum):
    COLLECTION = "collection"  # seeds = your own collection (the original run)
    CUSTOM = "custom"          # seeds = user-supplied album/track URLs


class ScanStatus(StrEnum):
    DRAFT = "draft"        # created, not yet queued
    QUEUED = "queued"      # waiting for the Mac poller to pick it up
    RUNNING = "running"    # a crawl is executing on the PC
    DONE = "done"          # crawl + curation finished
    ERROR = "error"        # crawl failed (see scans.error)
