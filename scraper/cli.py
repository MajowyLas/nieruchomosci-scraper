"""Interfejs wiersza polecen: scrape / raport / wszystko."""
from __future__ import annotations
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from .config import load_config, Config
from .http import HttpClient
from .storage import Database
from .sites import SCRAPERS
from . import report as report_mod


def _enable_windows_ansi() -> None:
    """Wlacza obsluge kolorow ANSI w konsoli Windows (jesli to mozliwe)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def run_scrape(cfg: Config, db: Database, log: Callable[[str], None] = print) -> None:
    """Scrapuje portale i zapisuje do bazy. `log` pozwala przekierowac komunikaty
    (CLI -> print, GUI -> okno)."""
    client = HttpClient(delay=cfg.opoznienie)
    log(f"Scrapuje portale: {', '.join(cfg.portale)}")
    log(f"Miasto: {cfg.miasto} | typy: {', '.join(cfg.typy)} | max stron: {cfg.max_stron}")
    suma_nowe, suma_znane = 0, 0
    for nazwa in cfg.portale:
        klasa = SCRAPERS.get(nazwa)
        if not klasa:
            log(f"  [!] Nieznany portal '{nazwa}' - pomijam")
            continue
        try:
            oferty = klasa(client, cfg).scrape()
            stat = db.upsert_many(oferty)
            suma_nowe += stat["nowe"]
            suma_znane += stat["znane"]
            log(f"  {nazwa}: pobrano {len(oferty)} (nowe: {stat['nowe']}, znane: {stat['znane']})")
        except Exception as e:  # jeden portal nie moze polozyc calego scrapowania
            log(f"  {nazwa}: BLAD: {type(e).__name__}: {e}")
    log(f"Razem: {suma_nowe} nowych, {suma_znane} znanych ofert zapisanych do bazy.")


def fetch_filtered(cfg: Config, db: Database) -> list[sqlite3.Row]:
    """Pobiera oferty z bazy i stosuje filtry parametrow z konfiguracji.
    Wspoldzielone przez raport CLI i GUI."""
    rows = db.fetch_all(sites=cfg.portale, types=cfg.typy)
    return report_mod.filtruj_oferty(
        rows,
        cena=(cfg.cena_min, cfg.cena_max),
        powierzchnia=(cfg.powierzchnia_min, cfg.powierzchnia_max),
        pokoje=(cfg.pokoje_min, cfg.pokoje_max),
    )


def run_report(cfg: Config, db: Database, kategoria: str, zapisz: str | None,
               bez_kolorow: bool, tylko_okazje: bool) -> None:
    rows = fetch_filtered(cfg, db)
    dzis = date.today()
    prog = cfg.okazja_prog_procent
    if not bez_kolorow:
        _enable_windows_ansi()
    use_color = (not bez_kolorow) and sys.stdout.isatty()
    print(report_mod.render_terminal(rows, dzis, kategoria, use_color=use_color,
                                     prog_okazji=prog, tylko_okazje=tylko_okazje))
    if zapisz:
        p = Path(zapisz)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            report_mod.render_markdown(rows, dzis, kategoria, prog_okazji=prog,
                                       tylko_okazje=tylko_okazje),
            encoding="utf-8",
        )
        print(f"\nRaport zapisany do: {p}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nieruchomosci",
        description="Scraper ogloszen nieruchomosci z raportem wg daty dodania.",
    )
    p.add_argument("--config", default="config.yaml", help="sciezka do pliku konfiguracji")
    p.add_argument("--db", default="data/nieruchomosci.db", help="sciezka do bazy danych")
    sub = p.add_subparsers(dest="komenda")

    sub.add_parser("scrape", help="pobierz oferty i zapisz do bazy (bez raportu)")

    for nazwa in ("raport", "wszystko"):
        sp = sub.add_parser(
            nazwa,
            help=("pokaz raport z bazy" if nazwa == "raport"
                  else "scrapuj, a nastepnie pokaz raport"),
        )
        sp.add_argument("--kategoria", choices=list(report_mod.KATEGORIE),
                        default="wszystkie", help="ktora kategorie wyswietlic")
        sp.add_argument("--zapisz", metavar="PLIK", default=None,
                        help="zapisz raport do pliku .md")
        sp.add_argument("--bez-kolorow", action="store_true", help="wylacz kolory ANSI")
        sp.add_argument("--tylko-okazje", action="store_true",
                        help="pokaz wylacznie oferty oznaczone jako okazja")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # polskie znaki w konsoli Windows
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    komenda = args.komenda or "wszystko"  # domyslnie: scrapuj + raport

    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Blad konfiguracji: {e}", file=sys.stderr)
        return 2

    db = Database(args.db)
    try:
        if komenda in ("scrape", "wszystko"):
            run_scrape(cfg, db)
        if komenda in ("raport", "wszystko"):
            kategoria = getattr(args, "kategoria", "wszystkie")
            zapisz = getattr(args, "zapisz", None)
            bez_kolorow = getattr(args, "bez_kolorow", False)
            tylko_okazje = getattr(args, "tylko_okazje", False)
            run_report(cfg, db, kategoria, zapisz, bez_kolorow, tylko_okazje)
    finally:
        db.close()
    return 0
