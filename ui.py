#!/usr/bin/env python
"""Aplikacja okienkowa: parametry, scrapowanie, lista ofert + panel szczegolow.

Uruchom:  python ui.py
Opiera sie na tej samej logice co CLI (scraper.cli / scraper.report).
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

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

from scraper.config import Config, load_config
from scraper.storage import Database
from scraper.cli import run_scrape, fetch_filtered, fetch_details, oblicz_odleglosci
from scraper import report as report_mod

CONFIG_PATH = "config.yaml"
DB_PATH = "data/nieruchomosci.db"
PORTALE = ["olx", "gratka", "nieruchomosci-online", "tarnowiak"]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scraper nieruchomosci")
        self.root.geometry("1180x820")
        self._q: queue.Queue = queue.Queue()
        self._then_report = False
        self._oferty: dict[str, dict] = {}      # iid -> wiersz (dict)
        self._also_on: dict = {}
        self._odl: dict = {}
        self._foto_lista: list[str] = []
        self._foto_idx = 0
        self._foto_ref = None                    # referencja na PhotoImage (anty-GC)

        self._build_widgets()
        self._wczytaj_z_config()
        self.root.after(120, self._drain_queue)

    # ================= budowa interfejsu =================
    def _build_widgets(self) -> None:
        top = ttk.Frame(self.root, padding=8)
        top.pack(side="top", fill="x")

        par = ttk.LabelFrame(top, text="Parametry wyszukiwania", padding=8)
        par.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(par, text="Miasto:").grid(row=0, column=0, sticky="w", pady=1)
        self.e_miasto = ttk.Entry(par, width=18)
        self.e_miasto.grid(row=0, column=1, columnspan=3, sticky="w", pady=1)

        ttk.Label(par, text="Rodzaj:").grid(row=1, column=0, sticky="w", pady=1)
        self.v_mieszkanie = tk.BooleanVar(value=True)
        self.v_dom = tk.BooleanVar(value=True)
        ttk.Checkbutton(par, text="mieszkanie", variable=self.v_mieszkanie).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(par, text="dom", variable=self.v_dom).grid(row=1, column=2, sticky="w")

        self.e_cena_min, self.e_cena_max = self._para_pol(par, 2, "Cena [zl]:")
        self.e_pow_min, self.e_pow_max = self._para_pol(par, 3, "Metraz [m2]:")
        self.e_pok_min, self.e_pok_max = self._para_pol(par, 4, "Pokoje:")

        ttk.Label(par, text="Portale:").grid(row=5, column=0, sticky="nw", pady=1)
        self.v_portale = {}
        for i, p in enumerate(PORTALE):
            var = tk.BooleanVar(value=True)
            self.v_portale[p] = var
            ttk.Checkbutton(par, text=p, variable=var).grid(row=5 + i, column=1, columnspan=3, sticky="w")

        ttk.Label(par, text="Max stron:").grid(row=9, column=0, sticky="w", pady=1)
        self.e_max_stron = ttk.Spinbox(par, from_=1, to=20, width=6)
        self.e_max_stron.set(3)
        self.e_max_stron.grid(row=9, column=1, sticky="w")

        ttk.Label(par, text="Prog okazji [%]:").grid(row=10, column=0, sticky="w", pady=1)
        self.e_prog = ttk.Spinbox(par, from_=50, to=100, width=6)
        self.e_prog.set(85)
        self.e_prog.grid(row=10, column=1, sticky="w")

        ttk.Label(par, text="Licz km od:").grid(row=11, column=0, sticky="w", pady=1)
        self.e_lok_ref = ttk.Entry(par, width=22)
        self.e_lok_ref.grid(row=11, column=1, columnspan=4, sticky="w", pady=1)

        ttk.Label(par, text="Max km:").grid(row=12, column=0, sticky="w", pady=1)
        self.e_max_km = ttk.Entry(par, width=6)
        self.e_max_km.grid(row=12, column=1, sticky="w")
        ttk.Label(par, text="(promien od 'Licz km od' / miasta)",
                  foreground="#888").grid(row=12, column=2, columnspan=3, sticky="w")

        rap = ttk.LabelFrame(top, text="Raport", padding=8)
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

        # --- przyciski ---
        btns = ttk.Frame(self.root, padding=(8, 0))
        btns.pack(side="top", fill="x")
        self.b_zapisz = ttk.Button(btns, text="Zapisz parametry", command=self._zapisz_config)
        self.b_scrape = ttk.Button(btns, text="Pobierz swieze dane", command=lambda: self._start_scrape(False))
        self.b_raport = ttk.Button(btns, text="Pokaz raport", command=self._pokaz_raport)
        self.b_detale = ttk.Button(btns, text="Szczegoly + zdjecia", command=self._start_details)
        self.b_eksport = ttk.Button(btns, text="Eksport .md", command=self._eksport_md)
        for b in (self.b_zapisz, self.b_scrape, self.b_raport, self.b_detale, self.b_eksport):
            b.pack(side="left", padx=4, pady=6)

        # --- pasek postepu + status ---
        pasek = ttk.Frame(self.root, padding=(8, 0))
        pasek.pack(side="top", fill="x")
        self.progress = ttk.Progressbar(pasek, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_txt = ttk.Label(pasek, text="", width=10, anchor="e")
        self.progress_txt.pack(side="left", padx=(6, 0))
        self.summary = ttk.Label(self.root, text="", padding=(8, 2), foreground="#555")
        self.summary.pack(side="top", fill="x")

        # --- glowny obszar: tabela ofert + panel szczegolow ---
        pan = ttk.PanedWindow(self.root, orient="horizontal")
        pan.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        lewy = ttk.Frame(pan)
        kolumny = ("cena", "m2", "dzialka", "pokoje", "km", "portal", "data")
        self.tree = ttk.Treeview(lewy, columns=kolumny, show="tree headings", height=20)
        self.tree.heading("#0", text="Oferta")
        self.tree.column("#0", width=320, stretch=True)
        naglowki = {"cena": ("Cena", 90), "m2": ("m2", 55), "dzialka": ("Dzialka", 70),
                    "pokoje": ("Pok.", 45), "km": ("km", 55), "portal": ("Portal", 110),
                    "data": ("Dodano", 90)}
        for k, (t, w) in naglowki.items():
            self.tree.heading(k, text=t)
            self.tree.column(k, width=w, anchor="center")
        self.tree.tag_configure("okazja", foreground="#cc6600")
        ysb = ttk.Scrollbar(lewy, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        pan.add(lewy, weight=3)

        self._build_panel_szczegolow(pan)

        # --- log na dole ---
        logf = ttk.LabelFrame(self.root, text="Log", padding=4)
        logf.pack(side="bottom", fill="x", padx=8, pady=(0, 6))
        self.log = tk.Text(logf, height=6, font=("Consolas", 9), background="#1e1e1e",
                           foreground="#cfcfcf", insertbackground="#cfcfcf")
        logsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=logsb.set)
        logsb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.status = ttk.Label(self.root, text="Gotowe.", anchor="w", relief="sunken", padding=4)
        self.status.pack(side="bottom", fill="x")

    def _build_panel_szczegolow(self, pan) -> None:
        prawy = ttk.Frame(pan, padding=6)
        self.det_title = ttk.Label(prawy, text="Wybierz oferte z listy", font=("", 11, "bold"),
                                   wraplength=380, justify="left")
        self.det_title.pack(anchor="w", fill="x")

        self.foto = ttk.Label(prawy)
        self.foto.pack(anchor="center", pady=6)
        nav = ttk.Frame(prawy)
        nav.pack()
        self.b_prev = ttk.Button(nav, text="◀", width=3, command=lambda: self._zmien_foto(-1))
        self.foto_licznik = ttk.Label(nav, text="")
        self.b_next = ttk.Button(nav, text="▶", width=3, command=lambda: self._zmien_foto(1))
        self.b_prev.pack(side="left"); self.foto_licznik.pack(side="left", padx=8); self.b_next.pack(side="left")

        self.det_info = tk.Text(prawy, height=16, width=44, wrap="word", font=("", 9),
                                background="#f7f7f7", relief="flat")
        self.det_info.pack(fill="both", expand=True, pady=6)
        self.det_info.configure(state="disabled")

        self.b_otworz = ttk.Button(prawy, text="Otworz oferte w przegladarce",
                                   command=self._otworz_oferte, state="disabled")
        self.b_otworz.pack(fill="x")
        self._aktualny_url = None
        pan.add(prawy, weight=2)

    def _para_pol(self, parent, row, etykieta):
        ttk.Label(parent, text=etykieta).grid(row=row, column=0, sticky="w", pady=1)
        e_od = ttk.Entry(parent, width=8)
        e_do = ttk.Entry(parent, width=8)
        ttk.Label(parent, text="od").grid(row=row, column=1, sticky="e")
        e_od.grid(row=row, column=2, sticky="w")
        ttk.Label(parent, text="do").grid(row=row, column=3, sticky="e")
        e_do.grid(row=row, column=4, sticky="w")
        return e_od, e_do

    # ================= config <-> formularz =================
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
        self._wpisz(self.e_max_km, cfg.max_km)

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
        return Config(
            miasto=self.e_miasto.get().strip().lower() or "tarnow",
            typy=typy, transakcja="sprzedaz",
            cena_min=self._opt_int(self.e_cena_min), cena_max=self._opt_int(self.e_cena_max),
            powierzchnia_min=self._opt_float(self.e_pow_min),
            powierzchnia_max=self._opt_float(self.e_pow_max),
            pokoje_min=self._opt_int(self.e_pok_min), pokoje_max=self._opt_int(self.e_pok_max),
            portale=portale, max_stron=self._opt_int(self.e_max_stron) or 3,
            okazja_prog_procent=self._opt_float(self.e_prog) or 85.0,
            lokalizacja_odniesienia=self.e_lok_ref.get().strip() or None,
            max_km=self._opt_float(self.e_max_km),
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
            "portale": cfg.portale, "max_stron": cfg.max_stron, "opoznienie": cfg.opoznienie,
            "okazja_prog_procent": cfg.okazja_prog_procent,
            "lokalizacja_odniesienia": cfg.lokalizacja_odniesienia, "max_km": cfg.max_km,
        }
        Path(CONFIG_PATH).write_text(
            "# Plik wygenerowany przez UI (ui.py). Mozna edytowac recznie.\n"
            + yaml.safe_dump(dane, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._set_status(f"Zapisano parametry do {CONFIG_PATH}")

    # ================= scrapowanie =================
    def _start_scrape(self, _then=False) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        self._set_running(True)
        self._log("=== Scrapowanie rozpoczete (kilkadziesiat sekund) ===")
        threading.Thread(target=self._scrape_worker, args=(cfg,), daemon=True).start()

    def _scrape_worker(self, cfg: Config) -> None:
        try:
            db = Database(DB_PATH)
            try:
                run_scrape(cfg, db, log=lambda m: self._q.put(("log", m)),
                           progress=lambda d, t: self._q.put(("progress", (d, t))))
            finally:
                db.close()
            self._q.put(("done", "Scrapowanie zakonczone."))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    # ================= szczegoly + zdjecia =================
    def _start_details(self) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        self._set_running(True)
        self._log("=== Pobieranie szczegolow i zdjec (1 zapytanie/oferta) ===")
        threading.Thread(target=self._details_worker, args=(cfg,), daemon=True).start()

    def _details_worker(self, cfg: Config) -> None:
        try:
            db = Database(DB_PATH)
            try:
                rows = fetch_filtered(cfg, db)
                fetch_details(cfg, db, rows, log=lambda m: self._q.put(("log", m)),
                              progress=lambda d, t: self._q.put(("progress", (d, t))))
            finally:
                db.close()
            self._q.put(("done_refresh", cfg))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    # ================= raport / lista ofert =================
    def _pokaz_raport(self, cfg: Config | None = None) -> None:
        cfg = cfg or self._build_config()
        if not cfg:
            return
        kat, tylko, sortuj = self.v_kategoria.get(), self.v_tylko_okazje.get(), self.v_sortuj_odl.get()
        self._set_running(True)
        self._set_status("Przygotowuje raport...")
        threading.Thread(target=self._offers_worker, args=(cfg, kat, tylko, sortuj),
                         daemon=True).start()

    def _offers_worker(self, cfg, kat, tylko, sortuj) -> None:
        try:
            db = Database(DB_PATH)
            try:
                rows = [dict(r) for r in fetch_filtered(cfg, db)]
            finally:
                db.close()
            odl = oblicz_odleglosci(cfg, rows, log=lambda m: self._q.put(("log", m)),
                                    progress=lambda d, t: self._q.put(("progress", (d, t))))
            rows = report_mod.filtruj_po_km(rows, odl, cfg.max_km)
            rows, also_on = report_mod.deduplikuj(rows)
            liczby = report_mod.policz_kategorie(rows, date.today())
            wybrane, mediany = report_mod.wybierz_oferty(
                rows, date.today(), kat, tylko, cfg.okazja_prog_procent, odl, sortuj)
            self._q.put(("offers", (wybrane, also_on, odl, mediany, liczby)))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    def _populate_tree(self, wybrane, also_on, odl, mediany, liczby) -> None:
        self.tree.delete(*self.tree.get_children())
        self._oferty.clear()
        self._also_on, self._odl = also_on, odl
        prog = self._opt_float(self.e_prog) or 85.0
        for r in wybrane:
            iid = f"{r['site']}|{r['listing_id']}"
            self._oferty[iid] = r
            km = odl.get((r["site"], r["listing_id"]))
            okazja = report_mod.czy_okazja(r, mediany, prog)
            wartosci = (
                self._cena(r["price"]),
                f"{r['area']:g}" if r["area"] else "",
                f"{round(r['plot_area'])}" if r.get("plot_area") else "",
                r["rooms"] or "",
                f"{km:.1f}" if km is not None else "",
                r["site"],
                (r["site_date"] or (r["first_seen"] or "")[:10]),
            )
            tagi = ("okazja",) if okazja else ()
            self.tree.insert("", "end", iid=iid, text=(r["title"] or "")[:80],
                             values=wartosci, tags=tagi)
        n = ", ".join(f"{report_mod.NAZWY[k]}: {liczby[k]}" for k in report_mod.KATEGORIE)
        self.summary.configure(text=f"{n}   |   pokazano: {len(wybrane)}")
        self._set_status(f"Raport gotowy: {len(wybrane)} ofert.")

    # ================= panel szczegolow =================
    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        r = self._oferty.get(sel[0])
        if not r:
            return
        self._aktualny_url = r["url"]
        self.b_otworz.configure(state="normal")
        self.det_title.configure(text=r["title"] or "(bez tytulu)")

        linie = []
        linie.append(f"Cena:        {self._cena(r['price'])}")
        if r["area"]:
            linie.append(f"Metraz:      {r['area']:g} m2")
        if r.get("plot_area"):
            linie.append(f"Dzialka:     {round(r['plot_area'])} m2")
        if r["rooms"]:
            linie.append(f"Pokoje:      {r['rooms']}")
        if r.get("floor"):
            linie.append(f"Pietro:      {r['floor']}")
        if r.get("year_built"):
            linie.append(f"Rok budowy:  {r['year_built']}")
        if r["price"] and r["area"]:
            linie.append(f"Cena/m2:     {round(r['price']/r['area']):,} zl".replace(",", " "))
        linie.append(f"Lokalizacja: {r['location']}")
        km = self._odl.get((r["site"], r["listing_id"]))
        if km is not None:
            linie.append(f"Odleglosc:   ~{km:.1f} km")
        linie.append(f"Portal:      {r['site']}")
        tez = self._also_on.get((r["site"], r["listing_id"]))
        if tez:
            linie.append(f"Takze na:    {', '.join(tez)}")
        if r.get("description"):
            linie.append("")
            linie.append(r["description"])

        self.det_info.configure(state="normal")
        self.det_info.delete("1.0", "end")
        self.det_info.insert("1.0", "\n".join(linie))
        self.det_info.configure(state="disabled")

        self._foto_lista = self._znajdz_zdjecia(r)
        self._foto_idx = 0
        self._pokaz_foto()

    def _znajdz_zdjecia(self, r) -> list[str]:
        d = r.get("photos_dir")
        if d and Path(d).exists():
            return sorted(str(p) for p in Path(d).glob("*.jpg"))
        return []

    def _pokaz_foto(self) -> None:
        if not PIL_OK or not self._foto_lista:
            self.foto.configure(image="", text="(brak zdjec - kliknij 'Szczegoly + zdjecia')")
            self._foto_ref = None
            self.foto_licznik.configure(text="")
            return
        try:
            img = Image.open(self._foto_lista[self._foto_idx])
            img.thumbnail((380, 280))
            self._foto_ref = ImageTk.PhotoImage(img)
            self.foto.configure(image=self._foto_ref, text="")
            self.foto_licznik.configure(text=f"{self._foto_idx + 1}/{len(self._foto_lista)}")
        except Exception:
            self.foto.configure(image="", text="(nie udalo sie wczytac zdjecia)")
            self._foto_ref = None

    def _zmien_foto(self, delta: int) -> None:
        if not self._foto_lista:
            return
        self._foto_idx = (self._foto_idx + delta) % len(self._foto_lista)
        self._pokaz_foto()

    def _otworz_oferte(self) -> None:
        if self._aktualny_url:
            webbrowser.open(self._aktualny_url)

    def _eksport_md(self) -> None:
        cfg = self._build_config()
        if not cfg:
            return
        sciezka = filedialog.asksaveasfilename(defaultextension=".md", initialfile="raport.md",
                                               filetypes=[("Markdown", "*.md")])
        if not sciezka:
            return
        db = Database(DB_PATH)
        try:
            rows = [dict(r) for r in fetch_filtered(cfg, db)]
        finally:
            db.close()
        odl = oblicz_odleglosci(cfg, rows)
        rows = report_mod.filtruj_po_km(rows, odl, cfg.max_km)
        rows, _ = report_mod.deduplikuj(rows)
        md = report_mod.render_markdown(rows, date.today(), self.v_kategoria.get(),
                                        prog_okazji=cfg.okazja_prog_procent,
                                        tylko_okazje=self.v_tylko_okazje.get(),
                                        odleglosci=odl, sortuj_po_odleglosci=self.v_sortuj_odl.get())
        Path(sciezka).write_text(md, encoding="utf-8")
        self._set_status(f"Raport zapisany: {sciezka}")

    # ================= petla komunikatow =================
    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "progress":
                    self._ustaw_postep(*payload)
                elif kind == "offers":
                    self._populate_tree(*payload)
                    self._set_running(False)
                elif kind == "done":
                    self._log(str(payload))
                    self._set_running(False)
                    self._set_status(str(payload))
                elif kind == "done_refresh":
                    self._log("Pobrano szczegoly. Odswiezam liste...")
                    self._set_running(False)
                    self._pokaz_raport(cfg=payload)
                elif kind == "error":
                    self._log("BLAD: " + str(payload))
                    self._set_running(False)
                    self._set_status("Wystapil blad.")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    # ================= pomocnicze =================
    def _set_running(self, running: bool) -> None:
        for b in (self.b_scrape, self.b_raport, self.b_detale, self.b_zapisz, self.b_eksport):
            b.configure(state="disabled" if running else "normal")
        if running:
            self.progress.configure(value=0)
            self.progress_txt.configure(text="")

    def _ustaw_postep(self, done: int, total: int) -> None:
        total = max(total, 1)
        self.progress.configure(maximum=total, value=done)
        self.progress_txt.configure(text=f"{done}/{total}")

    def _set_status(self, txt: str) -> None:
        self.status.configure(text=txt)

    def _log(self, txt: str) -> None:
        self.log.insert("end", txt + "\n")
        self.log.see("end")

    @staticmethod
    def _cena(v) -> str:
        if not v:
            return "do uzgodnienia"
        return f"{v:,}".replace(",", " ") + " zl"

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
