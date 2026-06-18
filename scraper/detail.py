"""Poglebianie ofert: parsowanie podstrony + pobieranie zdjec.

Listy wynikow daja podstawy (cena, metraz). Podstrona dodaje: powierzchnie
dzialki, rok budowy, pietro, opis i adresy zdjec. To 1 zapytanie na oferte,
wiec robimy to tylko dla ofert po filtrach.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# wzorce adresow zdjec per portal (pomijamy logo/baner/awatary)
_IMG_PATTERNS = {
    "olx": r'https://[a-z0-9.\-]*olxcdn\.com[^"\\\s]+?image[^"\\\s;]*',
    "gratka": r'https://(?:img\d+\.staticmorizon\.com\.pl|thumbs\.cdngr\.pl)/[^"\\\s]+?\.(?:jpe?g|webp)',
    "nieruchomosci-online": r'https://i\.st-nieruchomosci-online\.pl/[^"\\\s]+?\.(?:jpe?g|webp)',
}


def extract_detail(html: str, site: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    return {
        "plot_area": _powierzchnia_dzialki(text),
        "year_built": _rok_budowy(text),
        "floor": _pietro(text),
        "description": _opis(soup),
        "image_urls": _zdjecia(soup, html, site, base_url),
    }


def _liczba(s: str) -> Optional[float]:
    s = s.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _powierzchnia_dzialki(text: str) -> Optional[float]:
    """Szuka 'powierzchnia dzialki ... X m2/ar/ha' i zwraca metry kwadratowe."""
    etykiety = ["powierzchnia działki", "pow. działki", "powierzchnia terenu",
                "powierzchnia gruntu", "powierzchnia działek", "działka o pow"]
    for et in etykiety:
        m = re.search(et + r"[^0-9]{0,15}(\d[\d \xa0.,]*)\s*(ha|ar|m)", text, re.IGNORECASE)
        if m:
            val = _liczba(m.group(1))
            if val is None:
                continue
            jedn = m.group(2).lower()
            if jedn == "ha":
                return round(val * 10000)
            if jedn == "ar":
                return round(val * 100)
            return round(val)
    return None


def _rok_budowy(text: str) -> Optional[int]:
    m = re.search(r"rok budowy[^0-9]{0,8}((?:19|20)\d{2})", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _pietro(text: str) -> Optional[str]:
    m = re.search(r"piętro[:\s]{1,3}(parter|\d{1,2}(?:\s*/\s*\d{1,2})?)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(parter)\b", text, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _opis(soup: BeautifulSoup) -> Optional[str]:
    for sel in [('meta', {'property': 'og:description'}), ('meta', {'name': 'description'})]:
        el = soup.find(*sel)
        if el and el.get("content"):
            opis = el["content"].strip()
            if len(opis) > 30:
                return opis[:600]
    return None


def _zdjecia(soup: BeautifulSoup, html: str, site: str, base_url: str) -> list[str]:
    urls: list[str] = []

    if site == "tarnowiak":
        # WYLACZNIE galeria oferty (div.images / a.fancybox) - poza nia sa banery
        # reklamowe (SKUP AUT itp.), ktorych NIE chcemy pobierac.
        gal = soup.select_one("div.images")
        if gal:
            for a in gal.select("a.fancybox[href]"):
                urls.append(urljoin(base_url, a["href"]))
            if not urls:
                for img in gal.select("img[src]"):
                    if "/obrazki/" in img.get("src", ""):
                        urls.append(urljoin(base_url, img["src"]))
        return _oczysc_zdjecia(urls)

    # pozostale portale: glowne zdjecie z og:image + wzorzec CDN
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        urls.append(og["content"])
    pattern = _IMG_PATTERNS.get(site)
    if pattern:
        urls += re.findall(pattern, html)
    return _oczysc_zdjecia(urls)


def _oczysc_zdjecia(urls: list[str]) -> list[str]:

    # odfiltruj smieci i duplikaty (po fragmencie identyfikujacym zdjecie)
    czyste, widziane = [], set()
    for u in urls:
        if any(x in u.lower() for x in ("logo", "sprite", "icon", "avatar", "premium", "banner")):
            continue
        klucz = re.sub(r"(s=\d+x\d+|/\d+x\d+|thumb/|_s:|_m:|3x2)", "", u)[-60:]
        if klucz in widziane:
            continue
        widziane.add(klucz)
        czyste.append(u)
    return czyste[:8]


def pobierz_zdjecia(image_urls: list[str], dest_dir: Path, cap: int = 6,
                    session: Optional[requests.Session] = None) -> list[str]:
    """Pobiera zdjecia do katalogu. Zwraca liste lokalnych sciezek."""
    if not image_urls:
        return []
    dest_dir = Path(dest_dir)
    # juz pobrane? nie pobieramy drugi raz
    if dest_dir.exists():
        istniejace = sorted(str(p) for p in dest_dir.glob("*.jpg"))
        if istniejace:
            return istniejace
    dest_dir.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    zapisane = []
    for i, url in enumerate(image_urls[:cap], 1):
        try:
            r = sess.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and r.content:
                p = dest_dir / f"{i:02d}.jpg"
                p.write_bytes(r.content)
                zapisane.append(str(p))
        except requests.RequestException:
            continue
    return zapisane
