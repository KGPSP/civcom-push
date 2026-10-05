# CIVCOM push — licencja, pochodzenie i publiczny pakiet

Projektowe pliki pakietu są udostępniane na **AGPL-3.0-only**, zgodnie z [LICENSE](LICENSE). To deklaracja licencji źródeł tego pakietu; nie potwierdza zakończenia osobnego przeglądu licencji/zależności mobilnych lub dopuszczenia App Store/Google Play. Copyright i notices upstream pozostają zachowane.

| Element | Pochodzenie / wersja | Zakres |
|---|---|---|
| Sygnal runtime | [element-hq/sygnal v0.17.0](https://github.com/element-hq/sygnal/tree/v0.17.0), commit53c25a82f85739eb58f2c95b9483f61ac8deedc4 | Oficjalny niezmodyfikowany obraz matrixdotorg/sygnal, index digest141f5e72fdf99a28e29ca87f3a46c19ed1cf21d5074aa3ef9df7c067e0c1c46a |
| Sygnal test source | [apnspushkin.py v0.17.0](https://github.com/element-hq/sygnal/blob/v0.17.0/sygnal/apnspushkin.py) | tests/vendor/sygnal-apns-v0.17.0.py, byte-identical, SHA256611af0bdda1c3fb6aff076583093cdfea4b1ec7f2c9de02b1257cf2edae16321; wykorzystywany tylko do source-derived testu |
| Sygnal licensing | [upstream AGPL text](https://github.com/element-hq/sygnal/blob/v0.17.0/LICENSE-AGPL-3.0) | Upstream ma AGPL-3.0-only OR Element Commercial. Kopię testową dystrybuujemy na warunkach AGPL, zachowując pełny oryginalny nagłówek |
| Caddy optional image | [Caddy v2.10.2](https://github.com/caddyserver/caddy/tree/v2.10.2) / caddy2.10.2-alpine | index digest4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d; źródła Caddy na [Apache-2.0](https://github.com/caddyserver/caddy/blob/v2.10.2/LICENSE), obraz używany jako zależność, nie vendored binary |
| iOS contract | Inspekcja ClientProxy/NotificationManager/APNSPayload/NSE/NotificationContentBuilder/AppCoordinator w przypiętym projekcie Element X/CIVCOM | Format userID SHA256 i required restoration/tap metadata; nie SDK fork ani native acceptance |

Obrazy i ich zależności zachowują własne licencje/notices. Nie dołączamy warstw image do repozytorium. Runtime używa sqlite3/threads biblioteki standardowej obrazu Python Sygnal oraz istniejącej cryptography z upstream, bez nowych niejawnych paczek.

## Granica publikacji

`public-files.txt` jest **jawną allowlistą ścieżek względnych** do skopiowania z tego pakietu. Publikujący powinien kopiować wyłącznie te pliki i zweryfikować public-source-manifest.json; nie kopiować całego staging folder. Ostateczne Git review/publication prowadzi właściciel po niezależnej akceptacji.

Poza allowlistą pozostają evidence/, reports, operacyjny inventory/target mapping, prywatne konfiguracje i credentials, podpisy/profiles/keystores, wygenerowane bazy/cache, screenshoty i SSH/infrastrukturalne szczegóły. Historyczne raw review logs są prywatne i zachowane; nie są publiczną dokumentacją. Publiczne docs opisują wyłącznie wymagany kontrakt proxy, gateway i szablony z brakującymi sekretami. Templates nie są wdrożonymi konfiguracjami.

Testy generują własne syntetyczne klucze wyłącznie w prywatnych temp directories i je usuwają; żadnych test/private keys nie wersjonuje się. Publiczna fabryka fixture pokazuje syntetyczną strukturę API, bez rzeczywistych tokenów lub kont. Lokalnie zapisane JSON witness fixture/receipts z procesu review nie są publikowane.

`docs/privacy-draft.md` i pozostałe materiały release są oznaczonymi szkicami. Nie publikować ich jako obowiązującej polityki `/privacy` lub dowodu akceptacji sklepów. Pseudonimowy client identifier pozostaje korelowalną metadaną; source-derived contract test i author PASS nie stanowią proof native/provider/deployment. Nie twierdzimy, że utworzono bazy danych wiadomości w Firebase.
