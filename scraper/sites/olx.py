"""Adapter OLX. Karty ofert: [data-cy="l-card"] z renderem serwerowym."""
from __future__ import annotations
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup

from .base import BaseScraper
from ..models import Listing
from ..parsing import parse_price, parse_area, parse_rooms, parse_site_date, clean_text

_BASE = "https://www.olx.pl"
_KATEGORIA = {"mieszkanie": "mieszkania", "dom": "domy"}


class OlxScraper(BaseScraper):
    name = "olx"

    def build_url(self, property_type: str, page: int) -> str | None:
        kat = _KATEGORIA.get(property_type)
        if not kat:
            return None
        path = f"/nieruchomosci/{kat}/{self.config.transakcja}/{self.config.miasto}/"
        params: dict[str, str] = {}
        if page > 1:
            params["page"] = str(page)
        if self.config.cena_min is not None:
            params["search[filter_float_price:from]"] = str(self.config.cena_min)
        if self.config.cena_max is not None:
            params["search[filter_float_price:to]"] = str(self.config.cena_max)
        url = _BASE + path
        if params:
            url += "?" + urlencode(params)
        return url

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Listing] = []
        for card in soup.select('[data-cy="l-card"]'):
            listing_id = card.get("id")
            a = card.select_one("a[href]")
            if not listing_id or not a:
                continue
            href = a.get("href", "")
            if "/d/oferta/" not in href:
                continue  # pomijamy bloki nie-ofertowe
            url = urljoin(_BASE, href.split("?")[0])

            title_el = card.select_one("h4, h6, h5")
            title = clean_text(title_el.get_text(" ", strip=True)) if title_el else clean_text(a.get_text(" "))

            price_el = card.select_one('[data-testid="ad-price"]')
            price_raw = clean_text(price_el.get_text(" ", strip=True)) if price_el else ""

            # "Tarnow - Odswiezono dzisiaj o 08:04" -> lokalizacja + tekst daty
            loc_date = card.select_one('[data-testid="location-date"]')
            location, date_txt = "", ""
            if loc_date:
                parts = clean_text(loc_date.get_text(" ", strip=True)).split(" - ", 1)
                location = parts[0].strip()
                date_txt = parts[1].strip() if len(parts) > 1 else ""

            # OLX czesto nie ma osobnego pola powierzchni - probujemy z tytulu,
            # a w razie braku przeszukujemy cala tresc karty.
            card_text = clean_text(card.get_text(" ", strip=True))

            out.append(Listing(
                site=self.name,
                listing_id=str(listing_id),
                url=url,
                title=title,
                price=parse_price(price_raw),
                price_raw=price_raw,
                location=location,
                area=parse_area(title) or parse_area(card_text),
                rooms=parse_rooms(title) or parse_rooms(card_text),
                property_type=property_type,
                transaction=self.config.transakcja,
                site_date=parse_site_date(date_txt),
            ))
        return out
