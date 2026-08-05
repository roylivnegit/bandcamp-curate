"""Small URL helpers shared by the crawl and curation sides.

Bandcamp gives every artist and label its own subdomain, so the host of a release
URL identifies the *storefront* it sits on — which is not always the band the
release is stored under (a label's releases carry the artist's band_id). Both the
crawl filter and the curation exclusions need that host, hence one helper.
"""

import re

_HOST_RE = re.compile(r"https?://([^/]+)")


def url_host(url: str | None) -> str | None:
    """The host of a Bandcamp URL, e.g. https://atomesmusic.bandcamp.com/album/x → host."""
    if not url:
        return None
    m = _HOST_RE.match(url)
    return m.group(1).lower() if m else None
