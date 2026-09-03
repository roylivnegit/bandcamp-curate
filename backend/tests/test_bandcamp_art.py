from app.bandcamp.art import art_url


def test_art_url_none_passthrough() -> None:
    assert art_url(None) is None


def test_art_url_builds_bandcamp_cdn_url() -> None:
    assert art_url(435129856) == "https://f4.bcbits.com/img/a435129856_10.jpg"


def test_art_url_zero_is_not_treated_as_missing() -> None:
    # `art_id` is an opaque id, not a truthiness flag — a hypothetical 0 must
    # still build a URL, not be silently dropped like `None`.
    assert art_url(0) == "https://f4.bcbits.com/img/a0_10.jpg"
