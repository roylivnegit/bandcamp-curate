from pathlib import Path

from app.bandcamp.parse import (
    band_url_from_album_url,
    band_url_from_hints,
    parse_album_page,
    parse_album_supporters,
    parse_collection_items_api,
    parse_fan_page,
    parse_thumbs_api,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fan_page.html"
ALBUM_FIXTURE = Path(__file__).parent / "fixtures" / "album_page.html"


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


def test_band_url_from_album_url() -> None:
    assert (
        band_url_from_album_url("https://cerebro-spinal.bandcamp.com/album/panchito")
        == "https://cerebro-spinal.bandcamp.com"
    )
    assert band_url_from_album_url(None) is None


def test_parse_album_page_from_fixture() -> None:
    album = parse_album_page(ALBUM_FIXTURE.read_text())

    assert album.album_id == 4255072328
    assert album.title == "Panchito"
    assert album.url == "https://cerebro-spinal.bandcamp.com/album/panchito"
    assert album.art_id == 435129856

    assert album.band.bandcamp_id == 3817572659
    assert album.band.name == "Cerebro Spinal"
    assert album.band.url == "https://cerebro-spinal.bandcamp.com"

    # Tags normalized to lowercase, order preserved.
    assert album.tags == ["electronic", "psytrance", "trance", "israel"]

    assert len(album.tracks) == 1
    track = album.tracks[0]
    assert track.track_id == 4032544361
    assert track.title == "Panchito"
    assert track.track_num == 1
    assert track.duration == 486.761
    assert track.url == "https://cerebro-spinal.bandcamp.com/track/panchito"


def test_parse_album_supporters_from_collectors_blob() -> None:
    sup = parse_album_supporters(ALBUM_FIXTURE.read_text())

    assert sup.album_id == 4255072328
    assert [s.username for s in sup.supporters] == ["guron", "moth_lord", "deepcrate"]
    # Structured blob carries fan_id.
    assert sup.supporters[0].fan_id == 9985893
    assert sup.supporters[0].url == "https://bandcamp.com/guron"
    # Pagination signal present.
    assert sup.more_available is True
    assert sup.last_token


def test_parse_album_supporters_dom_fallback() -> None:
    # No #collectors-data blob → fall back to fan-pic DOM anchors (username only).
    dom = """
    <div class="collectors">
      <a class="fan pic" href="https://bandcamp.com/alice?from=fanthanks"></a>
      <a class="fan pic" href="https://bandcamp.com/bob?from=fanthanks"></a>
      <a class="fan pic" href="https://bandcamp.com/alice?from=fanthanks"></a>
    </div>
    """
    sup = parse_album_supporters(dom)
    assert [s.username for s in sup.supporters] == ["alice", "bob"]  # de-duped
    assert sup.supporters[0].fan_id is None
    assert sup.more_available is False


def test_parse_album_supporters_exposes_tralbum_type() -> None:
    # The album fixture is a full album → tralbum_type "a" for the thumbs XHR.
    sup = parse_album_supporters(ALBUM_FIXTURE.read_text())
    assert sup.tralbum_type == "a"
    assert sup.album_id == 4255072328


def test_parse_thumbs_api() -> None:
    payload = {
        "thumbs": [
            {"fan_id": 1, "username": "alice", "name": "Alice", "token": "t1"},
            {"fan_id": 2, "username": "bob", "name": "Bob", "token": "t2"},
            {"fan_id": 3, "name": "no username"},  # skipped — no username
        ],
        "more_thumbs_available": True,
    }
    supporters, last_token, more = parse_thumbs_api(payload)
    assert [s.username for s in supporters] == ["alice", "bob"]
    assert supporters[0].fan_id == 1 and supporters[0].url == "https://bandcamp.com/alice"
    assert last_token == "t2"  # final thumb's token
    assert more is True


def test_parse_thumbs_api_xhr_results_shape() -> None:
    # The paginated thumbs XHR uses results/more_available (verified live), and each
    # result ships a ready `url` — distinct from the embedded blob's thumbs shape.
    payload = {
        "results": [
            {"fan_id": 9985893, "username": "guron", "name": "guron",
             "url": "https://bandcamp.com/guron", "token": "1:1764260121:9985893:0:0:0"},
        ],
        "more_available": True,
    }
    supporters, last_token, more = parse_thumbs_api(payload)
    assert [s.username for s in supporters] == ["guron"]
    assert supporters[0].url == "https://bandcamp.com/guron"
    assert last_token == "1:1764260121:9985893:0:0:0"
    assert more is True


def test_parse_thumbs_api_empty() -> None:
    supporters, last_token, more = parse_thumbs_api({})
    assert supporters == [] and last_token is None and more is False
