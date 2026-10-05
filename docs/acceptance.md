# CIVCOM — niezależna akceptacja wydania

Każdy wynik musi zawierać faktyczny SHA Android/iOS, hash podpisanego binarium i konfiguracji gatewaya, model/OS, kanał dystrybucji, datę, operatora, polecenie/scenariusz, exit/result i prywatny evidence path. Dane syntetyczne; żadnych sekretów lub rozmów operacyjnych w raportach publicznych. Wynik autora jest oddzielny od niezależnego acceptance. W chwili utworzenia dokumentu wszystkie poniższe próby urządzeń/serwera/sklepów są NOT_RUN; nie przenosić wyniku lokalnych testów Python do tych wierszy.

| Brama | Dowód wymagany dla PASS |
|---|---|
| Bazowy build | Niezmienione przypięte upstream SHA, narzędzia i wynik obu platform |
| Build po zmianach | Candidate SHA, unit/static + native builds, zachowane historyczne FAIL |
| Podpisy | Produkcyjny/dev package, TeamID/profile/entitlements, Android Play signing fingerprint, actual associations |
| Logowanie | Login → auth.soia.info → właściwy app callback, PKCE, poprawny issuer/server; obcy server/callback odrzucony |
| Rejestracja użytkowników | Serwer/MAS odrzuca samorejestrację, administrator realnie zakłada testowe konto; ukryte UI nie jest dowodem |
| E2EE | Android↔iOS DM/grupa, weryfikacja urządzenia, nowe/odwołane urządzenie, brak kluczy błędnego konta |
| Recovery | Bezpieczne odzyskanie i utrata klucza, wymagany proces recovery, wylogowanie/cache |
| Media | Obrazy/pliki/audio-video attachments istniejące w v1; uprawnienia i E2EE download po offline/reconnect |
| Zakres wyłączony | Brak UI/startu audio-video calls, map i PSP; incoming call event i deep link nie inicjalizują wyłączonych usług |
| Prywatność sieci | Brak zakazanej telemetrii na obu urządzeniach; lista pozostałych requestów i metadanych |
| Gateway boundary | TLS, własna sieć, brak public5000/8080, obce źródło odrzucone, brak body w logach, błąd klucza blokuje nowy start |
| Pusher | Prawdziwy account pushers: dokładny app_id/url/format event_id_only, rejestracja/rotacja/unregister po logout |
| Count-only | Standardowy i rzeczywisty Synapse read-receipt/unread-count update: HTTP 200/rejected[], zero requestów upstream i zero alertów; brak badge forwarding |
| Android push | FCMv1 release i dev/nightly, foreground/background/killed/locked/offline, token rotation, denied permission, generic preview |
| iOS push | Sandbox Debug i production podpisany/TestFlight, NSE + appgroup, fore/back/killed/locked/offline, brak treści/nadawcy/pokoju |
| Negatywne provider | Błędny token/topic/środowisko, cofnięte IAM/klucz, outage/retry i cleanup odrzuconego pushkey; bez fake PASS po health200 |
| Polityki/licencje | Zatwierdzone procesy/retencja/licencje i zgodne privacy/store declarations + prawdziwy source |
| Pilotaż | Podpisana ograniczona próba użytkowników, operator, monitoring, rollback i odtworzenie |
| Sklepy | Faktyczne submission/review/publishing evidence, oddzielnie od signed build |

Zwalidowane aktualizacje count-only (forma standardowa oraz Synapse: id pusty, type null, sender pusty) otrzymują HTTP 200 z {"rejected":[]} jako no-op: zero requestów do Sygnal/dostawców i zero alertów. Brak event_id/room_id jest prawidłowy dla tej aktualizacji; zdarzenia nadal wymagają obu identyfikatorów. Przed oznaczeniem push PASS potwierdzić z faktycznym Synapse aktualizację licznika po read receipt, odpowiedź 200 i brak dodatkowego powiadomienia. Gateway nie przekazuje liczników/badge do dostawców. Health/readiness nie testuje uprawnień FCM/APNs ani dostarczania. OIDC schematy Android są prywatnymi URI; assetlinks na domenie nie dowodzi ochrony custom-scheme callback — kontrola state/PKCE/SDK musi przejść test native.
