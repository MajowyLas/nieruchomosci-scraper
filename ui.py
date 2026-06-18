#!/usr/bin/env python
"""Proste okno (GUI) do wprowadzania parametrow, scrapowania i podgladu raportu.

Uruchom:  python ui.py
Calosc opiera sie na tej samej logice co CLI (scraper.cli / scraper.report).
"""
from __future__ import annotations
import queue
import threading
import webbrowser
from datetime import date
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yaml

from scraper.config import Config, load_config
from scraper.storage import Database
from scraper.cli import run_scrape, fetch_filtered, oblicz_odleglosci
from scraper import report as report_mod

CONFIG_PATH = "config.yaml"
DB_PATH = "data/nieruchomosci.db"
PORTALE = ["olx", "gratka", "nieruchomosci-online", "tarnowiak"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scraper nieruchomosci")
        self.root.geometry("960x720")
        self._q: queue.Queue = queue.Queue()
        self._then_report = False

        self._build_widgets()
        self._wczytaj_z_config()       # prefill z istniejacego config.yaml
        self.root.after(120, self._drain_queue)

    # ---------- budowa interfejsu ----------
    def _build_widgets(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(side="top", fill="x")

        # --- Parametry wyszukiwania ---
        par = ttk.LabelFrame(top, text="Parametry wyszukiwania", padding=10)
        par.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(par, text="Miasto:").grid(row=0, column=0, sticky="w", pady=2)
        self.e_miasto = ttk.Entry(par, width=18)
        self.e_miasto.grid(row=0, column=1, columnspan=3, sticky="w", pady=2)

        ttk.Label(par, text="Rodzaj:").grid(row=1, column=0, sticky="w", pady=2)
        self.v_mieszkanie = tk.BooleanVar(value=True)
        self.v_dom = tk.BooleanVar(value=True)
        ttk.Checkbutton(par, text="mieszkanie", variable=self.v_mieszkanie).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(par, text="dom", variable=self.v_dom).grid(row=1, column=2, sticky="w")

        self.e_cena_min, self.e_cena_max = self._para_pol(par, 2, "Cena [zl]:")
        self.e_pow_min, self.e_pow_max = self._para_pol(par, 3, "Metraz [m2]:")
        self.e_pok_min, self.e_pok_max = self._para_pol(par, 4, "Pokoje:")

        ttk.Label(par, text="Portale:").grid(row=5, column=0, sticky="nw", pady=2)
        self.v_portale = {}
        for i, p in enumerate(PORTALE):
            var = tk.BooleanVar(value=True)
            self.v_portale[p] = var
            ttk.Checkbutton(par, text=p, variable=var).grid(row=5 + i, column=1, columnspan=3, sticky="w")

        ttk.Label(par, text="Max stron:").grid(row=9, column=0, sticky="w", pady=2)
        self.e_max_stron = ttk.Spinbox(par, from_=1, to=20, width=6)
        self.e_max_stron.set(3)
        self.e_max_stron.grid(row=9, column=1, sticky="w")

        ttk.Label(par, text="Prog okazji [%]:").grid(row=10, column=0, sticky="w", pady=2)
        self.e_prog = ttk.Spinbox(par, from_=50, to=100, width=6)
        self.e_prog.set(85)
        self.e_prog.grid(row=10, column=1, sticky="w")

        ttk.Label(par, text="Licz km od:").grid(row=11, column=0, sticky="w", pady=2)
        self.e_lok_ref = ttk.Entry(par, width=22)
        self.e_lok_ref.grid(row=11, column=1, columnspan=4, sticky="w", pady=2)
        ttk.Label(par, text="(adres/miasto odniesienia, np. 'Tarnow, Krakowska 1')",
                  foreground="#888").grid(row=12, column=0, columnspan=5, sticky="w")

        # --- Raport ---
        rap = ttk.LabelFrame(top, text="Raport", padding=10)
        rap.pack(side="left", fill="y")

        ttk.Label(rap, text="Kategoria:").pack(anchor="w")
        self.v_kategoria = tk.StringVar(value="wszystkie")
        for kat in report_mod.KATEGORIE:
            ttk.Radiobutton(rap, text=report_mod.NAZWY[kat], value=kat,
                            variable=self.v_kategoria).pack(anchor="w")
        self.v_tylko_okazje = tk.BooleanVar(value=False)
        ttk.Checkbutton(rap, text="tylko okazje", variable=self.v_tylko_okazje).pack(anchor="w", pady=(6, 0))
        self.v_sortuj_odl = tk.BooleanVar(value=False)
        ttk.Checkbutton(rap, text="sortuj wg odleglosci", variable=self.v_sortuj_odl).pack(anchor="w")

        # --- Przyciski ---
        btns = ttk.Frame(self.root, padding=(10, 0))
        btns.pack(side="top", fill="x")
        self.b_zapisz = ttk.Button(btns, text="Zapisz parametry", command=self._zapisz_config)
        self.b_scrape = ttk.Button(btns, text="Pobierz swieze dane", command=lambda: self._start_scrape(False))
        self.b_scrape_rap = ttk.Button(btns, text="Scrapuj + raport", command=lambda: self._start_scrape(True))
        self.b_raport = ttk.Button(btns, text="Pokaz raport", command=self._pokaz_raport)
        self.b_eksport = ttk.Button(btns, text="Zapisz raport (.md)", command=self._eksport_md)
        for b in (self.b_zapisz, self.b_scrape, self.b_scrape_rap, self.b_raport, self.b_eksport):
            b.pack(side="left", padx=4, pady=8)

        self.status = ttk.Label(self.root, text="Gotowe.", anchor="w", relief="sunken", padding=4)
        self.status.pack(side="bottom", fill="x")

        # --- Pole wynikow ---
        out = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        out.pack(side="top", fill="both", expand=True)
        self.txt = tk.Text(out, wrap="none", font=("Consolas", 10), background="#1e1e1e",
                           foreground="#e0e0e0", insertbackground="#e0e0e0")
        ysb = ttk.Scrollbar(out, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_configure("okazja", foreground="#ffb000")

    def _para_pol(self, parent, row, etykieta):
        """Wiersz z etykieta i dwoma polami (od / do)."""
        ttk.Label(parent, text=etykieta).grid(row=row, column=0, sticky="w", pady=2)
        e_od = ttk.Entry(parent, width=8)
        e_do = ttk.Entry(parent, width=8)
        ttk.Label(parent, text="od").grid(row=row, column=1, sticky="e")
        e_od.grid(row=row, column=2, sticky="w")
        ttk.Label(parent, text="do").grid(row=row, column=3, sticky="e")
        e_do.grid(row=row, column=4, sticky="w")
        return e_od, e_do

    # ---------- konfiguracja <-> formularz ----------
    def _wczytaj_z_config(self) -> None:
        if not Path(CONFIG_PATH).exists():
            return
        try:
            cfg = load_config(CONFIG_PATH)
        except Exception:
            return
        self.e_miasto.insert(0, cfg.miasto)
        self.v_mieszkanie.set("mieszkanie" in cfg.typy)
        self.v_dom.set("dom" in cfg.typy)
        self._wpisz(self.e_cena_min, cfg.cena_min)
        self._wpisz(self.e_cena_max, cfg.cena_max)
        self._wpisz(self.e_pow_min, cfg.powierzchnia_min)
        self._wpisz(self.e_pow_max, cfg.powierzchnia_max)
        self._wpisz(self.e_pok_min, cfg.pokoje_min)
        self._wpisz(self.e_pok_max, cfg.pokoje_max)
        for p, var in self.v_portale.items():
            var.set(p in cfg.portale)
        self.e_max_stron.set(cfg.max_stron)
        self.e_prog.set(int(cfg.okazja_prog_procent))
        if cfg.lokalizacja_odniesienia:
            self.e_lok_ref.insert(0, cfg.lokalizacja_odniesienia)

    def _build_config(self) -> Config | None:
        typy = []
        if self.v_mieszkanie.get():
            typy.append("mieszkanie")
        if self.v_dom.get():
            typy.append("dom")
        portale = [p for p, v in self.v_portale.items() if v.get()]
        if not typy:
            messagebox.showerror("Blad", "Zaznacz przynajmniej jeden rodzaj (mieszkanie/dom).")
            return None
        if not portale:
            messagebox.showerror("Blad", "Zaznacz przynajmniej jeden portal.")
            return None
        miasto = self.e_miasto.get().strip().lower() or "tarnow"
        return Config(
            miasto=miasto,
            typy=typy,
            transakcja="sprzedaz",
            cena_min=self._opt_int(self.e_cena_min),
            cena_max=self._opt_int(self.e_cena_max),
            powierzchnia_min=self._opt_float(self.e_pow_min),
            powierzchnia_max=self._opt_float(self.e_pow_max),
            pokoje_min=self._opt_int(self.e_pok_min),
            pokoje_max=self._opt_int(self.e_pok_max),
            portale=portale,
            max_stron=self._opt_int(self.e_max_stron) or 3,
            okazja_prog_procent=self._opt_float(self.e_prog) or 85.0,
            lokalizacja_odniesienia=self.e_lok_ref.get().strip() or None,
        )

    def _zapisz_config(self) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        dane = {
            "miasto": cfg.miasto, "typy": cfg.typy, "transakcja": cfg.transakcja,
            "cena_min": cfg.cena_min, "cena_max": cfg.cena_max,
            "powierzchnia_min": cfg.powierzchnia_min, "powierzchnia_max": cfg.powierzchnia_max,
            "pokoje_min": cfg.pokoje_min, "pokoje_max": cfg.pokoje_max,
            "portale": cfg.portale, "max_stron": cfg.max_stron,
            "opoznienie": cfg.opoznienie, "okazja_prog_procent": cfg.okazja_prog_procent,
            "lokalizacja_odniesienia": cfg.lokalizacja_odniesienia,
        }
        naglowek = "# Plik wygenerowany przez UI (ui.py). Mozna edytowac recznie.\n"
        Path(CONFIG_PATH).write_text(
            naglowek + yaml.safe_dump(dane, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self._set_status(f"Zapisano parametry do {CONFIG_PATH}")

    # ---------- scrapowanie (w watku) ----------
    def _start_scrape(self, then_report: bool) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        self._then_report = then_report
        self._set_running(True)
        self._set_output("")
        self._append("=== Scrapowanie rozpoczete (moze potrwac kilkadziesiat sekund) ===\n")
        threading.Thread(target=self._scrape_worker, args=(cfg,), daemon=True).start()

    def _scrape_worker(self, cfg: Config) -> None:
        try:
            db = Database(DB_PATH)
            try:
                run_scrape(cfg, db, log=lambda m: self._q.put(("log", m)))
            finally:
                db.close()
            self._q.put(("scrape_done", cfg))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._append(str(payload) + "\n")
                elif kind == "scrape_done":
                    self._append("=== Scrapowanie zakonczone ===\n")
                    self._set_running(False)
                    self._set_status("Scrapowanie zakonczone.")
                    if self._then_report:
                        self._pokaz_raport(cfg=payload)
                elif kind == "report_text":
                    self._set_output(payload)
                    self._linkuj()
                    self._podswietl_okazje()
                    self._set_running(False)
                    self._set_status("Raport gotowy.")
                elif kind == "error":
                    self._append("BLAD: " + str(payload) + "\n")
                    self._set_running(False)
                    self._set_status("Wystapil blad.")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    # ---------- raport ----------
    def _pokaz_raport(self, cfg: Config | None = None) -> None:
        cfg = cfg or self._build_config()
        if not cfg:
            return
        # czytamy zmienne Tk TU (glowny watek) i przekazujemy do workera
        kat = self.v_kategoria.get()
        tylko = self.v_tylko_okazje.get()
        sortuj = self.v_sortuj_odl.get()
        if cfg.lokalizacja_odniesienia:
            # geokodowanie = operacja sieciowa -> watek, by okno nie zamarlo
            self._set_running(True)
            self._set_status("Liczenie odleglosci (geokodowanie)...")
            self._append("\n=== Liczenie odleglosci (moze potrwac przy pierwszym razie) ===\n")
            threading.Thread(target=self._raport_worker, args=(cfg, kat, tylko, sortuj),
                             daemon=True).start()
            return
        try:
            tekst = self._zbuduj_raport(cfg, {}, kat, tylko, sortuj)
        except Exception as e:
            messagebox.showerror("Blad", f"Nie udalo sie odczytac bazy: {e}")
            return
        self._set_output(tekst)
        self._linkuj()
        self._podswietl_okazje()
        self._set_status("Raport gotowy.")

    def _zbuduj_raport(self, cfg, odleglosci, kat, tylko, sortuj) -> str:
        db = Database(DB_PATH)
        try:
            rows = fetch_filtered(cfg, db)
        finally:
            db.close()
        return report_mod.render_terminal(
            rows, date.today(), kat, use_color=False,
            prog_okazji=cfg.okazja_prog_procent, tylko_okazje=tylko,
            odleglosci=odleglosci, sortuj_po_odleglosci=sortuj,
        )

    def _raport_worker(self, cfg, kat, tylko, sortuj) -> None:
        try:
            db = Database(DB_PATH)
            try:
                rows = fetch_filtered(cfg, db)
            finally:
                db.close()
            odl = oblicz_odleglosci(cfg, rows, log=lambda m: self._q.put(("log", m)))
            tekst = report_mod.render_terminal(
                rows, date.today(), kat, use_color=False,
                prog_okazji=cfg.okazja_prog_procent, tylko_okazje=tylko,
                odleglosci=odl, sortuj_po_odleglosci=sortuj,
            )
            self._q.put(("report_text", tekst))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    def _eksport_md(self) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        sciezka = filedialog.asksaveasfilename(
            defaultextension=".md", initialfile="raport.md",
            filetypes=[("Markdown", "*.md"), ("Wszystkie pliki", "*.*")],
        )
        if not sciezka:
            return
        db = Database(DB_PATH)
        try:
            rows = fetch_filtered(cfg, db)
        finally:
            db.close()
        odl = oblicz_odleglosci(cfg, rows)  # korzysta z bufora, jesli juz liczone
        md = report_mod.render_markdown(
            rows, date.today(), self.v_kategoria.get(),
            prog_okazji=cfg.okazja_prog_procent, tylko_okazje=self.v_tylko_okazje.get(),
            odleglosci=odl, sortuj_po_odleglosci=self.v_sortuj_odl.get(),
        )
        Path(sciezka).write_text(md, encoding="utf-8")
        self._set_status(f"Raport zapisany: {sciezka}")

    # ---------- pomocnicze ----------
    def _podswietl_okazje(self) -> None:
        start = "1.0"
        while True:
            pos = self.txt.search("[OKAZJA]", start, stopindex="end")
            if not pos:
                break
            koniec = f"{pos}+8c"
            self.txt.tag_add("okazja", pos, koniec)
            start = koniec

    def _linkuj(self) -> None:
        """Zamienia adresy URL w raporcie na klikalne linki (otwiera przegladarke)."""
        self.txt.tag_configure("link", foreground="#4ea1ff", underline=True)
        start = "1.0"
        i = 0
        while True:
            pos = self.txt.search("http", start, stopindex="end")
            if not pos:
                break
            koniec = self.txt.index(f"{pos} lineend")
            url = self.txt.get(pos, koniec).strip()
            tag = f"link-{i}"
            self.txt.tag_add("link", pos, koniec)
            self.txt.tag_add(tag, pos, koniec)
            self.txt.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            self.txt.tag_bind(tag, "<Enter>", lambda e: self.txt.config(cursor="hand2"))
            self.txt.tag_bind(tag, "<Leave>", lambda e: self.txt.config(cursor=""))
            start = koniec
            i += 1

    def _set_running(self, running: bool) -> None:
        stan = "disabled" if running else "normal"
        for b in (self.b_scrape, self.b_scrape_rap, self.b_raport, self.b_zapisz, self.b_eksport):
            b.configure(state=stan)
        if running:
            self._set_status("Scrapowanie w toku...")

    def _set_status(self, txt: str) -> None:
        self.status.configure(text=txt)

    def _append(self, txt: str) -> None:
        self.txt.insert("end", txt)
        self.txt.see("end")

    def _set_output(self, txt: str) -> None:
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", txt)

    @staticmethod
    def _wpisz(entry, value) -> None:
        if value is not None:
            entry.insert(0, str(value))

    @staticmethod
    def _opt_int(entry):
        s = entry.get().strip()
        try:
            return int(float(s.replace(",", "."))) if s else None
        except ValueError:
            return None

    @staticmethod
    def _opt_float(entry):
        s = entry.get().strip()
        try:
            return float(s.replace(",", ".")) if s else None
        except ValueError:
            return None


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
