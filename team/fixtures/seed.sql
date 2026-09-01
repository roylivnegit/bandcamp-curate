-- team/fixtures/seed.sql — synthetic corpus for the sandbox database (E0-2).
--
-- Never built from Neon; band/album/track/tag flavor borrowed from the real scraped
-- fixtures at backend/tests/fixtures/*.html (Cerebro Spinal / Panchito, psytrance/electronic
-- tags) per the backlog's instruction. Loaded into a fresh, freshly-migrated database by
-- team/tools/sandbox-db.sh, so every id below is safe to hardcode — there are no prior rows.
--
-- Designed so team/tools/curate_seed.py (run right after this file loads) produces exactly
-- two recommendations for the "e2e-tester" user: album 2 (co-owned by both neighbours,
-- tagged psytrance) and album 3 (co-owned by one neighbour, tagged downtempo). Every
-- exclusion path curation is supposed to honor gets its own case that would otherwise have
-- been a candidate too:
--   album 4 — wishlisted by me            -> excluded by ownership/wishlist
--   album 5 — band I follow                -> excluded by follows
--   album 6 — band I've blacklisted         -> excluded by blacklist
--   album 7 — album I've liked              -> excluded by likes

-- ── Bands ──────────────────────────────────────────────────────────────────────────────
INSERT INTO bands (id, bandcamp_id, url, name, kind) VALUES
  (1, 3817572659, 'https://cerebrospinal.bandcamp.com', 'Cerebro Spinal', 'artist'),
  (2, 1000000002, 'https://panchitolabel.bandcamp.com', 'Panchito Label', 'label'),
  (3, 1000000003, 'https://wishlistband.bandcamp.com', 'Wishlist Band', 'artist'),
  (4, 1000000004, 'https://followedlabel.bandcamp.com', 'Followed Label', 'label'),
  (5, 1000000005, 'https://blockedartist.bandcamp.com', 'Blocked Artist', 'artist'),
  (6, 1000000006, 'https://likedartist.bandcamp.com', 'Liked Artist', 'artist');

-- ── Albums ─────────────────────────────────────────────────────────────────────────────
INSERT INTO albums (id, bandcamp_id, url, title, band_id) VALUES
  (1, 4255072328, 'https://cerebrospinal.bandcamp.com/album/panchito', 'Panchito', 1),
  (2, 2000000002, 'https://cerebrospinal.bandcamp.com/album/night-signals', 'Night Signals', 1),
  (3, 2000000003, 'https://panchitolabel.bandcamp.com/album/desert-bloom', 'Desert Bloom', 2),
  (4, 2000000004, 'https://wishlistband.bandcamp.com/album/someday', 'Someday', 3),
  (5, 2000000005, 'https://followedlabel.bandcamp.com/album/dispatch', 'Dispatch', 4),
  (6, 2000000006, 'https://blockedartist.bandcamp.com/album/noise', 'Noise', 5),
  (7, 2000000007, 'https://likedartist.bandcamp.com/album/echoes', 'Echoes', 6);

-- ── Tags ───────────────────────────────────────────────────────────────────────────────
INSERT INTO tags (id, name) VALUES
  (1, 'psytrance'),
  (2, 'downtempo');

-- Album 1 (mine, owned) is tagged psytrance too — the feed only shows a genre chip for a
-- tag that's in *my* profile (tags on albums I own), so album 2's shared tag becomes a
-- "matched tag" the E2E test can click. Confirmed by reading engine.py's _my_tag_profile()
-- and FeedCard.tsx's `rec.reasons.matched_tags` — a candidate's own tags alone aren't enough.
INSERT INTO album_tags (album_id, tag_id) VALUES
  (1, 1),
  (2, 1),
  (3, 2);

-- ── Fans ───────────────────────────────────────────────────────────────────────────────
-- fan 1 is "me" (the e2e-tester's own fan). fans 2-3 are taste-neighbours.
INSERT INTO fans (id, bandcamp_fan_id, username, url, name, is_me) VALUES
  (1, 9000001, 'e2e_me', 'https://bandcamp.com/e2e_me', 'E2E Tester', true),
  (2, 9000002, 'neighbour_alpha', 'https://bandcamp.com/neighbour_alpha', 'Neighbour Alpha', false),
  (3, 9000003, 'neighbour_beta', 'https://bandcamp.com/neighbour_beta', 'Neighbour Beta', false);

-- ── The app user (auth) ────────────────────────────────────────────────────────────────
-- password is "e2e-sandbox-pw" — bcrypt hash generated once with backend/.venv's bcrypt,
-- not a real secret (this database is created and destroyed inside a single cycle/run).
INSERT INTO users (id, username, password_hash, fan_id, bandcamp_fan_url) VALUES
  (1, 'e2e-tester', '$2b$12$xg/sULTiS0Z009DFx.nFW..BEHT.PqJm3oDrwEMSGg2Vz0ypLJnse', 1,
   'https://bandcamp.com/e2e_me');

-- ── Collection items ───────────────────────────────────────────────────────────────────
-- me: own album 1 (this scan's seed), wishlist album 4.
INSERT INTO fan_items (fan_id, item_type, album_id, is_wishlist) VALUES
  (1, 'album', 1, false),
  (1, 'album', 4, true);

-- neighbours: own the candidates (2, 3) plus the three that must each get excluded for a
-- different reason (5 = followed band, 6 = blacklisted band, 7 = liked album).
INSERT INTO fan_items (fan_id, item_type, album_id, is_wishlist) VALUES
  (2, 'album', 2, false),
  (3, 'album', 2, false),
  (3, 'album', 3, false),
  (2, 'album', 5, false),
  (3, 'album', 6, false),
  (2, 'album', 7, false);

-- ── Who supports my seed album (this is what makes fans 2 and 3 "neighbours") ──────────
INSERT INTO album_supporters (album_id, fan_id) VALUES
  (1, 2),
  (1, 3);

-- ── Exclusions, each with a real case ──────────────────────────────────────────────────
-- I follow "Followed Label" (band 4) -> album 5 must not be recommended despite co-ownership.
INSERT INTO follows (fan_id, target_type, band_id) VALUES
  (1, 'label', 4);

-- I've blacklisted "Blocked Artist" (band 5) -> album 6 must not be recommended.
INSERT INTO blacklist (user_id, target_type, band_id, active, reason) VALUES
  (1, 'artist', 5, true, 'not my taste');

-- I've liked "Echoes" (album 7) directly -> it and its band drop out of the feed.
INSERT INTO likes (user_id, item_type, album_id) VALUES
  (1, 'album', 7);

-- ── Bump every sequence past the explicit ids above ────────────────────────────────────
-- Every id above was hardcoded, which never advances the table's own identity sequence —
-- the next *real* insert (e.g. a fresh E2E signup) would otherwise ask Postgres for id 1
-- again and collide with the seed row, raising an IntegrityError the API maps to the
-- wrong-but-plausible-looking "username is already taken" (confirmed happening: it's
-- actually create_collection_scan's own INSERT racing the seeded users.id=1).
SELECT setval(pg_get_serial_sequence('bands', 'id'), (SELECT MAX(id) FROM bands));
SELECT setval(pg_get_serial_sequence('albums', 'id'), (SELECT MAX(id) FROM albums));
SELECT setval(pg_get_serial_sequence('tags', 'id'), (SELECT MAX(id) FROM tags));
SELECT setval(pg_get_serial_sequence('fans', 'id'), (SELECT MAX(id) FROM fans));
SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT MAX(id) FROM users));
