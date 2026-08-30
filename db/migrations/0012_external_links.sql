-- External links harvested from source pages, attached to an instrument
-- and/or a manufacturer.
--
-- Vintage Synth Explorer carries a "Websites of Interest" block on nearly
-- every instrument page: the maker's own site, user forums, retrofit and
-- service vendors, museums, sample archives. Those are three things at once:
-- a candidate for manufacturers.official_website, a source list for phase-2
-- research, and a document trail (manuals, ads, firmware) for phase 3.
--
-- Kept deliberately separate from facts_sources. facts_sources is evidence
-- FOR a stored fact; this table is a link we have merely seen and not yet
-- judged. A link only becomes evidence once it is fetched and used.
--
-- Links rot: most of these were written in the 2000s. status/http_status/
-- final_url record a real reachability check, so a dead link can be routed
-- to the Wayback Machine instead of being silently trusted.
BEGIN TRANSACTION;

CREATE TABLE external_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER REFERENCES manufacturers(id),
  instrument_id INTEGER REFERENCES instruments(id),
  url TEXT NOT NULL,
  domain TEXT NOT NULL,
  label TEXT,
  -- open list: manufacturer_official | community | service_mod | archive |
  -- media | retailer | samples | other
  link_type TEXT NOT NULL DEFAULT 'other',
  found_on TEXT NOT NULL,            -- the page we harvested it from
  source_name TEXT NOT NULL,         -- e.g. 'vintagesynth'
  status TEXT NOT NULL DEFAULT 'unchecked'
    CHECK (status IN ('unchecked', 'live', 'redirected', 'dead', 'error')),
  http_status INTEGER,
  final_url TEXT,
  checked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One row per (owner, url). COALESCE because either owner column may be null.
CREATE UNIQUE INDEX external_links_unique
  ON external_links (COALESCE(manufacturer_id, -1), COALESCE(instrument_id, -1), url);
CREATE INDEX external_links_domain ON external_links (domain);
CREATE INDEX external_links_manufacturer ON external_links (manufacturer_id);
CREATE INDEX external_links_instrument ON external_links (instrument_id);

COMMIT;
