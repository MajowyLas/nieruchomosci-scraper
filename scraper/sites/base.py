"""Bazowy adapter portalu - wspolna petla scrapowania i filtrowania."""
from __future__ import annotations
from typing import Iterator, Optional

from ..config import Config
from ..http import HttpClient
from ..models import Listing


class BaseScraper:
    """Wspolny szkielet. Adaptery nadpisuja build_url() i parse_listings()."""

    name: str = "base"

    def __init__(self, client: HttpClient, config: Config):
        self.client = client
        self.config = config

    # --- do nadpisania w adapterach ---
    def build_url(self, property_type: str, page: int) -> Optional[str]:
        """Zwraca adres strony wynikow dla danego typu i numeru strony.
        Zwroc None, aby zatrzymac stronicowanie."""
        raise NotImplementedError

    def parse_listings(self, html: str, property_type: str) -> list[Listing]:
        """Parsuje HTML strony wynikow do listy ofert."""
        raise NotImplementedError

    # --- wspolna logika ---
    def iter_pages(self, property_type: str) -> Iterator[str]:
        """Pobiera kolejne strony wynikow (do max_stron). Yielduje HTML."""
        for page in range(1, self.config.max_stron + 1):
            url = self.build_url(property_type, page)
            if not url:
                break
            resp = self.client.get(url)
            if resp is None or resp.status_code != 200:
                code = resp.status_code if resp else "brak odpowiedzi"
                print(f"  [{self.name}] strona {page} ({property_type}): {code} - przerywam")
                break
            yield resp.text

    def scrape_one_type(self, ptype: str) -> list[Listing]:
        """Scrapuje pojedynczy typ (mieszkanie/dom). Wydzielone, by mozna bylo
        scrapowac typy rownolegle."""
        collected: dict[tuple[str, str], Listing] = {}
        for html in self.iter_pages(ptype):
            items = self.parse_listings(html, ptype)
            if not items:
                break  # pusta strona = koniec wynikow
            for it in items:
                collected.setdefault(it.key(), it)
        return list(collected.values())

    def scrape(self) -> list[Listing]:
        """Pelne scrapowanie portalu wg konfiguracji (wszystkie typy).
        Zapisujemy WSZYSTKO - filtry po cenie/metrazu/pokojach sa na etapie raportu."""
        collected: dict[tuple[str, str], Listing] = {}
        for ptype in self.config.typy:
            for it in self.scrape_one_type(ptype):
                collected.setdefault(it.key(), it)
        return list(collected.values())
