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
    SUPPORTERS = "supporters"


class CrawlStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    ERROR = "error"
