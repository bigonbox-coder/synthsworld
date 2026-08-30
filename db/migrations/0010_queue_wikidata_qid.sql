-- Wikidata id on a queued name.
--
-- Seeding from non-English wikis returns local-script titles (コルグ for Korg),
-- so raw titles cannot be deduplicated against what we already have, and would
-- have queued every major maker a second time. The QID is the language-neutral
-- identity, and it also gives a later pass a free handle for country/inception
-- lookups. Nullable: names seeded by hand or surfaced from relations have none.

ALTER TABLE discovery_queue ADD COLUMN wikidata_qid TEXT;
