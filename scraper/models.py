"""Jednolity model ogloszenia, niezalezny od portalu."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Listing:
    """Pojedyncze ogloszenie sprowadzone do wspolnego ksztaltu.

    Kazdy adapter portalu produkuje obiekty Listing - dzieki temu baza
    danych i raport nie musza wiedziec, z jakiego serwisu pochodzi oferta.
    """
    site: str                       # nazwa portalu, np. "olx"
    listing_id: str                 # ID nadane przez portal (klucz deduplikacji)
    url: str                        # pelny adres oferty
    title: str                      # tytul ogloszenia
    price: Optional[int] = None     # cena w zlotych (sparsowana), None gdy brak
    price_raw: str = ""             # cena jak na stronie, np. "319 000 zl"
    location: str = ""              # lokalizacja tekstowo
    area: Optional[float] = None    # powierzchnia w m2
    rooms: Optional[int] = None     # liczba pokoi
    property_type: str = ""         # "mieszkanie" lub "dom"
    transaction: str = "sprzedaz"   # rodzaj transakcji
    site_date: Optional[str] = None # data dodania wg portalu (ISO YYYY-MM-DD), jesli dostepna

    # --- pola wypelniane dopiero przy "poglebianiu" (wejscie na podstrone) ---
    plot_area: Optional[float] = None       # powierzchnia dzialki w m2
    floor: Optional[str] = None             # pietro (tekst, np. "2/4")
    year_built: Optional[int] = None        # rok budowy
    description: Optional[str] = None        # skrocony opis
    image_urls: list[str] = field(default_factory=list)  # adresy zdjec
    detail_fetched: bool = False            # czy podstrona zostala juz pobrana

    def key(self) -> tuple[str, str]:
        """Klucz jednoznacznie identyfikujacy oferte (portal + ID)."""
        return (self.site, self.listing_id)

    def as_dict(self) -> dict:
        return asdict(self)
