# RCL - Rzadowy Proces Legislacyjny

Roboczy kontekst metodologiczny dla szerszego projektu Polish Dynaword:
[docs/polish_dynaword_research_frame.md](docs/polish_dynaword_research_frame.md).
Notatka dla legal review RCL:
[docs/rcl_legal_review_note.md](docs/rcl_legal_review_note.md).
Najnowsza kontrola przyrostu danych RCL:
[docs/rcl_delta_check_2026-08-26.json](docs/rcl_delta_check_2026-08-26.json).
Dowod prywatnej archiwizacji restricted na Hugging Face:
[docs/rcl_restricted_source_archive_2026-08-26.json](docs/rcl_restricted_source_archive_2026-08-26.json).

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

Kolejka dokumentow pozostalych po pilocie oraz ich osobny download batch:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_make_remaining_source_queue.py --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_gold_pilot.py --queue data\rcl_2026_consultations\review_queue_remaining_after_pilot.csv --output-dir data\rcl_remaining_consultations_v0_1 --priority 0 --limit 0 --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_validate_gold_pilot.py --input-dir data\rcl_remaining_consultations_v0_1 --expected-rows 42 --allow-duplicate-digests
```

Pelna kolejka 1000 wybranych dokumentow i batch pozostaly po dwoch
zaakceptowanych artefaktach 40 + 42:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_review_queue.py --output data\rcl_2026_consultations\review_queue_1000.csv --limit 0

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_make_remaining_source_queue.py --queue data\rcl_2026_consultations\review_queue_1000.csv --completed data\rcl_gold_pilot_v0_1\annotations.csv --completed data\rcl_remaining_consultations_v0_1\annotations.csv --output data\rcl_2026_consultations\review_queue_1000_remaining_after_82.csv --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_gold_pilot.py --queue data\rcl_2026_consultations\review_queue_1000_remaining_after_82.csv --output-dir data\rcl_2026_selected_remaining_918_v0_1 --priority 0 --limit 0 --actor PiotrSty
```

Pelny metadata crawl projektow ustaw z 2025 roku, kolejka wybranych dokumentow
i wznawialny download:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_downloader.py --output-dir data\rcl_2025_consultations --type-id 2 --create-from 2025-01-01 --create-to 2025-12-31 --max-pages 0 --no-download --save-html --resume --checkpoint-every 20 --workers 4

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_review_queue.py --projects-csv data\rcl_2025_consultations\projects.csv --documents-csv data\rcl_2025_consultations\documents.csv --output data\rcl_2025_consultations\review_queue_all_selected.csv --limit 0

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_gold_pilot.py --queue data\rcl_2025_consultations\review_queue_all_selected.csv --output-dir data\rcl_2025_selected_v0_1 --priority 0 --limit 0 --workers 8 --checkpoint-every 50 --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_validate_gold_pilot.py --input-dir data\rcl_2025_selected_v0_1 --expected-rows 4166 --allow-duplicate-digests

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_extract_pilot_text.py --input-dir data\rcl_2025_selected_v0_1 --actor PiotrSty --checkpoint-every 50 --workers 4

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_validate_extraction.py --input-dir data\rcl_2025_selected_v0_1 --expected-rows 4166
```

Metadata-only handoff do Polish DynaWord:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_prepare_dynaword_handoff.py --actor PiotrSty
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

Paczka dla review prawnego, bez surowych dokumentow i bez extracted text:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_make_legal_review_pack.py --actor PiotrSty
```

Dry-run przeniesienia zaakceptowanych rekordow kalibracyjnych do
`annotations.csv`:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_apply_calibration_review.py --actor PiotrSty
```

Zapis do `annotations.csv` wymaga `--commit` i zrodlowego CSV, w ktorym
`manual_review_status` ma wartosc `accepted`, `reviewed` albo `approved`.
Drafty oznaczone `needs_human_acceptance` sa pomijane.

Kolejka i review pack dla pozostalych niezaakceptowanych rekordow:

```powershell
& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_make_remaining_review_queue.py --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_build_review_pack.py --queue remaining_review_queue.csv --output-dir remaining_review_pack --sheet-name remaining_review_sheet.csv --title "RCL Remaining Review Pack" --description "Local review surface for the 30 unreviewed RCL pilot rows. Raw documents and extracted text are linked locally and should not be published before legal and PII review." --actor PiotrSty

& "C:\Users\Hipek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\rcl_draft_calibration_review.py --review-pack-dir remaining_review_pack --sheet-name remaining_review_sheet.csv --output-prefix remaining_review_suggestions --actor Codex-assisted
```

Instrukcja recenzji znajduje sie w
`docs/rcl_gold_set_annotation_protocol.md`; notatka dla review prawnego w
`docs/rcl_legal_review_note.md`. Surowe dokumenty pilota pozostaja lokalne do
czasu review legal/PII. Wyekstrahowany tekst rowniez pozostaje lokalny. Na
Hugging Face nalezy publikowac najpierw manifesty, checksums, opisy runow,
machine-observations bez snippetow i szablon anotacji.

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
- `rcl_remaining_consultations_v0_1/` - osobny batch dla pozostalych rekordow z
  kolejki review, bez mieszania z zaakceptowanym pilotem.
- `rcl_2026_selected_remaining_918_v0_1/` - checkpointowany batch dla 918
  rekordow pozostalych do pelnej kolejki 1000 po zaakceptowanych 82.
- `rcl_dynaword_handoff_v0_1/` - metadata-only adapter/handoff do Polish
  DynaWord; bez pola `text`, bez raw payloadow i bez claimu training-ready.
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
- `rcl_gold_pilot_v0_1/review_pack/calibration_apply_report.json` - raport z
  dry-run lub zapisu zaakceptowanych rekordow do `annotations.csv`.
- `rcl_gold_pilot_v0_1/remaining_review_queue.csv` i
  `rcl_gold_pilot_v0_1/remaining_review_pack/` - lokalna paczka review dla
  30 rekordow, ktore pozostaly po zaakceptowanej kalibracji.
- `rcl_gold_pilot_v0_1/legal_review_pack/` - metadata-only kolejka dla legal
  review: dokumentowe provenance, working premise, PII flags i puste pola
  decyzyjne dla prawnika.

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
