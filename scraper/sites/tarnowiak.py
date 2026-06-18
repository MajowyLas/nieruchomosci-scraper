"""Adapter Tarnowiak.pl - lokalny portal ogloszeniowy (region tarnowski).

HTML w starym stylu: karty to <a class="box_content_link">. Na stronie
kategorii pojawiaja sie tez promowane ogloszenia z INNYCH kategorii
(np. auto-skup) - odfiltrowujemy je po slowach kluczowych nieruchomosci.
Karta zawiera date dodania, ktora wykorzystujemy jako site_date.
"""
from __future__ import annotations
import re

from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import Listing
from ..parsing import parse_price, parse_area, parse_rooms, parse_site_date, clean_text

_BASE = "https://tarnowiak.pl"
_KATEGORIA = {"mieszkanie": "mieszkania", "dom": "domy"}
# slowa kluczowe potwierdzajace, ze oferta jest z danej kategorii
_KEYWORDS = {
    "mieszkanie": ("mieszkan", "kawalerka", "apartament", "pokoj", "pokój", "m2", "m²"),
    "dom": ("dom", "domu", "dzialk", "działk", "posiadl", "m2", "m²"),
}


class TarnowiakScraper(BaseScraper):
    name = "tarnowiak"

    def build_url(self, property_type: str, page: int) -> str | None:
        kat = _KATEGORIA.get(property_type)
        if not kat:
            return None
        baza = f"{_BASE}/ogloszenia/nieruchomosci/{kat}/sprzedam"
        # paginacja Tarnowiaka ma format ".../sprzedam:strona-2/"
        return f"{baza}/" if page == 1 else f"{baza}:strona-{page}/"

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        keywords = _KEYWORDS.get(property_type, ())
        out: list[Listing] = []
        for a in soup.select("a.box_content_link"):
            href = a.get("href", "")
            m = re.search(r"/ogloszenie/(\d+)", href)
            if not m:
                continue
            listing_id = m.group(1)

            desc = a.select_one(".box_content_desc")
            blob = clean_text(desc.get_text(" ", strip=True)).lower() if desc else ""
            # odfiltruj promowane ogloszenia z innych kategorii
            if keywords and not any(k in blob for k in keywords):
                continue

            title_el = desc.select_one("strong") if desc else None
            title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
            title = re.sub(r"^\d+\.\s*", "", title)  # usun numeracje "1. "

            price_el = a.select_one(".box_content_price strong, .box_content_price")
            price_raw = clean_text(price_el.get_text(" ", strip=True)) if price_el else ""

            date_el = a.select_one(".box_content_date")
            date_txt = clean_text(date_el.get_text(" ", strip=True)) if date_el else ""

            location = "Tarnów" if "tarn" in blob else self.config.miasto.capitalize()

            out.append(Listing(
                site=self.name,
                listing_id=listing_id,
                url=_BASE + href if href.startswith("/") else href,
                title=title or "(bez tytulu)",
                price=parse_price(price_raw),
                price_raw=price_raw,
                location=location,
                area=parse_area(title) or parse_area(blob),
                rooms=parse_rooms(title) or parse_rooms(blob),
                property_type=property_type,
                transaction=self.config.transakcja,
                site_date=parse_site_date(date_txt),
            ))
        return out
