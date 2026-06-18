"""Funkcje pomocnicze do wyciagania liczb i dat z tekstu ze stron."""
from __future__ import annotations
import re
from datetime import date, timedelta
from typing import Optional

# Polskie nazwy miesiecy (mianownik i dopelniacz) -> numer
_MIESIACE = {
    "stycznia": 1, "styczen": 1, "styczeń": 1,
    "lutego": 2, "luty": 2,
    "marca": 3, "marzec": 3,
    "kwietnia": 4, "kwiecien": 4, "kwiecień": 4,
    "maja": 5, "maj": 5,
    "czerwca": 6, "czerwiec": 6,
    "lipca": 7, "lipiec": 7,
    "sierpnia": 8, "sierpien": 8, "sierpień": 8,
    "wrzesnia": 9, "wrzesien": 9, "września": 9, "wrzesień": 9,
    "pazdziernika": 10, "pazdziernik": 10, "października": 10, "październik": 10,
    "listopada": 11, "listopad": 11,
    "grudnia": 12, "grudzien": 12, "grudzień": 12,
}


def parse_price(text: Optional[str]) -> Optional[int]:
    """'319 000 zl' / '395 000 zł' -> 319000. Zwraca None gdy brak liczby."""
    if not text:
        return None
    # bierzemy fragment przed 'zl' aby pominac cene za m2, jesli jest w tym samym tekscie
    head = re.split(r"zł|zl|/", text, maxsplit=1)[0]
    digits = re.sub(r"[^\d]", "", head)
    if not digits:
        return None
    try:
        val = int(digits)
    except ValueError:
        return None
    # odrzucamy absurdy (np. zlapany numer telefonu) - ceny < 1000 zl raczej nie sa sprzedaza
    return val if val >= 1000 else None


def parse_area(text: Optional[str]) -> Optional[float]:
    """'45 m2' / '34,5 m²' -> 45.0 / 34.5"""
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_rooms(text: Optional[str]) -> Optional[int]:
    """'3 pokoje' / '2-pokojowe' -> 3 / 2"""
    if not text:
        return None
    m = re.search(r"(\d+)\s*[- ]?pok", text.lower())
    if m:
        return int(m.group(1))
    return None


def parse_site_date(text: Optional[str], today: Optional[date] = None) -> Optional[str]:
    """Probuje wyciagnac date dodania/odswiezenia z tekstu portalu.

    Obsluguje: 'dzisiaj', 'wczoraj', '2026.06.02', '02.06.2026',
    '2 czerwca 2026'. Zwraca ISO 'YYYY-MM-DD' albo None.
    """
    if not text:
        return None
    today = today or date.today()
    t = text.lower()

    if "dzisiaj" in t or "dzis" in t or "dziś" in t:
        return today.isoformat()
    if "wczoraj" in t:
        return (today - timedelta(days=1)).isoformat()

    # format YYYY.MM.DD lub YYYY-MM-DD
    m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d)

    # format DD.MM.YYYY
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d{2})", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d)

    # format '2 czerwca 2026'
    m = re.search(r"(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(20\d{2})", t)
    if m and m.group(2) in _MIESIACE:
        return _safe_date(int(m.group(3)), _MIESIACE[m.group(2)], int(m.group(1)))

    return None


def _safe_date(y: int, mo: int, d: int) -> Optional[str]:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def clean_text(text: Optional[str]) -> str:
    """Normalizuje bialy znak (w tym twarde spacje) do pojedynczych spacji."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()
