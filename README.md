# CIVCOM — infrastruktura push i metadane dystrybucji

Oddzielny pakiet CIVCOM push do przeglądu, stan 2026-10-05. To źródła gatewaya i szablony konfiguracji; uruchomienie z rzeczywistymi credentials, urządzeniami i routingiem wymaga odrębnej akceptacji. Sekrety są poza repozytorium. Licencja: [AGPL-3.0-only](LICENSE); pochodzenie i bezpieczny zakres publikacji: [PROVENANCE.md](PROVENANCE.md).

Sygnal v0.17.0 pochodzi z [element-hq/sygnal](https://github.com/element-hq/sygnal/tree/v0.17.0), commit `53c25a82f85739eb58f2c95b9483f61ac8deedc4`. Oficjalny obraz [matrixdotorg/sygnal:v0.17.0](https://hub.docker.com/r/matrixdotorg/sygnal) przypięto do indeksu OCI `sha256:141f5e72fdf99a28e29ca87f3a46c19ed1cf21d5074aa3ef9df7c067e0c1c46a` (linux amd64/arm64). Pochodzenie i przypięte wersje opisuje PROVENANCE.md; test ma byte-identical kopię pojedynczego modułu upstream w tests/vendor. Nie pobierano warstw obrazu w ramach author checks. Opcjonalny Caddy 2.10.2-alpine również ma digest. Runtime obu obrazów pozostaje NOT_RUN.

Docelowy adres: `https://push.soia.info/_matrix/push/v1/notify`. Matrix serverName `soia.info`, API `https://matrix.soia.info`, issuer `https://auth.soia.info/`. Powiadomienia zdarzeń niosą identyfikatory zdarzenia/pokoju i token urządzenia; APNs dodatkowo potrzebuje zwalidowanego pseudonimowego identyfikatora klienta SHA256, aby iOS wybrał właściwe credentials; nagłówki, body, konta i tokeny nie trafiają do logów komponentów tego pakietu. To ograniczenie pakietu, nie potwierdzenie konfiguracji logów obecnego Traefika/MAS/Synapse ani polityki prywatności całej usługi.

| Platforma / build | Matrix pusher app_id | Provider / topic |
|---|---|---|
| Android release | `pl.gov.psp.civcom` | FCM HTTP v1, rzeczywisty projekt prod |
| Android debug | `pl.gov.psp.civcom.debug` | FCM HTTP v1, rzeczywisty projekt dev |
| Android nightly | `pl.gov.psp.civcom.nightly` | FCM HTTP v1, rzeczywisty projekt dev |
| iOS Release | `pl.gov.psp.civcom.ios.prod` | APNs production / `pl.gov.psp.civcom` |
| iOS Debug | `pl.gov.psp.civcom.dev.ios.dev` | APNs sandbox / `pl.gov.psp.civcom.dev` |

Android fdroid nie używa FCM. Identyfikatory pochodzą z implementacji agentów platformowych; iOS potwierdził wygenerowany projekt PBX. Token iOS ma format base64, dlatego Sygnal używa `convert_device_token_to_hex: true`. Matrix `app_id` APNs celowo różni się od `topic`. Apple TeamID `L643PDVV68` został odczytany przez koordynatora z membership KG PSP; nie jest wymyślonym placeholderem. KeyID i klucze APNs nadal nie są dostępne. Produkcja i sandbox mają oddzielne deskryptory KeyID/keyfile/topics; wspólny klucz dopuszczalny wyłącznie po potwierdzeniu jego rzeczywistych obu zakresów u Apple.

Granica HTTPS: Traefik → guard HTTP:8080 → Sygnal HTTP:5000 → APNs/FCM HTTPS. Kontenery nie publikują 5000/8080. Guard wymaga zdarzenia i pokoju, zabrania pól treści/nadawcy/nazwy pokoju/type, usuwa dowolne payloady/tweaks i nadaje stały APNs alert `CIVCOM — Nowa wiadomość`. Android renderuje własny tekst ogólny. Rozszerzenie iOS również musi zachować tekst ogólny; sprawdzenie na zablokowanym urządzeniu jest osobną bramą. Zapytania jedynie z licznikami, bez event_id/room_id, są walidowane i otrzymują HTTP 200 `{"rejected":[]}` bez jakiejkolwiek wysyłki do Sygnal/Apple/Google. Akceptowane są standardowa forma i wąska forma rzeczywistego Synapse z id:"", type:null, sender:"" oraz kompatybilna type:""; niepuste preview lub złe liczniki pozostają zabronione. Badge forwarding jest wyłączony. Deduplikacja zdarzeń zapisuje wyłącznie SHA256(event_id,room_id,app_id,pushkey), status i czas w prywatnym cache SQLite. To lokalny stan gatewaya; Firebase służy projektowi FCM, a nie przechowywaniu rozmów. Kontrakt retry, limity i niepewne wyniki opisuje [reliability.md](docs/reliability.md).

`prepare` odmawia startu bez rzeczywistych dokumentów Firebase obu środowisk, zgodności projektów/pakietów, prawidłowego niezaszyfrowanego klucza RSA ≥2048 bitów FCM i P-256 APNs, KeyID, TeamID i zamkniętej listy źródeł. Klucze są czytane w pamięci; komunikat błędu jest stały. Walidacja kryptograficzna nie potwierdza IAM, uprawnień APNs, poprawności dostarczania ani zgodności podpisanego urządzenia — potrzebne rzeczywiste próby.

Instrukcja operacyjna: [runbook.md](docs/runbook.md). Dokumenty do zatwierdzenia: [privacy-draft.md](docs/privacy-draft.md), [store-release.md](docs/store-release.md), [acceptance.md](docs/acceptance.md). Nie publikować szablonów polityki lub plików association jako ukończonych.

Publiczne source tests: `python3 -m unittest discover -s tests -v` (Python z cryptography dla syntetycznych crypto fixtures; runtime pinned Sygnal ma tę zależność). Testy lokalne i source-derived kontrakt opisuje [notification-contract.md](docs/notification-contract.md). Pełna akceptacja native/APNs/FCM/deployment pozostaje odrębna.
