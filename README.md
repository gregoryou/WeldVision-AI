# WeldVision AI 3.5.1

## Autor i kontakt

- **Autor i kierownictwo projektu:** Sławomir Krajewski.
- **Afiliacja naukowa autora:** Zachodniopomorski Uniwersytet Technologiczny w Szczecinie.
- **Repozytorium i kod źródłowy:** https://github.com/gregoryou/WeldVision-AI
- **Kontakt, pytania, zgłaszanie błędów i propozycje współpracy:** https://github.com/gregoryou/WeldVision-AI/issues
- **Licencja kodu:** GNU GPL-3.0-only.

*Afiliacja identyfikuje miejsce pracy naukowej autora. Nie stanowi oświadczenia, że uczelnia jest wydawcą, sponsorem lub oficjalnym podmiotem odpowiedzialnym za program.* Ze względów prywatności nie publikujemy prywatnego telefonu, adresu zamieszkania ani nieuzgodnionego adresu e-mail. Do kontaktu służy GitHub Issues.

[English documentation](README_EN.md)

**Licencja:** kod źródłowy jest udostępniany na zasadach [GNU GPL-3.0-only](LICENSE). Modele SAM i biblioteki zewnętrzne zachowują własne warunki licencyjne. [Informacja o komponentach](THIRD_PARTY_COMPONENTS.md) · [Historia rozwoju z pomocą AI](AI_ASSISTED_DEVELOPMENT.md) · [Bezpieczeństwo](SECURITY.md).

**Ograniczenia:** program ma charakter badawczy; nie jest certyfikowanym przyrządem metrologicznym. Segmentacja SAM wymaga kontroli operatora, a dokładność pomiarów zależy od poprawnej kalibracji. **Historyczne pomiary gardzieli `a` z wersji 3.2.x wymagają ponownego wykonania** — program nie powinien traktować ich jako aktualnych wyników.


WeldVision AI mierzy na zdjęciach makroskopowych pole przekroju spoiny, grubość blach, gardziel spoiny pachwinowej i inne wymiary geometryczne. Projekt .weldproj zapisuje zdjęcia, kalibrację, maski i oznaczenia.

## Uruchomienie w Windows

1. Rozpakuj archiwum do osobnego katalogu. Wymagany jest Python 3.13.
2. Przy pierwszej instalacji uruchom `Install_Base.bat`. Do analizy SAM na obsługiwanej karcie NVIDIA dostępny jest moduł instalowany przez `Install_AI_NVIDIA_CUDA.bat`. W zakładce **Analiza** można sprawdzić pakiety i wykrywanie CUDA.
3. Uruchom `Start_WeldVision_AI.bat`. Język wybierzesz w **O programie → Język interfejsu**. Zmiana języka zachowuje otwarty projekt.

## Od zdjęcia do wyniku

| Etap | Czynność |
| --- | --- |
| **Kalibracja** | Wskaż znaną długość lub trzy sąsiednie przecięcia siatki 10×10 mm, która leży w płaszczyźnie zgładu. |
| **Ustawienia maski** | Obejmij spoinę prostokątem ROI. Zaznacz FG na pewnych fragmentach spoiny i BG na pewnych fragmentach tła. Kliknij **Dalej → Analiza** po zakończeniu oznaczania. |
| **Analiza** | Kliknij **Utwórz maskę AI — bieżąca próbka**. Nowy projekt wybiera SAM Huge. Po analizie obejrzyj maskę i popraw ją pędzlem **Dodaj do maski**, **Usuń z maski** lub wielokątem. |
| **Wynik** | Odczytaj pole, objętość i masę na metr lub zapisz wyniki w Excelu. Objętość i masa zakładają stały przekrój na długości spoiny. |
| **Pomiar** | Zmierz grubość blachy, gardziel, promień lub kąt. Dodaj podpis lub podziałkę. Eksport fotografii obsługuje PNG, JPEG, BMP i TIFF. |

**Zatwierdź pomiar pola** w zakładce **Analiza** oznacza, że sprawdziłeś obrys maski wykorzystanej do obliczenia pola. Pole jest już widoczne po uzyskaniu niepustej maski i kalibracji. Analiza serii pomija zatwierdzone próbki. Edycja maski przenosi próbkę ponownie do weryfikacji. Oryginalna maska z SAM pozostaje dostępna w projekcie po ręcznej korekcie.

Do pomiarów liniowych wystarcza kalibracja. Można wykonać je także przed segmentacją. Ręczną maskę obrysujesz wielokątem w zakładce **Analiza**. Prawy przycisk myszy zamyka i wypełnia wielokąt.

## Pomiar gardzieli a spoiny pachwinowej

W zakładce **Pomiar** kliknij **Zmierz gardziel a — krok po kroku**.

- **Proste lico — sześć kliknięć**. Zaznacz po dwa punkty na powierzchni każdej blachy po stronie spoiny i dwa na prostym odcinku lica. Program wyznacza teoretyczny narożnik **O** z przecięcia prowadnic blach, a następnie rzut prostopadły z **O** do lica. Wynik `a = r` pojawia się wtedy, gdy przejdzie kontrolę trójkąta równoramiennego.
- **Wklęsłe lub wypukłe lico — obrys**. Wskaż **O**, pierwszy brzeg lica, kolejne punkty konturu i drugi brzeg, a następnie użyj prawego przycisku myszy. Przy licu wklęsłym uwzględnij jego najgłębszy fragment.
- Metody oparte na istniejących prowadnicach pozostają dostępne w tym samym oknie.

Wybierz **Wstaw komentarz** i kliknij miejsce podpisu na zdjęciu, aby wpisać treść. Dwuklik komentarza ponownie otwiera edytor.

## Testy

W środowisku z wymaganymi pakietami uruchom `python -m pytest -q -ra`. Instrukcja angielska opisuje instalację w środowisku wirtualnym.

## Aktualizacja 3.5.1

Eksport CSV zabezpiecza pola tekstowe mogące zostać zinterpretowane przez Excel jako formuły, bez zmiany wartości liczbowych i danych projektu. Poprawiono zależności Linux CI dla PyQt6. Zobacz [opis poprawek 3.5.1](RELEASE_NOTES_3_5_1.md).
