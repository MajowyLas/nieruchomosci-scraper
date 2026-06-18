"""Generowanie raportu: kategoryzacja po dacie + wydruk w terminalu."""
from __future__ import annotations
import sqlite3
import statistics
from datetime import datetime, date
from typing import Optional

# Kategorie wg liczby dni wstecz (None = bez limitu). Kolejnosc ma znaczenie.
KATEGORIE = {
    "dzis": 0,
    "3dni": 2,
    "7dni": 6,
    "wszystkie": None,
}
NAZWY = {
    "dzis": "Nowe dzis",
    "3dni": "Ostatnie 3 dni",
    "7dni": "Ostatnie 7 dni",
    "wszystkie": "Wszystkie",
}


def _data_pierwszego(row: sqlite3.Row) -> date:
    return datetime.fromisoformat(row["first_seen"]).date()


def naleznik_do_okna(data_pierwsza: date, dzis: date, kategoria: str) -> bool:
    """Czy oferta o dacie 'data_pierwsza' nalezy do okna 'kategoria'?

    Regula: kategorie KUMULATYWNE wg dni kalendarzowych. 'dzis' = 0 dni temu,
    '3dni' = nie wczesniej niz 2 dni temu (czyli dzis + 2 poprzednie), itd.
    'wszystkie' = zawsze prawda.

    To jest miejsce, w ktorym latwo zmienic semantyke kategorii - np. na okna
    kroczace co do godziny albo na pasma rozlaczne.
    """
    limit = KATEGORIE[kategoria]
    if limit is None:
        return True
    delta = (dzis - data_pierwsza).days
    return 0 <= delta <= limit


def policz_kategorie(rows: list[sqlite3.Row], dzis: date) -> dict[str, int]:
    """Zwraca liczbe ofert w kazdej kategorii (kumulatywnie)."""
    return {
        kat: sum(1 for r in rows if naleznik_do_okna(_data_pierwszego(r), dzis, kat))
        for kat in KATEGORIE
    }


def etykieta_wieku(d: date, dzis: date) -> str:
    delta = (dzis - d).days
    if delta <= 0:
        return "dzis"
    if delta == 1:
        return "wczoraj"
    if delta < 7:
        return f"{delta} dni temu"
    return d.isoformat()


# ---------- wykrywanie okazji cenowych ----------
def cena_za_m2(row: sqlite3.Row) -> Optional[float]:
    if row["price"] and row["area"]:
        return row["price"] / row["area"]
    return None


def mediany_cen_m2(rows: list[sqlite3.Row]) -> dict[str, float]:
    """Mediana ceny za m2 osobno dla kazdego typu (mieszkanie / dom).

    Mediana jest odporna na wartosci skrajne - pojedyncza luksusowa oferta
    nie zaburza 'normy' rynkowej.
    """
    grupy: dict[str, list[float]] = {}
    for r in rows:
        c = cena_za_m2(r)
        if c:
            grupy.setdefault(r["property_type"], []).append(c)
    return {typ: statistics.median(v) for typ, v in grupy.items() if v}


def czy_okazja(row: sqlite3.Row, mediany: dict[str, float], prog_procent: float) -> bool:
    """Reguła okazji: cena/m2 ponizej `prog_procent`% mediany dla danego typu.

    >>> To jest miejsce, w ktorym Twoja wiedza o rynku ma znaczenie. <<<
    Mozesz zmienic regule, np.:
      - staly prog procentowy (obecnie),
      - dolny percentyl (np. najtansze 20%),
      - odchylenie standardowe ponizej sredniej.
    """
    c = cena_za_m2(row)
    mediana = mediany.get(row["property_type"])
    if c is None or not mediana:
        return False
    return c < mediana * (prog_procent / 100.0)


def rabat_od_mediany(row: sqlite3.Row, mediany: dict[str, float]) -> Optional[int]:
    """O ile procent ponizej mediany jest oferta (dodatnie = taniej)."""
    c = cena_za_m2(row)
    mediana = mediany.get(row["property_type"])
    if c is None or not mediana:
        return None
    return round((1 - c / mediana) * 100)


# ---------- formatowanie ----------
class _C:
    """Kody ANSI (wlaczane tylko gdy terminal je obsluguje)."""
    def __init__(self, enabled: bool):
        self.B = "\033[1m" if enabled else ""
        self.DIM = "\033[2m" if enabled else ""
        self.CYAN = "\033[36m" if enabled else ""
        self.GREEN = "\033[32m" if enabled else ""
        self.YELLOW = "\033[33m" if enabled else ""
        self.R = "\033[0m" if enabled else ""


def _cena(v: Optional[int]) -> str:
    if v is None:
        return "cena: do uzgodnienia"
    return f"{v:,}".replace(",", " ") + " zl"


def _szczegoly(row: sqlite3.Row) -> str:
    czesci = []
    if row["area"]:
        czesci.append(f"{row['area']:g} m2")
    if row["rooms"]:
        czesci.append(f"{row['rooms']} pok.")
    if row["price"] and row["area"]:
        czesci.append(f"{round(row['price'] / row['area']):,}".replace(",", " ") + " zl/m2")
    return " | ".join(czesci)


def render_terminal(rows: list[sqlite3.Row], dzis: date, kategoria: str,
                    use_color: bool = True, prog_okazji: float = 85.0,
                    tylko_okazje: bool = False) -> str:
    c = _C(use_color)
    linie: list[str] = []
    liczby = policz_kategorie(rows, dzis)
    mediany = mediany_cen_m2(rows)  # 'norma' liczona z calego rynku w bazie

    linie.append("")
    linie.append(f"{c.B}{c.CYAN}{'=' * 64}{c.R}")
    linie.append(f"{c.B}{c.CYAN}  RAPORT NIERUCHOMOSCI  -  {dzis.isoformat()}{c.R}")
    linie.append(f"{c.B}{c.CYAN}{'=' * 64}{c.R}")
    linie.append("")
    linie.append(f"  {c.B}Podsumowanie:{c.R}")
    for kat in KATEGORIE:
        gwiazdka = "  <--" if kat == kategoria else ""
        linie.append(f"    {NAZWY[kat]:<18} {c.B}{c.GREEN}{liczby[kat]:>4}{c.R}{c.DIM}{gwiazdka}{c.R}")
    for typ, med in sorted(mediany.items()):
        linie.append(f"    {c.DIM}mediana {typ:<10} {round(med):>6,} zl/m2{c.R}".replace(",", " "))
    linie.append("")

    wybrane = [r for r in rows if naleznik_do_okna(_data_pierwszego(r), dzis, kategoria)]
    if tylko_okazje:
        wybrane = [r for r in wybrane if czy_okazja(r, mediany, prog_okazji)]
    wybrane.sort(key=lambda r: (r["first_seen"], -(r["price"] or 0)), reverse=True)

    tytul_sekcji = NAZWY[kategoria].upper() + (" - OKAZJE" if tylko_okazje else "")
    linie.append(f"  {c.B}{tytul_sekcji} ({len(wybrane)} ofert){c.R}")
    linie.append(f"  {c.DIM}{'-' * 60}{c.R}")

    if not wybrane:
        linie.append(f"  {c.DIM}(brak ofert w tej kategorii){c.R}")
    for i, row in enumerate(wybrane, 1):
        wiek = etykieta_wieku(_data_pierwszego(row), dzis)
        szcz = _szczegoly(row)
        okazja = czy_okazja(row, mediany, prog_okazji)
        znak = f"{c.YELLOW}{c.B}[OKAZJA] {c.R}" if okazja else ""
        linie.append(f"  {c.B}{i:>3}. {znak}{c.B}{row['title']}{c.R}")
        meta = f"       {c.GREEN}{c.B}{_cena(row['price'])}{c.R}"
        if szcz:
            meta += f"  {c.DIM}|{c.R}  {szcz}"
        if okazja:
            rabat = rabat_od_mediany(row, mediany)
            meta += f"  {c.YELLOW}{c.B}(-{rabat}% od mediany){c.R}"
        linie.append(meta)
        linie.append(f"       {c.DIM}{row['location']}  -  {row['site']}  -  {c.YELLOW}{wiek}{c.R}")
        linie.append(f"       {c.DIM}{row['url']}{c.R}")
        linie.append("")

    return "\n".join(linie)


def render_markdown(rows: list[sqlite3.Row], dzis: date, kategoria: str,
                    prog_okazji: float = 85.0, tylko_okazje: bool = False) -> str:
    liczby = policz_kategorie(rows, dzis)
    mediany = mediany_cen_m2(rows)
    out = [f"# Raport nieruchomosci - {dzis.isoformat()}", ""]
    out.append("## Podsumowanie")
    for kat in KATEGORIE:
        out.append(f"- **{NAZWY[kat]}**: {liczby[kat]}")
    for typ, med in sorted(mediany.items()):
        out.append(f"- mediana {typ}: {round(med):,} zl/m2".replace(",", " "))
    out.append("")
    wybrane = [r for r in rows if naleznik_do_okna(_data_pierwszego(r), dzis, kategoria)]
    if tylko_okazje:
        wybrane = [r for r in wybrane if czy_okazja(r, mediany, prog_okazji)]
    wybrane.sort(key=lambda r: (r["first_seen"], -(r["price"] or 0)), reverse=True)
    tytul = NAZWY[kategoria] + (" - okazje" if tylko_okazje else "")
    out.append(f"## {tytul} ({len(wybrane)})")
    out.append("")
    out.append("| # | Okazja | Tytul | Cena | Szczegoly | Lokalizacja | Portal | Dodano | Link |")
    out.append("|---|:---:|-------|------|-----------|-------------|--------|--------|------|")
    for i, row in enumerate(wybrane, 1):
        wiek = etykieta_wieku(_data_pierwszego(row), dzis)
        if czy_okazja(row, mediany, prog_okazji):
            rabat = rabat_od_mediany(row, mediany)
            ozn = f"-{rabat}%"
        else:
            ozn = ""
        out.append(
            f"| {i} | {ozn} | {row['title']} | {_cena(row['price'])} | {_szczegoly(row)} | "
            f"{row['location']} | {row['site']} | {wiek} | {row['url']} |"
        )
    return "\n".join(out)
