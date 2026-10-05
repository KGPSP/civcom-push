# CIVCOM — materiały sklepowe i bramy wydania

DRAFT. Wydawca: KG PSP. Nazwa: CIVCOM. Tożsamość produkcyjna: `pl.gov.psp.civcom`. Forki publiczne: [Android](https://github.com/KGPSP/civcom-android), [iOS](https://github.com/KGPSP/civcom-ios). Linki źródeł użytkownik ma móc otworzyć z aplikacji; dla każdego binarium trzeba wskazać odpowiadający commit/source i instrukcje budowy.

Propozycja opisu do sprawdzenia po akceptacji urządzeń: „CIVCOM umożliwia uprawnionym użytkownikom komunikację indywidualną i grupową, wysyłanie obrazów i plików oraz zarządzanie weryfikacją i odzyskiwaniem urządzeń. Dostęp do kont nadaje administrator.” Nie deklarować gotowej produkcyjnej niezawodności, formalnych certyfikatów bezpieczeństwa ani zgodności prawnej bez dowodów. Nie nazywać aplikacji kanałem alarmowym/zamiennikiem numerów alarmowych. W materiałach jasno wyjaśnić konieczność posiadania konta, mimo publicznego pobierania.

Przed złożeniem do sklepów:

1. Prawnik/licensing owner zatwierdza dystrybucję Element X i wszystkich zależności w każdym sklepie; zachować upstream historię, notices/licencje i odpowiedni source. Sygnal v0.17.0 ma [AGPL-3.0-only / licencję komercyjną](https://github.com/element-hq/sygnal/blob/v0.17.0/LICENSE-AGPL-3.0); sam link do repozytorium nie jest potwierdzeniem spełnienia wszystkich obowiązków dla konkretnego builda. Własność CIVCOM artwork/znaków i użycie nazw/atrybucji zatwierdzić osobno. Zgodność dystrybucji ze sklepami pozostaje blokadą, brak automatycznego rozstrzygnięcia.
2. Ustalić rzeczywiste podpisy, Play App Signing SHA256 (oddzielnie upload key) i iOS provisioning/entitlements wraz z NSE/share/app groups. TeamID KG PSP `L643PDVV68` jest znany; APNs KeyID/P8 i rzeczywiste profile nadal wymagane. Zarejestrować prawdziwe Firebase aplikacje i nadać minimalne role kontu gatewaya, odrębne od klienta.
3. Zatwierdzić i opublikować finalne privacy/terms/support/source links na `civcom.soia.info`. Obecne szkice i placeholdery nie stanowią gotowych polityk.
4. Uzupełnić App Privacy i Google Data safety na podstawie rzeczywistego data inventory (konto, urządzenie, push, metadata, pliki, logi, wszystkie SDK) i procesów administratora; sprawdzić wymagania usuwania kont w aktualnych formularzach i potrzebę dostępu reviewerów do konta administratora testowego. Nie udostępniać kont operacyjnych.
5. Przygotować prawdziwe zrzuty ekranu podpisanego builda z danymi syntetycznymi, opis uprawnień, wiek/kategorie i instrukcję review. Publiczna instalacja nie daje prawa do utworzenia konta; instrukcja sklepu musi to wyjaśnić.
6. Przejść niezależny przegląd, komplet acceptance.md i podpisać pilot. TestFlight push korzysta z APNs production pomimo testowego kanału dystrybucji. Przygotować rollback i operatora; nie wysyłać do sklepu po samych testach autora.

Brakujące decyzje: zatwierdzenie licencji/dystrybucji, retencja/procesy/dane kontaktowe, operatorzy, konta review, finalne zgody i podpisane binaria. Złożenie do Apple/Google, akceptacja sklepów oraz publiczne udostępnienie: NOT_RUN. Koordynator prowadzi GitHub/deployment/publication; ten pakiet nie wykonuje tych czynności.
