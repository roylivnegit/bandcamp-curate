"""Build a Bandcamp art image URL from the opaque `art_id` stored on Album/Track.

`art_id` alone isn't renderable — Bandcamp serves it off its asset CDN keyed by
id plus a size code. `_10` is a square thumbnail (~150px); see `Album.art_id`'s
docstring in `app/db/models.py` for why the id is stored instead of a URL.
"""


def art_url(art_id: int | None) -> str | None:
    if art_id is None:
        return None
    return f"https://f4.bcbits.com/img/a{art_id}_10.jpg"
