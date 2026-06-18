"""Adapter Gratka. Karty: [data-cy="card"] z bogatymi atrybutami data-cy."""
from __future__ import annotations
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import Listing
from ..parsing import parse_price, parse_area, parse_rooms, parse_site_date, clean_text

_BASE = "https://gratka.pl"
_KATEGORIA = {"mieszkanie": "mieszkania", "dom": "domy"}


class GratkaScraper(BaseScraper):
    name = "gratka"

    def build_url(self, property_type: str, page: int) -> str | None:
        kat = _KATEGORIA.get(property_type)
        if not kat:
            return None
        url = f"{_BASE}/nieruchomosci/{kat}/{self.config.miasto}"
        if page > 1:
            url += f"?page={page}"
        return url

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        for card in soup.select('[data-cy="card"]'):
            a = card.select_one('a[href*="/ob/"]') or card.select_one("a[href]")
            if not a:
                continue
            href = a.get("href", "")
            m = re.search(r"/ob/(\d+)", href)
            listing_id = m.group(1) if m else href.rstrip("/").split("/")[-1]
            if not listing_id:
                continue
            url = urljoin(_BASE, href.split("?")[0])

            price_raw = self._txt(card, '[data-cy="propertyCardPrice"]')
            location = self._txt(card, '[data-cy="propertyCardLocation"]')
            rooms_txt = self._txt(card, '[data-cy="cardPropertyInfoRooms"]')
            info = self._txt(card, '[data-cy="propertyCardInfo"]')
            date_txt = self._txt(card, '[data-cy="descriptionAddedAtDate"]')

            title = a.get("title") or clean_text(a.get_text(" ", strip=True))
            if not title:
                title = f"{property_type.capitalize()} {location}".strip()

            out.append(Listing(
                site=self.name,
                listing_id=str(listing_id),
                url=url,
                title=clean_text(title),
                price=parse_price(price_raw),
                price_raw=price_raw,
                location=location,
                area=parse_area(info) or parse_area(title),
                rooms=parse_rooms(rooms_txt) or parse_rooms(info),
                property_type=property_type,
                transaction=self.config.transakcja,
                site_date=parse_site_date(date_txt),
            ))
        return out

    @staticmethod
    def _txt(card, selector: str) -> str:
        el = card.select_one(selector)
        return clean_text(el.get_text(" ", strip=True)) if el else ""
