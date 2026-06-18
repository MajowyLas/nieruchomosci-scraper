"""Adapter nieruchomosci-online.pl. Karty: div.tile-inner (render serwerowy).

Portal nie pokazuje daty dodania na liscie wynikow, wiec datowanie opieramy
na 'first_seen' z bazy. Stronicowanie realizujemy przez podazanie za linkiem
'nastepna strona' (format URL szukaj.html jest pozycyjny i nieoczywisty).
"""
from __future__ import annotations
import re
from typing import Iterator, Optional
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import Listing
from ..parsing import parse_price, parse_area, parse_rooms, clean_text

_BASE = "https://www.nieruchomosci-online.pl"
# kod sekcji w szukaj.html: 3 = sprzedaz mieszkan/domow
_OBIEKT = {"mieszkanie": "mieszkanie", "dom": "dom"}
# slug miasta -> nazwa z polskimi znakami uzywana w wyszukiwarce
_MIASTA = {"tarnow": "Tarnów", "krakow": "Kraków", "rzeszow": "Rzeszów",
           "warszawa": "Warszawa", "wroclaw": "Wrocław", "poznan": "Poznań",
           "lodz": "Łódź", "gdansk": "Gdańsk"}


class NieruchomosciOnlineScraper(BaseScraper):
    name = "nieruchomosci-online"

    def build_url(self, property_type: str, page: int) -> Optional[str]:
        obj = _OBIEKT.get(property_type)
        if not obj:
            return None
        miasto = _MIASTA.get(self.config.miasto, self.config.miasto.capitalize())
        # format pozycyjny: ?3,<obiekt>,sprzedaz,,<Miasto>
        return f"{_BASE}/szukaj.html?3,{obj},{self.config.transakcja},,{quote(miasto)}"

    def iter_pages(self, property_type: str) -> Iterator[str]:
        url = self.build_url(property_type, 1)
        for _ in range(self.config.max_stron):
            if not url:
                break
            resp = self.client.get(url)
            if resp is None or resp.status_code != 200:
                break
            yield resp.text
            url = self._next_url(resp.text, resp.url)

    def _next_url(self, html: str, current_url: str) -> Optional[str]:
        soup = BeautifulSoup(html, "lxml")
        nxt = soup.select_one('a[rel="next"]')
        if not nxt:
            for a in soup.select("a[href]"):
                cls = " ".join(a.get("class", []))
                txt = a.get_text(" ", strip=True).lower()
                if "next" in cls.lower() or "nast" in txt or txt == "»":
                    nxt = a
                    break
        if nxt and nxt.get("href"):
            return urljoin(current_url, nxt["href"])
        return None

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        for tile in soup.select("div.tile-inner"):
            link = tile.select_one("h2.name a[href], .name a[href]")
            if not link:
                continue
            href = link.get("href", "")
            m = re.search(r"/(\d+)\.html", href)
            if not m:
                continue
            listing_id = m.group(1)
            url = urljoin(_BASE, href.split("?")[0])
            title = clean_text(link.get_text(" ", strip=True))

            province = tile.select_one("p.province, .province")
            location = clean_text(province.get_text(" ", strip=True)) if province else ""

            price_raw, area = "", None
            pd = tile.select_one("p.primary-display, .primary-display")
            if pd:
                price_span = pd.find("span")
                if price_span:
                    price_raw = clean_text(price_span.get_text(" ", strip=True))
                area_span = pd.select_one("span.area, .area")
                if area_span:
                    area = parse_area(area_span.get_text(" ", strip=True))

            out.append(Listing(
                site=self.name,
                listing_id=listing_id,
                url=url,
                title=title,
                price=parse_price(price_raw),
                price_raw=price_raw,
                location=location,
                area=area or parse_area(title),
                rooms=parse_rooms(title),
                property_type=property_type,
                transaction=self.config.transakcja,
                site_date=None,  # portal nie podaje daty na liscie
            ))
        return out
