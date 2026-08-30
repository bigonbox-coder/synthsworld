-- external_links.status gains 'blocked'.
--
-- The first full reachability run put 292 links in 'error' on an HTTP 403.
-- That is almost never a broken link: it is Cloudflare, a WAF or a parking
-- page refusing a non-browser client. Filing those next to real failures
-- would make a live source look dead and cost us the page.
--
-- 'blocked' means: the host answered, and refused us. Worth a manual look or
-- a fetch through quarantine-reader, unlike 'dead'.
BEGIN TRANSACTION;

CREATE TABLE external_links_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer_id INTEGER REFERENCES manufacturers(id),
  instrument_id INTEGER REFERENCES instruments(id),
  url TEXT NOT NULL,
  domain TEXT NOT NULL,
  label TEXT,
  link_type TEXT NOT NULL DEFAULT 'other',
  found_on TEXT NOT NULL,
  source_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unchecked'
    CHECK (status IN ('unchecked', 'live', 'redirected', 'blocked', 'dead', 'error')),
  http_status INTEGER,
  final_url TEXT,
  checked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO external_links_new SELECT * FROM external_links;
DROP TABLE external_links;
ALTER TABLE external_links_new RENAME TO external_links;

CREATE UNIQUE INDEX external_links_unique
  ON external_links (COALESCE(manufacturer_id, -1), COALESCE(instrument_id, -1), url);
CREATE INDEX external_links_domain ON external_links (domain);
CREATE INDEX external_links_manufacturer ON external_links (manufacturer_id);
CREATE INDEX external_links_instrument ON external_links (instrument_id);

COMMIT;
