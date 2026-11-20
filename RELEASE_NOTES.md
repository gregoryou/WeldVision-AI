# WeldVision AI 3.5.0

- **Wstecz / Dalej** prowadzą po etapach Kalibracja, Ustawienia maski, Analiza, Wynik i Pomiar.
- **Ustawienia maski** zawierają ROI oraz FG/BG. W **Analiza** można uruchomić SAM, poprawić wynikową maskę i zatwierdzić pole. Nowe projekty wybierają SAM Huge. Projekty zachowują zapisany model.
- **Pomiar** oferuje prowadzony pomiar gardzieli a w sześciu kliknięciach dla prostego lica, pomiar z obrysu oraz metody oparte na istniejących prowadnicach.
- Wstawienie i dwuklik komentarza otwierają edytor treści. Zmiany można cofać.
- **O programie** umożliwia przełączenie PL/EN bez zamykania projektu. Język jest zapamiętywany lokalnie.

## Weryfikacja

Windows 11, Python 3.13, PyQt6 i OpenCV. Uruchomiono `python -m pytest -q -ra`. Wynik 74 zaliczone testy i 1 pominięty, ponieważ opcjonalny zestaw DSC_*.JPG był niedostępny.

Test interfejsu sprawdza przygotowanie zlecenia SAM Huge, obsługę przykładowej maski, jej ręczną korektę, zatwierdzenie i pomijanie zatwierdzonych próbek w analizie seryjnej. Weryfikacja używa kontrolowanej maski. W tym przebiegu nie wykonywano inferencji SAM Huge na GPU. Testy osobno sprawdzają przełączenie języka z niezapisanym projektem, edycję komentarza w oknie dialogowym, pomiar gardzieli i Cofnij.


### Informacje o autorze i kontakcie / Attribution and contact

- W zakładce **O programie / About** podano autora, afiliację naukową (bez oficjalnego patronatu uczelni), licencję i aktywne odnośniki do repozytorium oraz zgłoszeń błędów.
- The Polish and English README files include the same author and support details. No private contact details are embedded.
