"""Wspolny klient HTTP: naglowki przegladarki, opoznienia, ponawianie."""
from __future__ import annotations
import time
import requests

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


class HttpClient:
    """Lekki wrapper na requests.Session z uprzejmym opoznieniem.

    Jeden klient jest wspoldzielony przez wszystkie adaptery - dzieki temu
    odstep miedzy zapytaniami i polityka ponawiania sa jednolite.
    """

    def __init__(self, delay: float = 1.5, timeout: int = 25, retries: int = 2):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(_DEFAULT_HEADERS)
        self._last_request = 0.0

    def get(self, url: str) -> "requests.Response | None":
        """Pobiera URL z opoznieniem i ponawianiem. Zwraca None przy porazce."""
        self._respect_delay()
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self._last_request = time.monotonic()
                if resp.status_code == 200:
                    return resp
                # 403/429 - serwer nas blokuje/ogranicza; poczekaj dluzej i sprobuj ponownie
                if resp.status_code in (403, 429, 503) and attempt < self.retries:
                    time.sleep(self.delay * (attempt + 2))
                    continue
                return resp  # inny kod - oddajemy, adapter zdecyduje
            except requests.RequestException as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(self.delay * (attempt + 1))
                    continue
        if last_err:
            print(f"  [http] blad pobierania {url}: {last_err}")
        return None

    def _respect_delay(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
