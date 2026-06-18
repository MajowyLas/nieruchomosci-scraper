# Scraper nieruchomości

Aplikacja konsolowa, która zbiera ogłoszenia sprzedaży mieszkań i domów z kilku
polskich portali i generuje raport z podziałem na **nowe dziś / ostatnie 3 dni /
ostatnie 7 dni / wszystkie**.

Obsługiwane portale:

| Portal | Data dodania na liście? | Uwagi |
|--------|:----:|-------|
| **OLX** | tak (*odświeżenie*) | data oznacza moment odświeżenia oferty, nie dodania |
| **Gratka** | tak | podaje realną datę dodania — najdokładniejsze źródło |
| **nieruchomosci-online.pl** | nie | data liczona od pierwszego wykrycia przez scraper |
| **Tarnowiak.pl** | tak | lokalny portal (region tarnowski) |

## Jak liczone są kategorie „nowe"

Scraper zapisuje każdą ofertę w lokalnej bazie SQLite z datą `first_seen`
(„kiedy zobaczyliśmy ją pierwszy raz"). Jeśli portal podaje datę dodania, używamy
jej; w przeciwnym razie liczymy od momentu pierwszego scrapowania.

> **Ważne:** pierwszy przebieg *zasiewa* bazę — wtedy prawie wszystko trafia do
> „nowe dziś". Kategorie stają się w pełni wiarygodne od kolejnych uruchomień.
> Dlatego scraper najlepiej uruchamiać **regularnie, np. raz dziennie**.

## Wymagania

- Python 3.11 lub nowszy
- Połączenie z internetem

## Instalacja

```powershell
# w katalogu projektu
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Konfiguracja

Parametry wyszukiwania ustawiasz w pliku [`config.yaml`](config.yaml):

```yaml
miasto: tarnow            # slug miasta używany w adresach portali
typy:                     # co scrapować
  - mieszkanie
  - dom
transakcja: sprzedaz
cena_min:                 # puste = bez limitu
cena_max:
portale:                  # zakomentuj (#) te, których nie chcesz
  - olx
  - gratka
  - nieruchomosci-online
  - tarnowiak
max_stron: 3              # ile stron wyników pobrać z każdego portalu
opoznienie: 1.5           # sekundy między zapytaniami (uprzejmość wobec serwerów)
okazja_prog_procent: 85   # próg okazji: cena/m² < 85% mediany (≥15% taniej)
```

## Użycie

```powershell
# 1) Scrapuj portale i zapisz oferty do bazy
python main.py scrape

# 2) Pokaż raport z bazy
python main.py raport                      # domyślnie: wszystkie
python main.py raport --kategoria dzis     # tylko nowe dziś
python main.py raport --kategoria 3dni     # ostatnie 3 dni
python main.py raport --kategoria 7dni     # ostatnie 7 dni

# 3) Scrapuj i od razu pokaż raport (wygodny skrót — działa też bez argumentu)
python main.py
python main.py wszystko --kategoria dzis
```

Opcje raportu:

| Opcja | Opis |
|-------|------|
| `--kategoria {dzis,3dni,7dni,wszystkie}` | która kategoria ma się wyświetlić |
| `--zapisz PLIK` | zapisz raport do pliku Markdown (np. `--zapisz raporty/dzis.md`) |
| `--bez-kolorow` | wyłącz kolory ANSI (przydatne przy zapisie do pliku/logu) |
| `--tylko-okazje` | pokaż wyłącznie oferty oznaczone jako okazja cenowa |

Opcje globalne: `--config ŚCIEŻKA` (inny plik konfiguracji), `--db ŚCIEŻKA` (inna baza).

## Wykrywanie okazji cenowych

Raport oznacza `[OKAZJA]` oferty, których **cena za m² jest wyraźnie niższa od
mediany** dla danego typu (mieszkania i domy liczone osobno). Median używamy
zamiast średniej, bo jest odporna na wartości skrajne. Przy każdej okazji widać,
o ile procent jest tańsza od mediany, a w podsumowaniu wyświetlane są same mediany.

Próg ustawiasz w `config.yaml`:

```yaml
okazja_prog_procent: 85   # okazja = cena/m2 < 85% mediany (czyli ≥15% taniej)
```

Niższa wartość = surowsze kryterium (mniej, ale lepszych okazji). Samą **regułę**
(stały procent / dolny percentyl / odchylenie standardowe) możesz zmienić w funkcji
`czy_okazja()` w pliku [`scraper/report.py`](scraper/report.py).

Aby zobaczyć wyłącznie okazje:

```powershell
python main.py raport --kategoria 7dni --tylko-okazje
```

## Automatyczne uruchamianie raz dziennie (Windows)

Aby kategorie były dokładne, warto scrapować codziennie. Najprościej przez
**Harmonogram zadań** (Task Scheduler):

1. Utwórz plik `scrapuj.bat` w katalogu projektu:
   ```bat
   @echo off
   cd /d "%~dp0"
   .venv\Scripts\python.exe main.py wszystko --kategoria dzis --zapisz raporty\raport-dzis.md --bez-kolorow
   ```
2. W Harmonogramie zadań dodaj nowe zadanie uruchamiające `scrapuj.bat` codziennie rano.

## Struktura projektu

```
scraper/
├── cli.py          # interfejs wiersza poleceń (komendy scrape/raport/wszystko)
├── config.py       # wczytywanie config.yaml
├── http.py         # wspólny klient HTTP (nagłówki, opóźnienia, ponawianie)
├── models.py       # model Listing (jednolite ogłoszenie)
├── parsing.py      # parsowanie ceny, powierzchni, dat (po polsku)
├── storage.py      # baza SQLite + logika first_seen
├── report.py       # kategoryzacja po dacie + wydruk/eksport
└── sites/          # adaptery portali (jeden plik = jeden portal)
    ├── base.py
    ├── olx.py
    ├── gratka.py
    ├── nieruchomosci_online.py
    └── tarnowiak.py
```

## Dodanie nowego portalu

1. Utwórz `scraper/sites/nowy_portal.py` z klasą dziedziczącą po `BaseScraper`.
2. Zaimplementuj `build_url(typ, strona)` oraz `parse_listings(html, typ)`.
3. Dodaj wpis do słownika `SCRAPERS` w `scraper/sites/__init__.py`.

Reszta aplikacji (baza, raport, CLI) zadziała bez żadnych zmian.

## Uwagi

- Scraper czyta publicznie dostępne strony z opóźnieniami między zapytaniami.
  Używaj go z umiarem i do własnych, niekomercyjnych potrzeb; respektuj
  regulaminy portali.
- Portale od czasu do czasu zmieniają strukturę HTML — jeśli któryś adapter
  przestanie zwracać oferty, trzeba zaktualizować selektory w jego pliku.
- Baza danych (`data/`) i raporty (`raporty/`) są ignorowane przez git.
```
