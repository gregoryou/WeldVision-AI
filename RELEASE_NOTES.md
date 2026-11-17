# WeldVision AI 3.2 — kalibracja i pomiary grubości (2026-11-10)

- Naprawiono przycisk kalibracji: pozostaje na karcie Pomiar. Narzędzia edycji maski nadal otwierają kartę Korekta.
- Dodano grubość spoiny a z trzech punktów (grań i dwa końce lica), prostopadle do odcinka lica.
- Dodano grubości blach t₁/t₂ oraz dowolne odcinki z dwóch punktów; narzędzia dostępne po kalibracji.
- Dodano wiele pomiarów na zdjęciu, etykiety mm, tabelę, usuwanie, anulowanie Esc/prawym przyciskiem oraz Ctrl+Z/Ctrl+Y.
- Punkty zachowują się przy zmianie próbki i zapisie/otwarciu projektu; zmiana skali przelicza wszystkie wymiary.
- Eksport obejmuje pomiary_liniowe.csv i obraz z wymiarami. CSV zawiera współrzędne źródłowe i skalę.
- Karta Pomiar ma przewijanie, a błędne/zerowe odcinki są odrzucane. Pomiar a odrzuca rzut poza wskazanym odcinkiem lica.
- Poprawiono przenośność testów dla ścieżek Windows z polskimi znakami.

Walidacja: Python 3.13 / Windows, PyQt6 (offscreen): **26 testów zaliczonych, 1 pominięty**. Pominięto opcjonalny test wcześniejszego zestawu DSC_*.JPG, niedostępnego pod wskazaną w tym teście ścieżką. Testy obejmują geometrię, kalibrację przez kliknięcia w GUI, grubości a/t₁/t₂, zmianę skali, nawigację, cofanie, zapis/odczyt, eksport, kompatybilność v1/v2 i dotychczasowe testy procesów roboczych. Sprawdzono wizualnie okna 1650×970 i 1100×700 na obrazie syntetycznym.

Przy nieregularnym licu a jest wynikiem wskazanej konstrukcji geometrycznej. Dokładność wyświetlenia nie stanowi deklaracji niepewności. Aktualizacja nie wymaga nowych zależności aplikacji.

---

# WeldVision AI 3.1 — raport etapów wdrożenia

Zrealizowano modernizację po audycie 21 zagadnień (P01–P21). Rozwiązania i ograniczenia:

| Etap | Identyfikatory | Zmiany |
|---|---|---|
| 1 — integralność danych | P01, P02, P06, P07, P08, P11, P12, P19 | Dirty flag i dialog zapis/odrzuć/anuluj; zapis ZIP przez temp i `os.replace`, walidacja CRC i `.bak`; UUID; bezpieczne przełączanie i usuwanie; kompletna kalibracja; poprawiony import v1; unikatowe nazwy eksportu; kontrolowane TemporaryDirectory |
| 2 — analiza AI | P03, P04, P05, P09, P10, P13, P14, P15, P17, P18 | Izolowany `QProcess`, identyczny interpreter GUI/worker, diagnostyka zależności i CUDA, zadania po UUID/revision; RAM: skompresowane maski, jeden model SAM w procesie, wycinanie ROI, parametry morfologii domyślnie zerowe; znormalizowane kopiowanie ROI; odrębne pliki modułów, instalator venv |
| 3 — przejrzyste GUI | P16, P20, P21 | Trzy panele `QSplitter`, cztery zakładki, ograniczona liczba akcji na pasku, statusy próbek, zatwierdzanie pomiaru, tabelaryczne wyniki, przejrzysta terminologia fizyczna |
| 4 — regresja | wszystkie powyżej | Testy jednostkowe, testy zapisu/odzysku, zdjęcia makroskopowe, GrabCut bez torch i test diagnostyczny |

## Wynik testów w środowisku przygotowania

- `compileall` i `py_compile` — OK.
- `pytest`: **16 passed, 1 skipped** (test GUI wymaga PyQt6; nie było go w środowisku wykonania).
- Testy na rzeczywistych zdjęciach `DSC_*.JPG`: 10 obrazów, weryfikacja integralności JPG, ROI, maski i FG/BG po zapis/odczyt oraz eksport zestawu — OK.
- Test GrabCut na syntheticznym zdjęciu — OK, bez Transformers.
- Rzeczywiste uruchomienie SAM Large/Huge na RTX 5070, graficzne testy Windows oraz sterownik NVIDIA — **nie zostały wykonane w tym środowisku**. Wymagają testu po instalacji na PC użytkownika.

## Istotne zasady

- Stare projekty `.weldproj` nie są automatycznie nadpisywane podczas otwarcia.
- Bezpiecznie otwieraj stare projekty, ale pierwsze zapisanie wykonaj przez „Zapisz jako”, tworząc kopię.
- Model SAM może wymagać pobrania wag i zgodnych wersji PyTorch/Transformers. Instalator instaluje zależności, nie włącza ani nie pobiera modelu przed pierwszą analizą.
- Stabilność przy awarii natywnej biblioteki CUDA jest ograniczona izolacją procesu; taka awaria nie gwarantuje ukończenia bieżącego zadania, ale powinna nie zniszczyć pliku projektu.
