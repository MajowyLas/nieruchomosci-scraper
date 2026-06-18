"""Geokodowanie (tekst -> wspolrzedne) i liczenie odleglosci.

Uzywa OpenStreetMap Nominatim (darmowe, bez klucza). Wyniki sa buforowane
w lokalnej bazie SQLite, bo polityka Nominatim dopuszcza ~1 zapytanie/s.
"""
from __future__ import annotations
import math
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Polityka Nominatim wymaga identyfikujacego User-Agent z kontaktem.
_UA = "nieruchomosci-scraper/0.1 (kontakt: anna.maywald@cart.com)"


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Odleglosc w km miedzy dwoma punktami (po powierzchni Ziemi)."""
    R = 6371.0  # promien Ziemi w km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


class Geocoder:
    """Zamienia tekstowa lokalizacje na (lat, lon). Buforuje wyniki (takze
    porazki), aby nie pytac wielokrotnie o to samo."""

    def __init__(self, cache_path: str | Path = "data/geocache.db", delay: float = 1.1):
        self.delay = delay
        self._last = 0.0
        self.conn = sqlite3.connect(cache_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS geocache (query TEXT PRIMARY KEY, lat REAL, lon REAL)"
        )
        self.conn.commit()

    def geocode(self, location: str) -> Optional[tuple[float, float]]:
        location = (location or "").strip()
        if not location:
            return None
        # probujemy pelnej lokalizacji, potem samej koncowki (miasto)
        for kandydat in self._kandydaci(location):
            coords = self._geocode_jeden(kandydat)
            if coords:
                return coords
        return None

    @staticmethod
    def _kandydaci(location: str) -> list[str]:
        kand = [location]
        if "," in location:
            kand.append(location.split(",")[-1].strip())  # np. "..., Tarnow" -> "Tarnow"
        # usun duplikaty zachowujac kolejnosc
        return list(dict.fromkeys(k for k in kand if k))

    def _geocode_jeden(self, query: str) -> Optional[tuple[float, float]]:
        row = self.conn.execute(
            "SELECT lat, lon FROM geocache WHERE query = ?", (query,)
        ).fetchone()
        if row is not None:
            return (row[0], row[1]) if row[0] is not None else None

        coords = self._zapytaj_api(query)
        self.conn.execute(
            "INSERT OR REPLACE INTO geocache (query, lat, lon) VALUES (?, ?, ?)",
            (query, coords[0] if coords else None, coords[1] if coords else None),
        )
        self.conn.commit()
        return coords

    def _zapytaj_api(self, query: str) -> Optional[tuple[float, float]]:
        self._respect_delay()
        try:
            r = requests.get(
                _NOMINATIM,
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "pl"},
                headers={"User-Agent": _UA},
                timeout=15,
            )
            self._last = time.monotonic()
            if r.status_code == 200:
                dane = r.json()
                if dane:
                    return float(dane[0]["lat"]), float(dane[0]["lon"])
        except (requests.RequestException, ValueError, KeyError):
            return None
        return None

    def _respect_delay(self) -> None:
        dt = time.monotonic() - self._last
        if self._last and dt < self.delay:
            time.sleep(self.delay - dt)

    def close(self) -> None:
        self.conn.close()


def policz_odleglosci(rows, ref_coords: tuple[float, float], geocoder: Geocoder,
                      log=lambda m: None, progress=None, stop=None) -> dict[tuple[str, str], float]:
    """Zwraca {(site, listing_id): km} - odleglosc oferty od punktu odniesienia.

    Geokoduje tylko UNIKALNE lokalizacje (wiele ofert dzieli te sama dzielnice),
    co minimalizuje liczbe zapytan do API. `progress(done, total)` raportuje postep.
    """
    unikalne: dict[str, Optional[tuple[float, float]]] = {}
    for r in rows:
        loc = (r["location"] or "").strip()
        if loc:
            unikalne.setdefault(loc, None)

    razem = len(unikalne)
    log(f"Geokodowanie {razem} unikalnych lokalizacji...")
    for i, loc in enumerate(unikalne, 1):
        if stop and stop():
            break
        unikalne[loc] = geocoder.geocode(loc)
        if progress:
            progress(i, razem)
        if i % 5 == 0 or i == razem:
            log(f"  ...{i}/{razem}")

    odleglosci: dict[tuple[str, str], float] = {}
    for r in rows:
        coords = unikalne.get((r["location"] or "").strip())
        if coords:
            km = haversine(ref_coords[0], ref_coords[1], coords[0], coords[1])
            odleglosci[(r["site"], r["listing_id"])] = km
    return odleglosci
