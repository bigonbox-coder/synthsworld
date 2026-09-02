#!/usr/bin/env python3
"""Gyarto-nev feloldas EGY helyen: rovid nev, hosszu ceg-alak, nev-tortenet.

MIERT LETT EZ KULON FAJL
========================
2026-09-02 delelott a nev-modell megvaltozott (migracio 0026): a
canonical_name mostantol a KOZISMERT nev (Korg, Moog, ARP), a teljes ceg-alak
pedig a long_name-be kerult (Korg Inc., Moog Music, ARP Instruments).

A leszedokben viszont mindenhol ott ultek a sajat forditotablaik, amik a REGI,
hosszu alakra mutattak:

    harvest_docdir:       "Korg" -> "Korg Inc."
    harvest_vintagesynth: "korg" -> "Korg Inc."
    harvest_synthmania:   "korg" -> "Korg Inc."
    harvest_synfo:        "Arp"  -> "ARP Instruments"

Ezek a nevek a valtozas ota EGYIK gyartoval sem egyeznek, tehat a scriptek
CSENDBEN atlepnek a legfontosabb gyartok fololt. Nem hibaztak, nem is
figyelmeztettek: egyszeruen nem talaltak semmit. A synthfool-nal ez 11
gyarto-mappa volt, koztuk a Korg, Moog, Roland, Buchla es az EML.

Ugyanez a hiba mar egyszer kijott aznap: a reggeli synth-db beemeles 401
hangszert hagyott ki, mert a forras a rovid alakot hasznalta, mi meg akkor a
hosszut tartottuk fonevkent.

A tanulsag nem az, hogy a forditotablak rosszak, hanem hogy a feloldas nem
tartozhat a leszedore. Egy helyen all, mindharom nevalakot nezi, es ha a
modell megint valtozik, EGY fajlt kell javitani.

Hasznalat:
    from maker_lookup import MakerLookup
    makers = MakerLookup(con)
    mid = makers.find("Korg Inc.")     # -> a Korg id-je
    mid = makers.find("korg")          # ugyanaz
"""

import re
import sqlite3


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class MakerLookup:
    """Nev -> manufacturer_id. Sorrend: pontos egyezes, majd normalizalt."""

    def __init__(self, con):
        self.exact = {}
        self.by_norm = {}
        self.canon_by_id = {mid: n for mid, n in
                            con.execute("SELECT id, canonical_name FROM manufacturers")}
        for sql in (
            "SELECT id, canonical_name FROM manufacturers",
            "SELECT id, long_name FROM manufacturers WHERE long_name IS NOT NULL",
            "SELECT manufacturer_id, name FROM manufacturer_name_history",
        ):
            for mid, name in con.execute(sql):
                if not name:
                    continue
                # A canonical_name nyer, ha ket gyarto ugyanarra a nevre hozna:
                # a kesobbi forrasok csak akkor irnak, ha meg ures a kulcs.
                self.exact.setdefault(name, mid)
                self.by_norm.setdefault(norm(name), mid)

    def canonical(self, name):
        """Nev -> a MOSTANI canonical_name. A batch-et iro leszedoknek kell,
        mert azok nevvel hivatkoznak a gyartora, nem id-vel."""
        mid = self.find(name)
        return self.canon_by_id.get(mid) if mid else None

    def find(self, name):
        if not name:
            return None
        return self.exact.get(name) or self.by_norm.get(norm(name))

    def __contains__(self, name):
        return self.find(name) is not None

    def __len__(self):
        return len(self.by_norm)
