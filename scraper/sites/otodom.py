"""Adapter Otodom. Dane czytamy z JSON-a osadzonego w stronie (__NEXT_DATA__),
co jest niezawodne - nie zalezy od wygladu HTML."""
from __future__ import annotations
import json
from typing import Optional

from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import Listing
from ..parsing import parse_site_date, clean_text

_BASE = "https://www.otodom.pl"
_KATEGORIA = {"mieszkanie": "mieszkanie", "dom": "dom"}
# slug lokalizacji w URL: wojewodztwo/powiat/gmina/miasto
_LOKACJA = {
    "tarnow": "malopolskie/tarnow/tarnow/tarnow",
    "krakow": "malopolskie/krakow/krakow/krakow",
    "rzeszow": "podkarpackie/rzeszow/rzeszow/rzeszow",
    "warszawa": "mazowieckie/warszawa/warszawa/warszawa",
    "wroclaw": "dolnoslaskie/wroclaw/wroclaw/wroclaw",
    "poznan": "wielkopolskie/poznan/poznan/poznan",
}
_POKOJE = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
           "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10}


class OtodomScraper(BaseScraper):
    name = "otodom"

    def build_url(self, property_type: str, page: int) -> Optional[str]:
        kat = _KATEGORIA.get(property_type)
        if not kat:
            return None
        lok = _LOKACJA.get(self.config.miasto, f"malopolskie/{self.config.miasto}/{self.config.miasto}/{self.config.miasto}")
        return f"{_BASE}/pl/wyniki/{self.config.transakcja}/{kat}/{lok}?page={page}&limit=72"

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        nd = BeautifulSoup(html, "lxml").find("script", id="__NEXT_DATA__")
        if not nd or not nd.string:
            return []
        try:
            dane = json.loads(nd.string)
            items = dane["props"]["pageProps"]["data"]["searchAds"]["items"]
        except (KeyError, ValueError, TypeError):
            return []

        out: list[Listing] = []
        for it in items:
            lid = it.get("id")
            slug = it.get("slug")
            if not lid or not slug:
                continue
            cena = (it.get("totalPrice") or {}).get("value")
            rooms = it.get("roomsNumber")
            rooms = _POKOJE.get(rooms) if isinstance(rooms, str) else (int(rooms) if rooms else None)
            data = it.get("dateCreated") or it.get("createdAtFirst")
            out.append(Listing(
                site=self.name,
                listing_id=str(lid),
                url=f"{_BASE}/pl/oferta/{slug}",
                title=clean_text(it.get("title")),
                price=int(cena) if cena else None,
                price_raw=f"{int(cena):,} zł".replace(",", " ") if cena else "",
                location=self._lokalizacja(it),
                area=self._float(it.get("areaInSquareMeters")),
                rooms=rooms,
                property_type=property_type,
                transaction=self.config.transakcja,
                site_date=parse_site_date(data) if data else None,
            ))
        return out

    @staticmethod
    def _float(v) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _lokalizacja(self, it: dict) -> str:
        addr = (it.get("location") or {}).get("address") or {}

        def nazwa(klucz):
            v = addr.get(klucz)
            return v.get("name") if isinstance(v, dict) else None

        czesci = [nazwa("district"), nazwa("city"), nazwa("province")]
        loc = ", ".join(c for c in czesci if c)
        return loc or self.config.miasto.capitalize()
