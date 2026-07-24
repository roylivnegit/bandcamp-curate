from pathlib import Path

from app.bandcamp.parse import (
    band_url_from_hints,
    parse_collection_items_api,
    parse_fan_page,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fan_page.html"


def test_parse_fan_page_from_fixture() -> None:
    fc = parse_fan_page(FIXTURE.read_text())

    assert fc.fan.fan_id == 9985893
    assert fc.fan.username == "guron"
    assert fc.fan.url == "https://bandcamp.com/guron"

    # Fixture was built with one track + one album item.
    types = sorted(i.item_type for i in fc.items)
    assert types == ["album", "track"]
    assert len(fc.follows) == 2

    # Pagination signal present.
    assert fc.last_token
    assert fc.more_available is True


def test_parsed_item_fields() -> None:
    fc = parse_fan_page(FIXTURE.read_text())
    by_type = {i.item_type: i for i in fc.items}

    track = by_type["track"]
    assert track.item_id and track.band.bandcamp_id and track.band.name
    assert track.url and track.url.startswith("http")

    album = by_type["album"]
    assert album.item_id and album.band.bandcamp_id


def test_band_url_from_hints_prefers_verified_custom_domain() -> None:
    assert band_url_from_hints({"subdomain": "foo"}) == "https://foo.bandcamp.com"
    assert (
        band_url_from_hints(
            {"subdomain": "foo", "custom_domain": "x.com", "custom_domain_verified": True}
        )
        == "https://x.com"
    )
    assert band_url_from_hints(None) is None


def test_parse_collection_items_api_shape() -> None:
    payload = {
        "items": [
            {
                "item_id": 111,
                "item_type": "album",
                "band_id": 222,
                "band_name": "Some Label",
                "item_title": "An Album",
                "item_url": "https://x.bandcamp.com/album/an-album",
                "url_hints": {"subdomain": "x"},
            }
        ],
        "last_token": "tok",
        "more_available": True,
    }
    items, last_token, more = parse_collection_items_api(payload)
    assert len(items) == 1 and items[0].item_type == "album"
    assert items[0].band.url == "https://x.bandcamp.com"
    assert last_token == "tok" and more is True
