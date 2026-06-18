"""Warstwa przechowywania (SQLite) ze sledzeniem 'kiedy pierwszy raz widziane'."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    site          TEXT NOT NULL,
    listing_id    TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    price         INTEGER,
    price_raw     TEXT,
    location      TEXT,
    area          REAL,
    rooms         INTEGER,
    property_type TEXT,
    transaction_t TEXT,
    site_date     TEXT,
    first_seen    TEXT NOT NULL,   -- ISO datetime: kiedy oferta pojawila sie u nas
    last_seen     TEXT NOT NULL,   -- ISO datetime: kiedy ostatnio ja widzielismy
    plot_area     REAL,            -- powierzchnia dzialki (m2) - z podstrony
    floor         TEXT,            -- pietro - z podstrony
    year_built    INTEGER,         -- rok budowy - z podstrony
    description   TEXT,            -- opis - z podstrony
    image_urls    TEXT,            -- JSON: lista adresow zdjec
    photos_dir    TEXT,            -- katalog z pobranymi zdjeciami
    detail_fetched INTEGER DEFAULT 0,  -- czy podstrona zostala pobrana
    PRIMARY KEY (site, listing_id)
);
CREATE INDEX IF NOT EXISTS idx_first_seen ON listings(first_seen);
"""

# kolumny dodane po pierwszej wersji - migracja istniejacych baz
_NOWE_KOLUMNY = {
    "plot_area": "REAL", "floor": "TEXT", "year_built": "INTEGER",
    "description": "TEXT", "image_urls": "TEXT", "photos_dir": "TEXT",
    "detail_fetched": "INTEGER DEFAULT 0",
    "favorite": "INTEGER DEFAULT 0",
}


class Database:
    def __init__(self, path: str | Path = "data/nieruchomosci.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Dodaje brakujace kolumny do istniejacej bazy (bezpieczne ALTER-y)."""
        istniejace = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for kol, typ in _NOWE_KOLUMNY.items():
            if kol not in istniejace:
                self.conn.execute(f"ALTER TABLE listings ADD COLUMN {kol} {typ}")

    def upsert_many(self, listings: Iterable[Listing]) -> dict:
        """Zapisuje liste ofert. Zwraca statystyki {'nowe': N, 'znane': M}."""
        now = datetime.now().isoformat(timespec="seconds")
        nowe, znane = 0, 0
        for ls in listings:
            if self._upsert_one(ls, now):
                nowe += 1
            else:
                znane += 1
        self.conn.commit()
        return {"nowe": nowe, "znane": znane}

    def _upsert_one(self, ls: Listing, now: str) -> bool:
        """Zwraca True, jesli to nowa oferta (wczesniej nieznana)."""
        cur = self.conn.execute(
            "SELECT 1 FROM listings WHERE site = ? AND listing_id = ?",
            (ls.site, ls.listing_id),
        )
        is_new = cur.fetchone() is None

        # first_seen dla nowej oferty: data z portalu (jesli jest), inaczej teraz.
        first_seen = self._initial_first_seen(ls, now) if is_new else None

        if is_new:
            self.conn.execute(
                """INSERT INTO listings
                   (site, listing_id, url, title, price, price_raw, location, area,
                    rooms, property_type, transaction_t, site_date, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ls.site, ls.listing_id, ls.url, ls.title, ls.price, ls.price_raw,
                 ls.location, ls.area, ls.rooms, ls.property_type, ls.transaction,
                 ls.site_date, first_seen, now),
            )
        else:
            # znana oferta: odswiezamy dane i last_seen, NIE ruszamy first_seen
            self.conn.execute(
                """UPDATE listings SET url=?, title=?, price=?, price_raw=?, location=?,
                       area=?, rooms=?, property_type=?, transaction_t=?, site_date=?, last_seen=?
                   WHERE site=? AND listing_id=?""",
                (ls.url, ls.title, ls.price, ls.price_raw, ls.location, ls.area, ls.rooms,
                 ls.property_type, ls.transaction, ls.site_date, now, ls.site, ls.listing_id),
            )
        return is_new

    @staticmethod
    def _initial_first_seen(ls: Listing, now: str) -> str:
        """Reconciliacja: uzyj daty z portalu jesli jest, inaczej biezacy czas.

        Dzieki temu pierwszy raport po starcie od razu pokazuje realne
        'nowe dzis/3/7 dni' dla portali, ktore podaja date (np. Gratka),
        a dla pozostalych liczy od momentu pierwszego scrapowania.
        """
        if ls.site_date:
            return f"{ls.site_date}T00:00:00"
        return now

    def update_detail(self, site: str, listing_id: str, detail: dict) -> None:
        """Zapisuje dane z podstrony (dzialka, pietro, rok, opis, zdjecia)."""
        self.conn.execute(
            """UPDATE listings SET plot_area=?, floor=?, year_built=?, description=?,
                   image_urls=?, photos_dir=?, detail_fetched=1
               WHERE site=? AND listing_id=?""",
            (detail.get("plot_area"), detail.get("floor"), detail.get("year_built"),
             detail.get("description"), json.dumps(detail.get("image_urls") or []),
             detail.get("photos_dir"), site, listing_id),
        )
        self.conn.commit()

    def fetch_all(self, sites: Optional[list[str]] = None,
                  types: Optional[list[str]] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM listings"
        clauses, params = [], []
        if sites:
            clauses.append(f"site IN ({','.join('?' * len(sites))})")
            params += sites
        if types:
            clauses.append(f"property_type IN ({','.join('?' * len(types))})")
            params += types
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY first_seen DESC, price ASC"
        return list(self.conn.execute(sql, params))

    def close(self) -> None:
        self.conn.close()
