# CIVCOM iOS — powiązanie domeny Apple

Worker obsługuje wyłącznie GET/HEAD dwóch dokładnych HTTPS adresów AASA na civcom.soia.info. Zachowuje zastane powiązania Elementa i dodaje identyfikator development L643PDVV68.pl.gov.psp.civcom.dev oraz dokładną ścieżkę /oauth/ios/pl.gov.psp.civcom.dev. ID został odczytany z MachO entitlements rzeczywistego binarium symulatora. Produkcyjny identyfikator/prefix wymagają osobnego sprawdzenia podpisu.

Testy: node --test worker.test.mjs. Kontrola pakietu: wrangler deploy --dry-run --config wrangler.jsonc. Wdrożenie używa istniejącej autoryzacji Cloudflare i odpowiedniego konta operatora; bez nowych sekretów/baz. Worker/config/JSON przeszły niezależny review.

Wersja wdrożona 2026-10-05: ff87bd4b-ae75-47a1-9b2a-3301ebd95c8e. Oba origin endpointy odpowiadają JSON200 bez przekierowania, z nowym development ID. To nie dowodzi odświeżenia Apple CDN ani urządzenia lub logowania. Przy pierwszej próbie Apple CDN nadal serwował poprzednią kopię bez CIVCOM i native logowanie było zablokowane przed SSO.

Wycofanie: odłączyć wyłącznie dwie trasy HTTPS wymienione w wrangler.jsonc od tego workera, aby wróciły do istniejącego originu. Zachować pozostałe trasy i DNS. Nie kasować danych/keychain aplikacji dla odświeżania association. Apple cache oraz właściwe podpisy, account login i physical acceptance pozostają odrębnymi bramami.
