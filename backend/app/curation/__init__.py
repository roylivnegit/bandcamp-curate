"""Curation (M4): turn the crawled graph into a ranked feed of music you don't own.

`engine` scores candidate albums/tracks — things owned by your taste-neighbours (the
fans who bought what you bought) — after excluding everything already in your world
(owned, wishlisted, or by an artist/label you follow, or blacklisted), and writes
explainable rows into `recommendations`.
"""
