# WeldVision AI — audyt kodu i projekt przebudowy interfejsu

**Zakres:** `weldvision_ai.py` (2394 linie), wersja zgodna z `WeldVision_AI_double_click_PATH_fix.zip` oraz `WeldVision_AI_batch_isolated_safe.zip`.

**Metoda:** przegląd statyczny kodu, kontrola składni (`py_compile`), pięć lokalnych testów funkcji obrazu/ROI/maski, próba wykazująca kolizję nazw eksportu. Nie wykonano testów interfejsu PyQt6 ani rzeczywistego uruchomienia CUDA/SAM na RTX 5070 w tym środowisku. Wnioski dotyczące zdarzeń Qt i GPU są analizą ryzyka wynikającą z kodu; należy je potwierdzić testami na Windows.

## Wniosek

Program posiada rozbudowane funkcje, ale jest zbyt silnie powiązany: interfejs, dane próbek, przetwarzanie AI, zapis projektu i logika eksportu znajdują się w jednym pliku. Najpierw trzeba wyeliminować ryzyko utraty danych i błędnych wyników, następnie uprościć pracę użytkownika, a na końcu rozwijać AI.

## Ryzyka i usterki (priorytety)

| ID | Priorytet | Gdzie | Ustalenie | Poprawka i kryterium odbioru |
|---|---|---|---|---|
| P01 | Krytyczny | `closeEvent` ~2232 | Zamknięcie tylko zapisuje stan do RAM, bez kontroli niezapisanych zmian na dysku. | Flaga `dirty`; przed zamknięciem i otwarciem innego projektu **Zapisz / Nie zapisuj / Anuluj**. |
| P02 | Krytyczny | `_save_project_to_path` ~2058–2149 | ZIP otwierany w `w`, czyli plik projektu jest od razu skracany. Błąd w połowie zapisu może pozostawić uszkodzony projekt. | Zapis do pliku tymczasowego w tym samym katalogu, weryfikacja ZIP i atomowa podmiana (`os.replace`); backup poprzedniej wersji. |
| P03 | Krytyczny | `run_sam` i `on_sam_finished` ~1768–1810 | Wynik pojedynczej analizy AI nie ma powiązania z identyfikatorem zdjęcia; podczas przetwarzania można zmienić aktywną próbkę, co może nadpisać inną maskę lub wywołać błąd rozmiaru. | Zadanie musi mieć stałe `sample_id`; wynik przypisać do właściwej próbki, niezależnie od nawigacji; umożliwić podgląd/akceptację. |
| P04 | Krytyczny | `run_sam` ~1788–1800, `closeEvent` | Ponowne kliknięcie AI zastępuje referencję do `QThread` podczas działania; zamknięcie czeka 3 sekundy, a obliczenia mogą trwać znacznie dłużej. Ryzyko `QThread: Destroyed while thread is still running`. | Jeden menedżer zadań, blokada duplikatów, obsługa anulowania, oczekiwanie na zakończenie przed usunięciem obiektu. |
| P05 | Wysoki | `run_sam_all` ~1569–1747 | Podczas AI wsadowego można usuwać/dodawać zdjęcia i edytować ich maski, podczas gdy wyniki przypisuje się po indeksie listy; ryzyko przypisania maski do niewłaściwej próbki lub nadpisania korekt. | Stałe UUID próbek zamiast indeksów, blokada operacji kolidujących albo kontrola wersji wyniku i akceptacja konfliktu. |
| P06 | Wysoki | `remove_current_item` ~1272 | Usunięcie elementu listy przed wyłączeniem sygnałów nawigacji może aktywować `currentRowChanged` w trakcie modyfikacji `batch_items`. | Blokować sygnały listy, bezpiecznie ustawić nową aktywną próbkę, test A/B/C z usuwaniem środkowej. |
| P07 | Wysoki | `accept_calibration` ~1417; `known_mm.valueChanged` | Zmiana znanej długości po zaznaczeniu dwóch punktów nie przelicza `mm_per_px`, choć użytkownik widzi nową liczbę. | Zapisać punkty i odległość pikselową, aktualizować kalibrację po zmianie długości albo jawnie wymagać „Zastosuj kalibrację”; wersjonować skalę. |
| P08 | Wysoki | `open_project` ~2170 | Otwarcie innego projektu nie pyta o niezapisane zmiany; sesja jest nadpisywana. Nie ma pełnej walidacji plików oraz kształtu masek. | Preflight pliku, odczyt do struktury tymczasowej, walidacja, dopiero wtedy zamiana bieżącej sesji. |
| P09 | Wysoki | `run_sam_all`, `run_batch_worker_cli` ~2258 | Program nie sprawdza z góry, czy **ten sam** Python uruchamiający proces roboczy ma `torch`, `transformers`, CUDA. Występuje już obserwowany błąd `ModuleNotFoundError: torch`. | Diagnostyka środowiska i krótki test procesu roboczego przy starcie analizy; precyzyjny komunikat i wskazanie interpretera. |
| P10 | Wysoki | `_on_batch_process_finished` ~1696 | Komunikat o SAM Huge sugeruje CUDA/VRAM także wtedy, gdy log mówi o braku `torch`. | Klasyfikacja błędów (brak pakietu, niedostępne CUDA, brak VRAM, uszkodzony model, brak dostępu do pliku), wskazówki zależne od przyczyny. |
| P11 | Wysoki | `export_batch_results` ~1990–2044 | Brak sprawdzania kolizji wszystkich wygenerowanych nazw i pytania o nadpisanie. Dla nazw `A`, `A_02`, `A` otrzymujemy `A`, `A_02`, `A_02` — nadpisanie. | Unikatowe nazwy oparte o UUID/indeks; sprawdzenie istniejących plików; eksport do nowego katalogu lub potwierdzenie. |
| P12 | Wysoki | `open_project`, `_save_project_to_path`, CSV | Po odczytaniu projektu `source_path` wskazuje na `tempdir/item_xxx/image.jpg`, a pierwotna nazwa źródłowa przestaje być przechowywana w modelu danych. Przy kolejnych zapisach/CSV traci się informację o pochodzeniu zdjęcia. | Oddzielne pola `original_filename`, `original_path` (informacyjne), `image_in_project`, `sample_id`. |
| P13 | Średni | `store_current_item_state` ~1366 | Każda aktualizacja wyniku kopiuje trzy pełnowymiarowe maski, co przy dużych JPG i kilkunastu próbkach niepotrzebnie obciąża RAM. | Przechowywać zmienione maski skompresowane, cache LRU aktywnych próbek, zapisywać przy przejściu lub „dirty”. |
| P14 | Średni | `copy_current_setup_to_all` ~1516 | ROI jest kopiowane w surowych współrzędnych pikselowych, co na zdjęciach o różnej rozdzielczości daje niepoprawne położenie. | Kopiowanie normalizowanych współrzędnych lub ostrzeżenie przy różnych wymiarach; automatyczne dopasowanie tylko za zgodą. |
| P15 | Średni | `clean_mask` ~78 | Otwieranie/zamykanie morfologiczne i odcinanie wysp poniżej 100 px mogą zmienić powierzchnię mierzoną. | Opcje parametrów przetwarzania; surowa maska AI i skorygowana maska obok siebie; zapis algorytmu do metadanych. |
| P16 | Średni | UI `MainWindow.__init__` ~863–1205 | 13 przycisków w górnym pasku, duplikaty w panelu bocznym, trzy przyciski zapisu o podobnych nazwach; górny pasek nie jest adaptacyjny. | Menu/toolbar z maks. 5–7 głównymi akcjami; `QSplitter` i zakładki; zwięzłe etykiety, kontekstowa dostępność. |
| P17 | Średni | cały plik; `BatchSamWorker` ~397 | Kilka implementacji podobnej logiki SAM; klasa `BatchSamWorker` pozostaje mimo użycia izolowanego `QProcess`. | Wydzielić silnik SAM, warstwę projektu i GUI. Usunąć niewykorzystywane ścieżki kodu. |
| P18 | Średni | launcher ZIP | Paczka `WeldVision_AI_double_click_PATH_fix.zip` nie zawiera `requirements.txt`, a launcher uruchamia pierwszą znalezioną instalację Pythona, niekoniecznie z kompletem bibliotek. `.vbs` ukrywa komunikaty błędów. | Wirtualne środowisko projektu, przycisk „Sprawdź instalację”, diagnostyka bez terminala i spójny, przetestowany instalator. |
| P19 | Średni | `open_project`, `closeEvent` | Katalogi tymczasowe po projektach nie są sprzątane; przy częstym otwieraniu mogą się gromadzić duże kopie zdjęć na C:. | Zarządzany katalog tymczasowy i sprzątanie po zamknięciu, z uwzględnieniem aktywnych procesów. |
| P20 | Średni | `run_sam_all` | „AI dla wszystkich zdjęć” nie działa bez przygotowania ROI/FG; część próbek jest pomijana, brak wygodnej tabeli gotowości przed startem. | Preflight ze statusem każdej próbki, liczba gotowych i pominiętych, możliwość powrotu do brakujących. |
| P21 | Wysoki (metrologia) | `calculate_metrics` ~1425 i raporty | Formuła A×ρ daje teoretyczną masę materiału dla odcinka o stałym przekroju; nie jest automatycznie „uzyskiem stopiwa” ani rzeczywistym zużyciem drutu. | Nazwać wynik „oszacowana masa materiału przekroju na 1 m”; odróżniać metal spoiny od przetopionego materiału rodzimego, doprecyzować obszar pomiarowy i założenia. |

## Proponowany interfejs — jeden czytelny ekran

```text
WeldVision AI — Projekt: NazwaProjektu.weldproj ● Niezapisane zmiany
[Otwórz projekt]  [Dodaj zdjęcia]  [Zapisz]  [Analizuj przygotowane]  [Anuluj]

┌──────────────────────┬────────────────────────────────┬─────────────────────────┐
│ PRÓBKI               │ OBRAZ                          │ POMIAR                  │
│ Szukaj / filtr       │ duże zdjęcie, zoom, pan        │ [Kalibracja]            │
│ ✓ 001 3315_12       │ nakładka maski + ROI           │ [Zaznaczenia]           │
│ ! 002 3315_13       │ FG / BG, historia zmian        │ [AI]                    │
│ ◯ 003 3315_14       │                                │ [Korekta]               │
│ ...                  │                                │ [Wyniki]                │
│ Poprzednie / Następne│                                │                         │
└──────────────────────┴────────────────────────────────┴─────────────────────────┘
Zadanie 4/12 • CUDA: RTX 5070 • VRAM 7,4 GB wolne • Zapisano 18:32
```

**Status próbki:** `Nieprzygotowana` / `ROI gotowe` / `Po AI — do weryfikacji` / `Zatwierdzona` / `Błąd`. Zielony znacznik wyłącznie dla zatwierdzonego wyniku, a nie dla samego zakończenia obliczeń.

**Panel prawy:** ustawienia w zakładkach, nie wszystkie naraz. W zakładce „Pomiar” kalibracja i gęstość; w „AI” model, urządzenie, start, postęp i diagnostyka; w „Korekta” maska i narzędzia; w „Wyniki” area, masa, założenia i eksport.

**Ważne zachowania użytkowe:** `Ctrl+S` zapis, `Ctrl+Z`/`Ctrl+Y` cofanie i ponawianie, strzałki przejścia do próbki, potwierdzenie nadpisania maski zatwierdzonej, komunikat o zmianach przed zamknięciem; automatyczny zapis odzyskiwania; możliwość pokazania/ukrycia markerów niezależnie od maski.

## Zmiany wewnętrzne — struktura rekomendowana

```text
weldvision/
  app.py                     # QApplication i okno główne
  gui/main_window.py         # układ, akcje, nawigacja
  gui/canvas.py              # wyświetlanie i edycja obrazu
  gui/panels.py              # pomiar, AI, korekta, wyniki
  core/sample.py             # Sample + stałe UUID, historia
  core/project.py            # zapis/odczyt, dirty, auto-save
  core/measurements.py       # obliczenia z testami
  ai/sam_engine.py           # jeden algorytm segmentacji
  ai/worker.py               # osobny proces, komunikacja JSON
  ai/preflight.py            # test instalacji/sterownika/VRAM
  export/exports.py          # CSV/PNG, unikatowe nazwy
  diagnostics/logging.py     # logi diagnostyczne
  tests/                    # testy regresyjne i GUI
```

Nie trzeba od razu przepisywać wszystkiego; najpierw wyodrębnić **model danych próbki i zapis projektu**, potem zadań AI, a na końcu przebudować wizualnie UI.

## Pomiar naukowy i rzetelność

Matematyka obecna w `calculate_metrics` jest spójna dla założenia stałego pola przekroju: `A_mm2 = N_px × (mm_per_px)^2`, `V_cm3_na_m = A_mm2`, `masa_kg_na_m = A_mm2 × rho_g_cm3 / 1000`. Nie jest to jednak bezpośredni pomiar sprawności stapiania ani masy wprowadzonego spoiwa, jeśli maska obejmuje również przetopiony materiał rodzimy. W raportach zapisać: nazwę/wersję modelu, metodę segmentacji, ROI, FG/BG, kalibrację (punkty i długość), skalę, gęstość, status zatwierdzenia oraz datę wykonania analizy.

## Plan wdrożenia i testy akceptacyjne

**Etap 1 — integralność danych:** P01, P02, P03, P04, P05, P06, P07, P08, P11 i P12; zapis atomowy, odzyskiwanie projektu, stałe identyfikatory, blokady edycji i bezpieczna nawigacja.

**Etap 2 — analiza i GPU:** P09, P10, P13, P14, P15, P17, P18; preflight pakietów/urządzeń, jedna implementacja SAM, kontrola pamięci, przyjazne błędy i sensowne przywracanie stanu.

**Etap 3 — interfejs:** P16, P20 i P21; pasek krótkich akcji, lewa lista próbek, centralny canvas, zakładki po prawej, status i zbiorcze wyniki; weryfikacja przez użytkownika.

**Minimalne testy regresyjne:**
1. 20 zdjęć z unikalnymi maskami/markerami; 100 przełączeń w losowej kolejności bez utraty danych.
2. Zapis → otwarcie → edycja → nadpisanie → otwarcie; pełna zgodność maski, punktów, nazw i kalibracji.
3. Symulowane przerwanie zapisu projektu: poprzedni plik nadal otwiera się bez błędów.
4. Zmiana znanej długości 10 na 20 mm powinna podwoić skalę mm/px i zwiększyć pole 4× przy tej samej masce (albo wymagać jawnej rekalibracji).
5. Uruchom AI na próbce A, przejdź do B przed końcem: wynik A nie może zmienić B.
6. Rozpocznij AI wsadowe, spróbuj usunąć/dodać próbkę: aplikacja blokuje operację lub zachowuje mapowanie po UUID.
7. Eksport nazw `A`, `A_02`, `A`: trzy unikatowe zestawy wyników, bez cichego nadpisania.
8. `torch` nie zainstalowany w interpreterze procesu roboczego: diagnostyka pokazuje brak modułu bez sugerowania VRAM i nie zamyka GUI.
9. 20 zdjęć wysokiej rozdzielczości i SAM Large/Huge: brak niekontrolowanego przyrostu RAM, możliwość anulowania.
10. Zamknięcie programu z niezapisanymi zmianami: użytkownik otrzymuje czytelny wybór i może anulować zamknięcie.

## Wynik przeprowadzonej kontroli

- Składnia: `python -m py_compile` — **OK**.
- Testy pomocnicze: `_prepare_sam_crop`, `_restore_mask_from_crop`, `clean_mask` — **5 podstawowych asercji OK**.
- Test eksportu nazw: `A`, `A_02`, `A` → `A`, `A_02`, `A_02` — **wykazana kolizja nazwy**.
- Brak pełnych testów interfejsu na Windows i GPU w środowisku audytu — stabilności produkcyjnej **nie potwierdzono**.
