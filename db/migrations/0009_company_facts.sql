-- Founding/ending years, city and founders as first-class columns.
--
-- Until now these facts existed only inside the prose history, which meant the
-- site could not sort by era, filter by city, or search for a founder by name --
-- exactly the queries a manufacturer museum is built around. Additive columns
-- only, per the project rule; nothing existing is rewritten.
--
-- Convention for the year columns: they hold the CANONICAL, legal-entity dates.
-- Where operational and legal dates differ (the Siel case: production stopped
-- 1986, deregistered 1987), the column takes the legal one and the prose keeps
-- the distinction. ended_year applies to both 'defunct' and 'acquired' records:
-- it is the year the company stopped existing as an independent entity.

ALTER TABLE manufacturers ADD COLUMN founded_year INTEGER;
ALTER TABLE manufacturers ADD COLUMN ended_year INTEGER;
ALTER TABLE manufacturers ADD COLUMN city TEXT;
ALTER TABLE manufacturers ADD COLUMN founders TEXT;
