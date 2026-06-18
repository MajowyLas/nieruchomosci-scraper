"""Interfejs wiersza polecen: scrape / raport / wszystko."""
from __future__ import annotations
import argparse
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Callable

import requests

from .config import load_config, Config
from .http import HttpClient, _DEFAULT_HEADERS
from .storage import Database
from .sites import SCRAPERS
from .geo import Geocoder, policz_odleglosci, geokoduj_wspolrzedne, haversine
from .detail import extract_detail, pobierz_zdjecia
from . import report as report_mod

# ile podstron ofert pobierac naraz przy poglebianiu (kompromis szybkosc/grzecznosc)
DETAL_WATKI = 6


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


def run_scrape(cfg: Config, db: Database, log: Callable[[str], None] = print,
               progress=None, stop=None) -> None:
    """Scrapuje portale RÓWNOLEGLE (kazdy na osobnym watku) i zapisuje do bazy.
    `stop()` (callable -> bool) pozwala przerwac miedzy zadaniami."""
    log(f"Scrapuje rownolegle: {', '.join(cfg.portale)} (typy: {', '.join(cfg.typy)})")
    log(f"Miasto: {cfg.miasto} | max stron: {cfg.max_stron}")
    # zadania na poziomie (portal, typ) - mieszkania i domy z tego samego portalu ida naraz
    zadania = [(n, t) for n in cfg.portale if SCRAPERS.get(n) for t in cfg.typy]
    razem = len(zadania)

    def scrape_zadanie(nazwa, ptype):
        if stop and stop():
            return nazwa, [], None
        try:
            client = HttpClient(delay=cfg.opoznienie)  # osobny klient = osobna pauza
            return nazwa, SCRAPERS[nazwa](client, cfg).scrape_one_type(ptype), None
        except Exception as e:
            return nazwa, None, f"{type(e).__name__}: {e}"

    suma_nowe = suma_znane = done = 0
    with ThreadPoolExecutor(max_workers=min(razem, 8)) as ex:
        futs = [ex.submit(scrape_zadanie, n, t) for n, t in zadania]
        for fut in as_completed(futs):
            if stop and stop():
                ex.shutdown(wait=False, cancel_futures=True)
                log("Przerwano scrapowanie.")
                break
            nazwa, oferty, err = fut.result()
            if err:
                log(f"  {nazwa}: BLAD: {err}")
            else:
                stat = db.upsert_many(oferty)  # zapis w watku wywolujacym (1 polaczenie)
                suma_nowe += stat["nowe"]
                suma_znane += stat["znane"]
                log(f"  {nazwa}: +{len(oferty)} (nowe: {stat['nowe']})")
            done += 1
            if progress:
                progress(done, razem)
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


def fetch_details(cfg: Config, db: Database, rows, log: Callable[[str], None] = lambda m: None,
                  pobieraj_zdjecia: bool = True, progress=None, stop=None) -> int:
    """Poglebia oferty (podstrona + zdjecia) - tylko te jeszcze niepobrane.
    `progress(done, total)` raportuje postep. Zwraca liczbe poglebionych ofert."""
    do_pobrania = [r for r in rows if not r["detail_fetched"]]
    if not do_pobrania:
        log("Wszystkie oferty maja juz pobrane szczegoly.")
        return 0
    razem = len(do_pobrania)
    log(f"Poglebianie {razem} ofert rownolegle ({DETAL_WATKI} naraz)...")
    sesja = requests.Session()
    sesja.headers.update(_DEFAULT_HEADERS)

    def zadanie(r):
        if stop and stop():
            return r, None
        try:
            resp = sesja.get(r["url"], timeout=25)
            if resp.status_code != 200:
                return r, None
            det = extract_detail(resp.text, r["site"], r["url"])
            if pobieraj_zdjecia and det["image_urls"]:
                dest = Path("data/photos") / f"{r['site']}_{r['listing_id']}"
                pobierz_zdjecia(det["image_urls"], dest, session=sesja)
                det["photos_dir"] = str(dest)
            return r, det
        except Exception:
            return r, None

    done = zrobione = 0
    with ThreadPoolExecutor(max_workers=DETAL_WATKI) as ex:
        futs = [ex.submit(zadanie, r) for r in do_pobrania]
        for fut in as_completed(futs):
            if stop and stop():
                ex.shutdown(wait=False, cancel_futures=True)
                log("Przerwano poglebianie.")
                break
            r, det = fut.result()
            if det is not None:
                db.update_detail(r["site"], r["listing_id"], det)  # zapis w 1 watku
                zrobione += 1
            done += 1
            if progress:
                progress(done, razem)
            if done % 10 == 0 or done == razem:
                log(f"  ...{done}/{razem}")
    log(f"Poglebiono {zrobione} ofert.")
    return zrobione


def oblicz_odleglosci(cfg: Config, rows, log: Callable[[str], None] = lambda m: None,
                      progress=None, stop=None) -> dict:
    """Liczy odleglosc kazdej oferty od cfg.lokalizacja_odniesienia (w km).
    Pusty slownik, gdy lokalizacja nie podana lub nieznaleziona. Wspoldzielone
    przez CLI i GUI."""
    # punkt odniesienia: jawnie podany, a gdy ustawiono tylko promien km - miasto
    punkt = cfg.lokalizacja_odniesienia or (cfg.miasto if cfg.max_km else None)
    if not punkt:
        return {}
    geo = Geocoder()
    try:
        ref = geo.geocode(punkt)
        if not ref:
            log(f"Nie znaleziono lokalizacji odniesienia: {punkt}")
            return {}
        log(f"Punkt odniesienia: {punkt} -> {ref[0]:.4f}, {ref[1]:.4f}")
        return policz_odleglosci(rows, ref, geo, log=log, progress=progress, stop=stop)
    finally:
        geo.close()


def oblicz_odleglosci_i_wsp(cfg: Config, rows, log: Callable[[str], None] = lambda m: None,
                            progress=None, stop=None):
    """Zwraca (km_dict, coords_dict, ref). Wspolrzedne sluza tez do mapy.
    Punkt odniesienia: lokalizacja_odniesienia, inaczej miasto."""
    punkt = cfg.lokalizacja_odniesienia or cfg.miasto
    geo = Geocoder()
    try:
        ref = geo.geocode(punkt)
        coords = geokoduj_wspolrzedne(rows, geo, log=log, progress=progress, stop=stop)
        km = ({k: haversine(ref[0], ref[1], la, lo) for k, (la, lo) in coords.items()}
              if ref else {})
        return km, coords, ref
    finally:
        geo.close()


def run_report(cfg: Config, db: Database, kategoria: str, zapisz: str | None,
               bez_kolorow: bool, tylko_okazje: bool, sortuj_odleglosc: bool = False) -> None:
    rows = fetch_filtered(cfg, db)
    dzis = date.today()
    prog = cfg.okazja_prog_procent
    # geokodujemy tylko oferty z wyswietlanej kategorii (oszczednosc zapytan)
    okno = report_mod.tylko_w_oknie(rows, dzis, kategoria)
    odleglosci = oblicz_odleglosci(cfg, okno, log=print)
    rows = report_mod.filtruj_po_km(rows, odleglosci, cfg.max_km)
    rows, also_on = report_mod.deduplikuj(rows)
    if not bez_kolorow:
        _enable_windows_ansi()
    use_color = (not bez_kolorow) and sys.stdout.isatty()
    print(report_mod.render_terminal(rows, dzis, kategoria, use_color=use_color,
                                     prog_okazji=prog, tylko_okazje=tylko_okazje,
                                     odleglosci=odleglosci, sortuj_po_odleglosci=sortuj_odleglosc,
                                     also_on=also_on))
    if zapisz:
        p = Path(zapisz)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            report_mod.render_markdown(rows, dzis, kategoria, prog_okazji=prog,
                                       tylko_okazje=tylko_okazje, odleglosci=odleglosci,
                                       sortuj_po_odleglosci=sortuj_odleglosc),
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
    sub.add_parser("detale", help="poglebia oferty po filtrach: podstrony + zdjecia")

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
        sp.add_argument("--sortuj-odleglosc", action="store_true",
                        help="sortuj wg odleglosci (wymaga lokalizacja_odniesienia w config)")
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
        if komenda == "detale":
            fetch_details(cfg, db, fetch_filtered(cfg, db), log=print)
        if komenda in ("raport", "wszystko"):
            kategoria = getattr(args, "kategoria", "wszystkie")
            zapisz = getattr(args, "zapisz", None)
            bez_kolorow = getattr(args, "bez_kolorow", False)
            tylko_okazje = getattr(args, "tylko_okazje", False)
            sortuj_odleglosc = getattr(args, "sortuj_odleglosc", False)
            run_report(cfg, db, kategoria, zapisz, bez_kolorow, tylko_okazje, sortuj_odleglosc)
    finally:
        db.close()
    return 0
