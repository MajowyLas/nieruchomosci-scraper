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
cena_min:                 # puste = bez limitu (zł)
cena_max:
powierzchnia_min:         # metraż użytkowy w m² (puste = bez limitu)
powierzchnia_max:
pokoje_min:               # liczba pokoi (puste = bez limitu)
pokoje_max:
portale:                  # zakomentuj (#) te, których nie chcesz
  - olx
  - gratka
  - nieruchomosci-online
  - tarnowiak
max_stron: 3              # ile stron wyników pobrać z każdego portalu
opoznienie: 1.5           # sekundy między zapytaniami (uprzejmość wobec serwerów)
okazja_prog_procent: 85   # próg okazji: cena/m² < 85% mediany (≥15% taniej)
lokalizacja_odniesienia:  # adres/miasto do liczenia km (puste = od miasta)
max_km:                   # promień w km od punktu odniesienia (puste = bez limitu)
```

### Parametry wyszukiwania

| Parametr | Znaczenie |
|----------|-----------|
| `typy` | rodzaj nieruchomości: `mieszkanie` i/lub `dom` |
| `cena_min` / `cena_max` | widełki ceny w zł |
| `powierzchnia_min` / `powierzchnia_max` | metraż użytkowy w m² |
| `pokoje_min` / `pokoje_max` | liczba pokoi |
| `lokalizacja_odniesienia` | adres/miasto, od którego liczona jest odległość ofert (w km) |
| `max_km` | maksymalny promień w km — odrzuca oferty dalej od punktu odniesienia |

Filtry metrażu, pokoi i ceny są stosowane **na etapie raportu** — możesz je zmienić
w `config.yaml` i od razu uruchomić raport ponownie, **bez ponownego scrapowania**
(baza przechowuje pełny zrzut rynku). Oferta, w której portal **nie podał** danej
cechy (np. brak liczby pokoi), nie jest odrzucana — żeby nie zgubić trafnych
ogłoszeń z niekompletnymi danymi.

## Najprościej: okno (UI)

Jeśli wolisz klikać zamiast pisać w terminalu, uruchom graficzny interfejs:

```powershell
python ui.py
```

W oknie ustawiasz parametry (miasto, rodzaj, cena, metraż, pokoje, portale, promień km),
po lewej widzisz **tabelę ofert**, a po kliknięciu wiersza — **panel szczegółów ze
zdjęciem** (miniatura, przewijanie strzałkami ◀ ▶, przycisk „Otwórz w przeglądarce").
U góry pasek postępu pokazuje, że coś się dzieje, a na dole jest log.

Przyciski:

- **Zapisz parametry** — zapisuje ustawienia do `config.yaml`
- **Pobierz świeże dane** — scrapuje portale (postęp na pasku i w logu)
- **Pokaż raport** — buduje listę ofert z bazy (z filtrami, odległościami, dedup)
- **Szczegóły + zdjęcia** — pogłębia oferty po filtrach: wchodzi na ich podstrony i
  pobiera m² działki, rok, piętro, opis i zdjęcia (wolne — 1 zapytanie na ofertę)
- **Eksport .md** — zapis raportu do pliku Markdown

Okazje są wyróżnione kolorem. Pole **„Licz km od"** + **„Max km"** pozwala podać
punkt odniesienia i promień — oferty dalej niż X km znikają, a w tabeli widać `km`.
Aby uruchomić okno bez okienka konsoli w tle, użyj `pythonw ui.py` (możesz zrobić do
tego skrót na pulpicie).

## Użycie z terminala

```powershell
# 1) Scrapuj portale i zapisz oferty do bazy
python main.py scrape

# 1b) Pogłęb oferty po filtrach (podstrony: działka, rok, opis, zdjęcia)
python main.py detale

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
| `--sortuj-odleglosc` | sortuj wg odległości (wymaga `lokalizacja_odniesienia` w config) |

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

## Odległość od wybranej lokalizacji

Po ustawieniu `lokalizacja_odniesienia` (w `config.yaml` lub w polu „Licz km od"
w oknie) raport pokazuje przy każdej ofercie przybliżoną odległość `~X km` od tego
punktu, a opcja „sortuj wg odległości" / `--sortuj-odleglosc` układa oferty od
najbliższych.

Współrzędne są ustalane przez geokodowanie (OpenStreetMap **Nominatim**, darmowe,
bez klucza). Kilka uwag:

- Wyniki są **buforowane** w `data/geocache.db`, więc to samo miejsce nie jest
  pytane dwa razy — pierwszy raport z odległościami trwa dłużej, kolejne są szybkie.
- Lokalizacje ofert bywają zgrubne (dzielnica/miasto), więc odległość jest
  **przybliżona** — najlepiej sprawdza się do odróżnienia ofert „w mieście" od tych
  w okolicznych miejscowościach.
- Wymaga połączenia z internetem (tak jak samo scrapowanie).

## Szczegóły ofert i zdjęcia

Listy wyników dają podstawy (cena, metraż, lokalizacja). Komenda **`detale`** (lub
przycisk **„Szczegóły + zdjęcia"** w oknie) wchodzi na podstronę każdej oferty
**pasującej do filtrów** i dociąga:

- **powierzchnię działki** (m²) — kluczowe przy domach,
- rok budowy, piętro, skrócony opis,
- **zdjęcia** — zapisywane do `data/photos/<portal>_<id>/`.

To operacja kosztowna (1 zapytanie na ofertę), dlatego robimy ją tylko dla ofert po
filtrach i **buforujemy** — raz pogłębiona oferta nie jest pobierana ponownie.
Miniatury w oknie wymagają biblioteki **Pillow** (instalowana z `requirements.txt`).

## Deduplikacja

Ta sama nieruchomość bywa wystawiona na kilku portalach naraz. Raport **scala takie
duplikaty** (po identycznym typie, metrażu i cenie) w jedną pozycję i dopisuje, na
jakich innych portalach też się pojawia (np. „także na: gratka").

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
main.py             # punkt wejścia CLI (python main.py ...)
ui.py               # okno graficzne (python ui.py)
config.yaml         # parametry wyszukiwania
scraper/
├── cli.py          # interfejs wiersza poleceń (komendy scrape/raport/wszystko)
├── config.py       # wczytywanie config.yaml
├── http.py         # wspólny klient HTTP (nagłówki, opóźnienia, ponawianie)
├── models.py       # model Listing (jednolite ogłoszenie)
├── parsing.py      # parsowanie ceny, powierzchni, dat (po polsku)
├── storage.py      # baza SQLite + logika first_seen
├── geo.py          # geokodowanie (Nominatim) + odległość (haversine)
├── detail.py       # pogłębianie ofert: podstrony + pobieranie zdjęć
├── report.py       # kategoryzacja, dedup, wydruk/eksport
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
