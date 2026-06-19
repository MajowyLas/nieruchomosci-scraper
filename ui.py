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

try:
    import tkintermapview
    MAP_OK = True
except ImportError:
    MAP_OK = False

TARNOW = (50.0123, 20.9881)  # srodek Tarnowa - domyslny widok mapy

import requests

from scraper.config import Config, load_config
from scraper.storage import Database
from scraper.cli import (run_scrape, fetch_filtered, fetch_details, oblicz_odleglosci,
                         oblicz_odleglosci_i_wsp)
from scraper.detail import extract_detail, pobierz_zdjecia
from scraper.http import _DEFAULT_HEADERS
from scraper import report as report_mod

CONFIG_PATH = "config.yaml"
DB_PATH = "data/nieruchomosci.db"
PORTALE = ["olx", "otodom", "gratka", "nieruchomosci-online", "tarnowiak"]


class Tooltip:
    """Prosty dymek z podpowiedzia pokazywany po najechaniu na widget."""

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self._after = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _evt=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, font=("", 9), padx=6, pady=3,
                 wraplength=340).pack()

    def _hide(self, _evt=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Scraper nieruchomosci")
        self.root.geometry("1180x820")
        self._q: queue.Queue = queue.Queue()
        self._gen = 0                            # token zapytania (anty-wyscig)
        self._abort = threading.Event()          # flaga przerwania operacji
        self._fetching_detale: set[str] = set()  # iid ofert aktualnie doszczegolawianych
        self._oferty: dict[str, dict] = {}      # iid (widoczne) -> wiersz (dict)
        self._wszystkie: list[dict] = []         # pelna lista przed filtrami wynikow
        self._mediany: dict = {}
        self._liczby: dict = {}
        self._also_on: dict = {}
        self._odl: dict = {}
        self._coords: dict = {}                  # (site,id) -> (lat,lon) dla mapy
        self._map_gen = -1                       # dla ktorego zapytania mapa jest aktualna
        self._foto_lista: list[str] = []
        self._foto_idx = 0
        self._foto_ref = None                    # referencja na PhotoImage (anty-GC)

        self._build_widgets()
        self._wczytaj_z_config()
        self.root.after(120, self._drain_queue)
        self.root.after(250, self._pokaz_raport)  # pokaz oferty z bazy od razu po starcie

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

        w = 5 + len(PORTALE)   # pierwszy wolny wiersz pod lista portali
        ttk.Label(par, text="Max stron:").grid(row=w, column=0, sticky="w", pady=1)
        self.e_max_stron = ttk.Spinbox(par, from_=1, to=20, width=6)
        self.e_max_stron.set(3)
        self.e_max_stron.grid(row=w, column=1, sticky="w")

        ttk.Label(par, text="Prog okazji [%]:").grid(row=w + 1, column=0, sticky="w", pady=1)
        self.e_prog = ttk.Spinbox(par, from_=50, to=100, width=6)
        self.e_prog.set(85)
        self.e_prog.grid(row=w + 1, column=1, sticky="w")

        ttk.Label(par, text="Licz km od:").grid(row=w + 2, column=0, sticky="w", pady=1)
        self.e_lok_ref = ttk.Entry(par, width=22)
        self.e_lok_ref.grid(row=w + 2, column=1, columnspan=4, sticky="w", pady=1)

        ttk.Label(par, text="Max km:").grid(row=w + 3, column=0, sticky="w", pady=1)
        self.e_max_km = ttk.Entry(par, width=6)
        self.e_max_km.grid(row=w + 3, column=1, sticky="w")
        ttk.Label(par, text="(promien od 'Licz km od' / miasta)",
                  foreground="#888").grid(row=w + 3, column=2, columnspan=3, sticky="w")

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

        # --- przyciski akcji: dwa glowne + reszta z boku ---
        akcje = ttk.Frame(self.root, padding=(8, 2))
        akcje.pack(side="top", fill="x")
        btns = ttk.Frame(akcje)
        btns.pack(fill="x")
        self.b_scrape = ttk.Button(btns, text="Pobierz dane z portali",
                                   command=lambda: self._start_scrape(False))
        self.b_raport = ttk.Button(btns, text="Pokaz oferty", command=self._pokaz_raport)
        self.b_otworz_top = ttk.Button(btns, text="Otworz oferte w przegladarce",
                                       command=self._otworz_oferte)
        self.b_scrape.pack(side="left", padx=(0, 4), pady=4)
        self.b_raport.pack(side="left", padx=4, pady=4)
        self.b_otworz_top.pack(side="left", padx=4, pady=4)
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=12, pady=4)
        self.b_detale = ttk.Button(btns, text="Dociagnij zdjecia (wszystkie)", command=self._start_details)
        self.b_zapisz = ttk.Button(btns, text="Zapisz ustawienia", command=self._zapisz_config)
        self.b_eksport = ttk.Button(btns, text="Eksport", command=self._eksport_md)
        for b in (self.b_detale, self.b_zapisz, self.b_eksport):
            b.pack(side="left", padx=3, pady=4)
        self.b_anuluj = ttk.Button(btns, text="Anuluj", command=self._anuluj, state="disabled")
        self.b_anuluj.pack(side="right", padx=3, pady=4)
        ttk.Label(
            akcje,
            text="Ustaw filtry po lewej, potem: Pobierz dane (z internetu, rzadko) → Pokaz oferty "
                 "(z bazy, szybko). Zdjecia oferty dociagaja sie po jej kliknięciu.",
            foreground="#777",
        ).pack(anchor="w", pady=(2, 0))

        Tooltip(self.b_scrape, "Pobiera AKTUALNE oferty z portali (przez internet) i zapisuje do bazy. "
                               "Wolniejsze - rob, gdy chcesz odswiezyc dane (np. raz dziennie).")
        Tooltip(self.b_raport, "Pokazuje oferty z juz pobranych danych wg filtrow. Szybkie - "
                               "klikaj po kazdej zmianie parametrow. Odleglosci dolicza sie w tle.")
        Tooltip(self.b_detale, "Z gory pobiera zdjecia i opisy dla WSZYSTKICH ofert po filtrach. "
                               "Opcjonalne - i tak dociagaja sie pojedynczo po kliknieciu oferty.")
        Tooltip(self.b_zapisz, "Zapisuje biezace ustawienia formularza do pliku config.yaml.")
        Tooltip(self.b_eksport, "Zapisuje liste ofert do pliku Markdown (.md).")

        # --- pasek postepu + status ---
        pasek = ttk.Frame(self.root, padding=(8, 0))
        pasek.pack(side="top", fill="x")
        self.progress = ttk.Progressbar(pasek, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_txt = ttk.Label(pasek, text="", width=10, anchor="e")
        self.progress_txt.pack(side="left", padx=(6, 0))
        self.summary = ttk.Label(self.root, text="", padding=(8, 2), foreground="#555")
        self.summary.pack(side="top", fill="x")

        # --- filtry wynikow (dzialaja natychmiast, bez ponownego pobierania) ---
        flt = ttk.Frame(self.root, padding=(8, 0))
        flt.pack(side="top", fill="x")
        ttk.Label(flt, text="Filtruj wyniki:").pack(side="left")
        self.f_typ = tk.StringVar(value="wszystkie")
        self.f_rynek = tk.StringVar(value="wszystkie")
        self.f_stan = tk.StringVar(value="wszystkie")
        self.f_fav = tk.BooleanVar(value=False)
        for etykieta, var, wartosci in (
            ("Typ", self.f_typ, ["wszystkie", "mieszkanie", "dom"]),
            ("Rynek", self.f_rynek, ["wszystkie", "pierwotny", "wtorny"]),
            ("Stan", self.f_stan, ["wszystkie", "do wejscia", "deweloperski", "do remontu"]),
        ):
            ttk.Label(flt, text=etykieta + ":").pack(side="left", padx=(10, 2))
            cb = ttk.Combobox(flt, textvariable=var, values=wartosci, state="readonly", width=12)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self._odswiez_tabele())
        ttk.Checkbutton(flt, text="tylko ulubione ★", variable=self.f_fav,
                        command=self._odswiez_tabele).pack(side="left", padx=(12, 0))

        # --- zakladki: Lista + Mapa ---
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        tab_lista = ttk.Frame(self.nb)
        self.nb.add(tab_lista, text="Lista")
        pan = ttk.PanedWindow(tab_lista, orient="horizontal")
        pan.pack(fill="both", expand=True)

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
        self.tree.bind("<Double-1>", lambda e: self._otworz_oferte())  # 2x klik = otworz oferte
        pan.add(lewy, weight=3)

        self._build_panel_szczegolow(pan)

        # zakladka Mapa
        tab_mapa = ttk.Frame(self.nb)
        self.nb.add(tab_mapa, text="Mapa")
        if MAP_OK:
            self.map_widget = tkintermapview.TkinterMapView(tab_mapa, corner_radius=0)
            self.map_widget.pack(fill="both", expand=True)
            self.map_widget.set_position(*TARNOW)
            self.map_widget.set_zoom(11)
        else:
            self.map_widget = None
            ttk.Label(tab_mapa, text="Mapa niedostepna - zainstaluj: pip install tkintermapview").pack(pady=20)
        self.nb.bind("<<NotebookTabChanged>>", self._tab_zmieniona)

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

        # przyciski akcji NA GORZE panelu - zawsze widoczne (nie chowaja sie na dole)
        akcje_of = ttk.Frame(prawy)
        akcje_of.pack(fill="x", pady=4)
        self.b_otworz = ttk.Button(akcje_of, text="Otworz w przegladarce",
                                   command=self._otworz_oferte)
        self.b_fav = ttk.Button(akcje_of, text="☆ Ulubione", command=self._toggle_fav, state="disabled")
        self.b_otworz.pack(side="left", padx=(0, 4))
        self.b_fav.pack(side="left")

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
                           progress=lambda d, t: self._q.put(("progress", (d, t))),
                           stop=self._abort.is_set)
            finally:
                db.close()
            self._q.put(("done_refresh", cfg))   # po pobraniu od razu pokaz liste
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
                              progress=lambda d, t: self._q.put(("progress", (d, t))),
                              stop=self._abort.is_set)
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
        self._gen += 1                       # token: ignorujemy wyniki starych zapytan
        self._set_running(True)
        self._set_status("Przygotowuje liste...")
        threading.Thread(target=self._offers_worker, args=(self._gen, cfg, kat, tylko, sortuj),
                         daemon=True).start()

    def _offers_worker(self, gen, cfg, kat, tylko, sortuj) -> None:
        try:
            db = Database(DB_PATH)
            try:
                rows = [dict(r) for r in fetch_filtered(cfg, db)]
            finally:
                db.close()
            dzis = date.today()
            liczby = report_mod.policz_kategorie(rows, dzis)
            # 1) NATYCHMIAST pokaz oferty bez odleglosci - okno nie czeka na geokodowanie
            r0, also0 = report_mod.deduplikuj(rows)
            wyb0, med0 = report_mod.wybierz_oferty(r0, dzis, kat, tylko, cfg.okazja_prog_procent, {}, False)
            self._q.put(("offers", (gen, wyb0, also0, {}, med0, liczby)))
            self._q.put(("enable", gen))     # lista widoczna, glowne przyciski aktywne
            # 2) jesli trzeba - policz odleglosci w TLE i odswiez liste
            if cfg.lokalizacja_odniesienia or cfg.max_km:
                self._q.put(("log", "Licze odleglosci w tle (lista juz widoczna)..."))
                okno = report_mod.tylko_w_oknie(rows, dzis, kat)
                odl, coords, _ref = oblicz_odleglosci_i_wsp(
                    cfg, okno, log=lambda m: self._q.put(("log", m)),
                    progress=lambda d, t: self._q.put(("progress", (d, t))),
                    stop=self._abort.is_set)
                self._q.put(("coords", (gen, coords)))    # wspolrzedne dla mapy
                r2 = report_mod.filtruj_po_km(rows, odl, cfg.max_km)
                r2, also2 = report_mod.deduplikuj(r2)
                wyb2, med2 = report_mod.wybierz_oferty(r2, dzis, kat, tylko, cfg.okazja_prog_procent,
                                                       odl, sortuj)
                self._q.put(("offers", (gen, wyb2, also2, odl, med2, liczby)))
            self._q.put(("fin", gen))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    def _populate_tree(self, wybrane, also_on, odl, mediany, liczby) -> None:
        """Zapamietuje pelny wynik i rysuje tabele (z filtrami wynikow)."""
        self._wszystkie = wybrane
        self._also_on, self._odl, self._mediany, self._liczby = also_on, odl, mediany, liczby
        self._odswiez_tabele()

    def _filtr_wynikow(self, r) -> bool:
        """Czy oferta przechodzi filtry wynikow (typ/rynek/stan/ulubione)?"""
        if self.f_typ.get() != "wszystkie" and r["property_type"] != self.f_typ.get():
            return False
        if self.f_rynek.get() != "wszystkie" and report_mod.wykryj_rynek(r) != self.f_rynek.get():
            return False
        if self.f_stan.get() != "wszystkie" and report_mod.wykryj_stan(r) != self.f_stan.get():
            return False
        if self.f_fav.get() and not r.get("favorite"):
            return False
        return True

    def _odswiez_tabele(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._oferty.clear()
        prog = self._opt_float(self.e_prog) or 85.0
        pokazane = 0
        for r in self._wszystkie:
            if not self._filtr_wynikow(r):
                continue
            iid = f"{r['site']}|{r['listing_id']}"
            self._oferty[iid] = r
            km = self._odl.get((r["site"], r["listing_id"]))
            tagi = ("okazja",) if report_mod.czy_okazja(r, self._mediany, prog) else ()
            wartosci = (
                self._cena(r["price"]),
                f"{r['area']:g}" if r["area"] else "",
                f"{round(r['plot_area'])}" if r.get("plot_area") else "",
                r["rooms"] or "",
                f"{km:.1f}" if km is not None else "",
                r["site"],
                (r["site_date"] or (r["first_seen"] or "")[:10]),
            )
            gwiazdka = "★ " if r.get("favorite") else ""
            self.tree.insert("", "end", iid=iid, text=gwiazdka + (r["title"] or "")[:80],
                             values=wartosci, tags=tagi)
            pokazane += 1
        n = ", ".join(f"{report_mod.NAZWY[k]}: {self._liczby.get(k, 0)}" for k in report_mod.KATEGORIE)
        self.summary.configure(text=f"{n}   |   pokazano: {pokazane}")
        self._set_status(f"Pokazano {pokazane} ofert.")

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
        self.b_fav.configure(state="normal",
                             text="★ Ulubiona" if r.get("favorite") else "☆ Do ulubionych")
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

        # zdjecia/opis na zadanie: jesli oferta nie byla jeszcze poglebiona, dociagnij ja w tle
        iid = f"{r['site']}|{r['listing_id']}"
        if not r.get("detail_fetched") and iid not in self._fetching_detale:
            self._fetching_detale.add(iid)
            self.foto.configure(image="", text="(pobieram zdjecia...)")
            threading.Thread(target=self._one_detail_worker, args=(iid, dict(r)), daemon=True).start()

    def _one_detail_worker(self, iid: str, r: dict) -> None:
        try:
            sess = requests.Session()
            sess.headers.update(_DEFAULT_HEADERS)
            resp = sess.get(r["url"], timeout=25)
            if resp.status_code != 200:
                self._q.put(("one_detail", (iid, None)))
                return
            det = extract_detail(resp.text, r["site"], r["url"])
            if det["image_urls"]:
                dest = Path("data/photos") / f"{r['site']}_{r['listing_id']}"
                pobierz_zdjecia(det["image_urls"], dest, session=sess)
                det["photos_dir"] = str(dest)
            db = Database(DB_PATH)
            try:
                db.update_detail(r["site"], r["listing_id"], det)
            finally:
                db.close()
            self._q.put(("one_detail", (iid, det)))
        except Exception as e:
            self._q.put(("log", f"Szczegoly oferty: {type(e).__name__}: {e}"))
            self._q.put(("one_detail", (iid, None)))

    def _zaktualizuj_detal(self, iid: str, det) -> None:
        self._fetching_detale.discard(iid)
        r = self._oferty.get(iid)
        if r is None:
            return
        r["detail_fetched"] = 1
        if det:
            for pole in ("plot_area", "floor", "year_built", "description", "photos_dir"):
                r[pole] = det.get(pole)
            if self.tree.exists(iid) and det.get("plot_area"):
                self.tree.set(iid, "dzialka", str(round(det["plot_area"])))
        sel = self.tree.selection()
        if sel and sel[0] == iid:      # odswiez panel, jesli oferta nadal zaznaczona
            self._on_select()

    def _znajdz_zdjecia(self, r) -> list[str]:
        d = r.get("photos_dir")
        if d and Path(d).exists():
            return sorted(str(p) for p in Path(d).glob("*.jpg"))
        return []

    def _pokaz_foto(self) -> None:
        if not PIL_OK or not self._foto_lista:
            self.foto.configure(image="", text="(brak zdjec dla tej oferty)")
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
        url = self._aktualny_url
        if not url:  # nic nie kliknieto wczesniej - wez z biezacego zaznaczenia
            sel = self.tree.selection()
            if sel:
                r = self._oferty.get(sel[0])
                url = r.get("url") if r else None
        if url:
            webbrowser.open(url)
        else:
            messagebox.showinfo("Oferta", "Najpierw zaznacz oferte na liscie (kliknij wiersz).")

    # ================= mapa =================
    def _na_mapie(self) -> bool:
        return bool(self.map_widget) and self.nb.index(self.nb.select()) == 1

    def _tab_zmieniona(self, _evt=None) -> None:
        if not self._na_mapie():
            return
        if self._map_gen == self._gen and self._coords:
            self._ustaw_markery()
        elif self._oferty:
            cfg = self._build_config()
            if not cfg:
                return
            self._set_status("Wczytuje mape (geokodowanie w tle)...")
            threading.Thread(target=self._map_worker,
                             args=(self._gen, list(self._oferty.values()), cfg), daemon=True).start()

    def _map_worker(self, gen, rows, cfg) -> None:
        try:
            _km, coords, _ref = oblicz_odleglosci_i_wsp(
                cfg, rows, log=lambda m: self._q.put(("log", m)),
                progress=lambda d, t: self._q.put(("progress", (d, t))), stop=self._abort.is_set)
            self._q.put(("map_points", (gen, coords)))
        except Exception as e:
            self._q.put(("log", f"Mapa: {type(e).__name__}: {e}"))

    def _ustaw_markery(self) -> None:
        if not self.map_widget:
            return
        self.map_widget.delete_all_marker()
        laty, lony = [], []
        for (site, lid), (la, lo) in self._coords.items():
            r = self._oferty.get(f"{site}|{lid}")
            if not r:
                continue
            tekst = f"{self._cena(r['price'])} - {(r['title'] or '')[:24]}"
            self.map_widget.set_marker(la, lo, text=tekst,
                                       command=lambda marker, i=f"{site}|{lid}": self._marker_klik(i))
            laty.append(la)
            lony.append(lo)
        if laty:
            try:
                self.map_widget.fit_bounding_box((max(laty), min(lony)), (min(laty), max(lony)))
            except Exception:
                pass
        self._set_status(f"Mapa: {len(laty)} ofert z lokalizacja.")

    def _marker_klik(self, iid: str) -> None:
        self.nb.select(0)  # wroc na liste
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self._on_select()

    def _toggle_fav(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        r = self._oferty.get(sel[0])
        if not r:
            return
        nowy = 0 if r.get("favorite") else 1
        r["favorite"] = nowy
        db = Database(DB_PATH)
        try:
            db.set_favorite(r["site"], r["listing_id"], bool(nowy))
        finally:
            db.close()
        self.b_fav.configure(text="★ Ulubiona" if nowy else "☆ Do ulubionych")
        # odswiez gwiazdke w wierszu (lub usun wiersz, gdy aktywny filtr 'tylko ulubione')
        if self.f_fav.get() and not nowy:
            self._odswiez_tabele()
        elif self.tree.exists(sel[0]):
            self.tree.item(sel[0], text=("★ " if nowy else "") + (r["title"] or "")[:80])

    def _anuluj(self) -> None:
        self._abort.set()
        self._log("Przerywanie... (czekam na zakonczenie biezacych zapytan)")
        self._set_status("Przerywanie...")

    def _eksport_md(self) -> None:
        if not self._wszystkie:
            messagebox.showinfo("Eksport", "Najpierw kliknij 'Pokaz oferty'.")
            return
        sciezka = filedialog.asksaveasfilename(defaultextension=".md", initialfile="raport.md",
                                               filetypes=[("Markdown", "*.md")])
        if not sciezka:
            return
        # eksportujemy to, co aktualnie widac (z filtrami wynikow), bez ponownego geokodowania
        widoczne = [r for r in self._wszystkie if self._filtr_wynikow(r)]
        md = report_mod.render_markdown(
            widoczne, date.today(), self.v_kategoria.get(),
            prog_okazji=self._opt_float(self.e_prog) or 85.0,
            tylko_okazje=self.v_tylko_okazje.get(),
            odleglosci=self._odl, sortuj_po_odleglosci=self.v_sortuj_odl.get())
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
                    gen, *reszta = payload
                    if gen == self._gen:                 # ignoruj wyniki starych zapytan
                        self._populate_tree(*reszta)
                elif kind == "enable":
                    if payload == self._gen:   # tylko biezace zapytanie
                        self._wlacz_glowne()   # lista widoczna; Anuluj zostaje (geo w tle)
                elif kind == "fin":
                    if payload == self._gen:
                        self._set_running(False)
                elif kind in ("coords", "map_points"):
                    gen, coords = payload
                    if gen == self._gen:
                        self._coords = coords
                        self._map_gen = gen
                        if self._na_mapie():
                            self._ustaw_markery()
                elif kind == "one_detail":
                    self._zaktualizuj_detal(*payload)
                elif kind == "done":
                    self._log(str(payload))
                    self._set_running(False)
                    self._set_status(str(payload))
                elif kind == "done_refresh":
                    self._log("Gotowe. Odswiezam liste ofert...")
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
    _GLOWNE = ("b_scrape", "b_raport", "b_detale", "b_zapisz", "b_eksport")

    def _set_running(self, running: bool) -> None:
        for nazwa in self._GLOWNE:
            getattr(self, nazwa).configure(state="disabled" if running else "normal")
        self.b_anuluj.configure(state="normal" if running else "disabled")
        if running:
            self._abort.clear()
            self.progress.configure(value=0)
            self.progress_txt.configure(text="")

    def _wlacz_glowne(self) -> None:
        """Odblokowuje glowne przyciski, ale zostawia Anuluj (cos moze isc w tle)."""
        for nazwa in self._GLOWNE:
            getattr(self, nazwa).configure(state="normal")

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
