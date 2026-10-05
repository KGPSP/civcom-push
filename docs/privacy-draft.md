# CIVCOM — szkic informacji o prywatności

DRAFT / BLOKADA PUBLIKACJI. To materiał do zatwierdzenia przez administratora danych i właściwe osoby KG PSP; nie jest obowiązującą polityką. Nie publikować pod `/privacy` w tej postaci.

CIVCOM jest planowanym komunikatorem KG PSP dla kont nadawanych przez administratora. Aplikacja ma korzystać z serwera `soia.info` i logowania `auth.soia.info`. Zakres v1 obejmuje wiadomości indywidualne/grupowe, obrazy i pliki, szyfrowanie E2EE, weryfikację urządzeń, odzyskiwanie i powiadomienia. Zakres nie obejmuje rozmów głosowych/wideo, map ani integracji PSP.

Do uzupełnienia i zatwierdzenia przed publikacją:

| Element informacji | Stan / wymagane ustalenie |
|---|---|
| Administrator, dane kontaktowe, IOD | Publikujący KG PSP wskazany; pełna formalna tożsamość i kontakty administratora/inspektora niezatwierdzone |
| Cel i podstawa przetwarzania | Określić rzeczywiste cele organizacyjne i właściwe podstawy; nie domniemywać zgody/obowiązku prawnego |
| Kategorie danych | Konta/profile, urządzenia, identyfikatory pokoi/zdarzeń, członkostwo i metadane; zaszyfrowane wiadomości/załączniki; logi logowania/usług do inwentaryzacji |
| Lokalne dane | Klucze/cache/backup i zapis plików na urządzeniu — zweryfikować zachowanie obu podpisanych klientów |
| Push | Gateway ma przekazywać event_id/room_id i token do Google FCM/Apple APNs; APNs dodatkowo niesie SHA256 identyfikatora klienta wymagany do routingu iOS. Hash jest pseudonimowy i korelowalny, nie anonimowy. Brak body/nazwy pokoju/nadawcy; ustalić odbiorców, warunki, regiony i transfery |
| Hosting/SSO/backup | Potwierdzić wszystkich podwykonawców, role, umowy, lokalizacje i dostęp administratorów |
| Retencja | Gateway proponuje48h dla terminalnego cache dedup SHA256/status/time; niepewne rekordy wymagają operatora i nie są automatycznie usuwane. Brak zatwierdzonych okresów dla kont, tokenów, metadanych, wiadomości, mediów, logów i kopii — blokuje publikację |
| Dostęp, usuwanie i prawa | Ustalić procedurę wniosków, kontakt, identyfikację, terminy, odwołanie dostępu, ograniczenia usuwania w pokojach/kopiach |
| Bezpieczeństwo i E2EE | E2EE nie ukrywa wszystkich metadanych; nie składać zapewnienia o braku dostępu serwera do dowolnych danych; określić politykę recovery/device trust |
| Incydenty i zgłoszenia | Brak zatwierdzonego procesu; wyznaczyć odpowiedzialnych, kanał i obsługę |
| Telemetria | Plan wyłącza PostHog/Sentry/Rust Sentry/Rageshake; potwierdzić w diffach i na urządzeniach oraz zinwentaryzować pozostałe SDK/sieć |
| Wersja i wejście w życie | Ustalić po zatwierdzeniu; nie wymyślać dat obowiązywania |

Wersja publiczna powinna jasno opisywać rzeczywiste, sprawdzone zachowanie; deklaracje sklepowe muszą być z nią zgodne. Sama konfiguracja tego gatewaya lub brak pól treści w jednym request nie potwierdza prywatności całego systemu. Apple wymaga uwzględnienia także partnerów/SDK w deklaracjach [App Privacy](https://developer.apple.com/app-store/app-privacy-details/); Google opisuje deklarowanie w [Data safety](https://support.google.com/googleplay/android-developer/answer/10787469). Odpowiedzi formularzy przygotowuje się na podstawie inwentaryzacji, bez zaznaczania „brak zbierania danych” z powodu samego E2EE.
