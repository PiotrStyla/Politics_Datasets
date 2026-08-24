# RCL - Rzadowy Proces Legislacyjny

Roboczy kontekst metodologiczny dla szerszego projektu Polish Dynaword:
[docs/polish_dynaword_research_frame.md](docs/polish_dynaword_research_frame.md).

Ten katalog zawiera narzedzia do pobierania publicznych danych z
`legislacja.gov.pl`, ze szczegolnym naciskiem na:

- liste projektow z Rzadowego Procesu Legislacyjnego,
- metadane projektow,
- etap `Konsultacje publiczne`,
- PDF-y ze stanowiskami / pisemnymi uwagami organizacji.

W szerszym pipeline RCL traktujemy jako kandydacki strumien
source-ingestion/provenance dla Polish Dynaword, a nie jako izolowany scraping.

## Szybki start

W tym srodowisku nie ma `python` w globalnym `PATH`, ale Codex ma bundlowany
runtime:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_downloader.py --max-pages 1 --max-projects 5 --no-download --save-html
```

Pelniejsze pobranie projektow ustaw:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_downloader.py --max-pages 0 --save-html
```

Pelny inventory listy projektow, bez wchodzenia w strony projektow:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_downloader.py --max-pages 0 --list-only --save-html
```

Domyslnie skrypt pobiera tylko dokumenty z konsultacji, ktorych kategoria lub
nazwa pliku zawiera `stanowisk` albo `uwag`. Aby zapisac wszystkie dokumenty z
etapu konsultacji publicznych:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_downloader.py --max-pages 0 --all-consultation-docs --save-html
```

Kolejka do recznego review z manifestu konsultacji:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_review_queue.py --limit 100 --per-priority 40
```

Ograniczony pilot gold setu: pobranie 40 dokumentow `priority=1`, manifest
SHA-256 i tabela do anotacji:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_gold_pilot.py
```

Walidacja zgodnosci manifestu, plikow i tabeli anotacji:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_validate_gold_pilot.py
```

Lokalna ekstrakcja tekstu z dokumentow pilota oraz machine-observations do
triage:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_extract_pilot_text.py --actor PiotrSty
```

Walidacja ekstrakcji:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_validate_extraction.py
```

Kolejka 10 dokumentow do kalibracyjnego manual review:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_make_calibration_queue.py --actor PiotrSty
```

Lokalny HTML/CSV review pack dla kolejki kalibracyjnej:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_build_review_pack.py --actor PiotrSty
```

Konserwatywne draft-sugestie do kalibracyjnego review:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_draft_calibration_review.py --actor Codex-assisted
```

Instrukcja recenzji znajduje sie w
`docs/rcl_gold_set_annotation_protocol.md`. Surowe dokumenty pilota pozostaja
lokalne do czasu review legal/PII. Wyekstrahowany tekst rowniez pozostaje
lokalny. Na Hugging Face nalezy publikowac najpierw manifesty, checksums, opisy
runow, machine-observations bez snippetow i szablon anotacji.

## Wyniki

Skrypt zapisuje dane w `data/rcl/`:

- `projects.csv` i `projects.jsonl` - lista projektow i link do katalogu konsultacji,
- `documents.csv` i `documents.jsonl` - dokumenty znalezione w konsultacjach; kolumna
  `selected` oznacza dokumenty pasujace do filtra pobierania,
- `raw_html/` - opcjonalny zapis surowego HTML-u, gdy uzyto `--save-html`,
- `pdf/` - pobrane pliki PDF, pogrupowane po projekcie i podkatalogu.
- `runs/rcl_run_*.json` - audytowalny opis runu: argumenty, liczniki i sciezki
  wynikow.
- `review_queue.csv` - opcjonalna kolejka dokumentow do manual review.
- `rcl_gold_pilot_v0_1/` - lokalny pilot: manifest, tabela anotacji, checksums,
  run i 40 dokumentow do recenzji.
- `rcl_gold_pilot_v0_1/extracted_text/` - lokalne ekstrakty tekstowe; nie
  publikowac przed legal/PII review.
- `rcl_gold_pilot_v0_1/machine_observations.csv` - automatyczne wskazowki do
  triage, nie recenzja czlowieka.
- `rcl_gold_pilot_v0_1/calibration_queue.csv` - 10-row calibration set do
  pierwszego manual review.
- `rcl_gold_pilot_v0_1/review_pack/` - lokalny HTML/CSV do kalibracyjnego
  review; zawiera linki do lokalnych plikow i nie jest artefaktem do publikacji.
- `rcl_gold_pilot_v0_1/review_pack/calibration_review_suggestions.csv` -
  konserwatywne draft-sugestie; wymagaja akceptacji/edycji recenzenta przed
  przeniesieniem do `annotations.csv`.

## Uwagi techniczne

Crawler korzysta tylko ze standardowej biblioteki Pythona. Strona RCL jest
publiczna, ale warto utrzymywac umiarkowane tempo pobierania. Domyslny odstęp
miedzy zadaniami to `0.5 s`; mozna go zwiekszyc przez `--sleep 1.5`.

Najwazniejsze parametry:

- `--type-id 2` - projekty ustaw,
- `--type-id 10` - projekty rozporzadzen,
- `--max-pages 0` - bez limitu stron,
- `--max-projects N` - limit projektow do testow,
- `--list-only` - tylko inventory listy projektow,
- `--no-download` - tylko metadane,
- `--category-keyword tekst` - dodatkowy filtr kategorii lub nazwy pliku.
