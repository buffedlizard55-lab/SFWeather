# Test fixtures

These files exist so the parsing code can be tested **offline** against the exact
shape a publisher returns, without the test suite depending on network access
(the sandbox and the `Tests` workflow both run with no route to NOAA hosts).

Every fixture is derived from a real response retrieved from an official
endpoint. Nothing here is invented, and the field values are verbatim.

| Fixture | Source endpoint | Retrieved | What was trimmed |
| --- | --- | --- | --- |
| `census_geocoder_94122.json` | `https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=-122.483894&y=37.760459&benchmark=Public_AR_Current&vintage=Current_Current&format=json` | 18 Sep 2026 (review pass) | Object IDs (`OID`, `OBJECTID`), centroids/interior points and land/water areas were dropped from most geographies to keep the file small. The `2020 Census Blocks` record is kept in full. Geography *names*, *GEOIDs* and the input coordinate block are verbatim. |

Rules for adding a fixture:

1. Copy the real response; do not write one from memory.
2. Record the exact URL, the retrieval date and what was trimmed, in the table
   above.
3. A fixture must be able to make the code under test **fail** when it is
   mutated — a fixture that only exercises the happy path proves nothing. The
   negative cases live in `tests/test_parsers.py` next to the positive one.
