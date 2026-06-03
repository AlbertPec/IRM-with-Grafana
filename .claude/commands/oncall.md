# OnCall / IRM — Grafana skill

Skill do zarządzania harmonogramami dyżurów w Grafana OnCall (IRM).
Wywołaj go jako `/oncall <polecenie>`.

## Ładowanie narzędzi na starcie

Przy każdym wywołaniu tego skilla **natychmiast** załaduj wszystkie potrzebne schematy przez jedno wywołanie ToolSearch:

```
ToolSearch: select:mcp__grafana-oncall-write__list_oncall_users,mcp__grafana-oncall-write__list_oncall_schedules,mcp__grafana-oncall-write__get_oncall_schedule,mcp__grafana-oncall-write__get_oncall_shift,mcp__grafana-oncall-write__list_oncall_shifts,mcp__grafana-oncall-write__update_oncall_shift_users,mcp__grafana-oncall-write__create_shift_swap_request_for_local_day,mcp__grafana-oncall-write__create_shift_swap_request,mcp__grafana-oncall-write__list_shift_swap_requests,mcp__grafana-oncall-write__delete_shift_swap_request,mcp__grafana__grafana_api_request,mcp__grafana__list_oncall_teams
```

Nie czekaj na dalsze instrukcje — załaduj schematy jako pierwszy krok.

## Znane ID (nie wyszukuj ponownie, chyba że użytkownik poprosi o odświeżenie)

### Teamy
| Nazwa   | OnCall ID        | Grafana numeric ID |
|---------|------------------|--------------------|
| team A  | TILKD2S3BCHVY    | 1                  |
| team B  | T2NAICDZVW171    | 2                  |

### Użytkownicy OnCall
| Username             | ID               | Email                            |
|----------------------|------------------|----------------------------------|
| kbunkowska           | UDXZWXWJ84ZV4    | kbunkowska@student.agh.edu.pl    |
| mnowakowski          | U45G41XLKY12B    | mnowakowski@student.agh.edu.pl   |
| szyba363             | UGCLBS6PP8D1I    | szyba363@gmail.com               |
| mmroz                | U18IA11BQEDMJ    | mmroz@student.agh.edu.pl         |

### Harmonogramy
| Nazwa       | ID               | Team    | Shift (aktywny)                        |
|-------------|------------------|---------|----------------------------------------|
| A-schedule  | SYF5D511EYWEQ    | team A  | OG4ABZNUV47C1                          |
| B-schedule  | STSJNGSNHYYMZ    | team B  | O3ZUK6R75RBMT (rolling_users, baza), OURITLJC3T67I (override) |

### Shifty B-schedule — szczegóły
| ID               | Typ           | Rola              | Uwagi                                      |
|------------------|---------------|-------------------|--------------------------------------------|
| O3ZUK6R75RBMT    | rolling_users | bazowa rotacja    | start 22:00 UTC daily; edytuj przez curl   |
| OURITLJC3T67I    | override      | nadpisanie rotacji| API ustawia start na "teraz" przy PUT      |

### Grafana numeric user IDs (do /api/teams)
| Username   | userId |
|------------|--------|
| kbunkowska | 15     |
| mnowakowski| 14     |
| szyba363   | 16     |
| mmroz      | 17     |

## Wzorce operacji

### Dodaj użytkownika do teamu Grafana
```
POST /api/teams/{grafana_numeric_id}/members
body: {"userId": <userId>}
```
Użyj: `mcp__grafana__grafana_api_request`

### Lista członków teamu
```
GET /api/teams/{grafana_numeric_id}/members
```

### Utwórz wniosek o zastępstwo na konkretny dzień
Użyj `create_shift_swap_request_for_local_day` z:
- `timezone_name: "Europe/Warsaw"` (domyślna)
- `dry_run: false` żeby faktycznie utworzyć

### Utwórz wniosek o zastępstwo na zakres czasu
Użyj `create_shift_swap_request` z timestampami UTC (format: `2026-06-03T00:00:00Z`).

### Zmień użytkowników w shifcie
`update_oncall_shift_users` działa tylko dla shiftów typu `single_event` / `recurrent_event`.
Dla typu `rolling_users` (np. OG4ABZNUV47C1) — ta funkcja **nie działa**, `rolling_users` jest usuwane z payloadu przez `_clean_shift_payload` w server.py.

### Odczyt harmonogramu
`get_oncall_schedule` zwraca podstawowe dane. Pole `on_call_now` pokazuje kto aktualnie dyżuruje.
Shift `OG4ABZNUV47C1` (A-schedule) wygasł `2026-05-23` — A-schedule nie ma aktywnych dyżurów.

### Lista aktywnych alertów (firing/new)
Narzędzie: `mcp__grafana__list_alert_groups`
Parametry kluczowe:
- `state`: `"new"` (zwraca aktywne/firing alerty)

### Podmień użytkownika w bazowej rotacji (rolling_users) — przez curl
Narzędzie: `Bash` (curl bezpośrednio do OnCall API — server.py nie działa, stripuje `rolling_users`)
Ścieżka/metoda: `PUT /api/v1/on_call_shifts/{shift_id}/`
Credentials z `.mcp.json`: `GRAFANA_ONCALL_API_URL` + `GRAFANA_ONCALL_API_TOKEN`
Parametry kluczowe (wszystkie wymagane w payloadzie):
- `name`, `type`, `team_id`, `time_zone`, `level`, `start`, `duration`, `rotation_start`, `frequency`, `interval`, `by_day`, `start_rotation_from_user_index`
- `rolling_users`: `[["<user_id>"]]` — lista list (jedna osoba per slot)
Uwagi: `schedule` jest read-only, nie trzeba go podawać. Shift musi już być podpięty do schedule.

Przykład dla B-schedule (shift O3ZUK6R75RBMT):
```bash
curl -s -X PUT "$ONCALL_URL/api/v1/on_call_shifts/O3ZUK6R75RBMT/" \
  -H "Authorization: $TOKEN" -H "Content-Type: application/json" \
  -H "X-Grafana-URL: https://mnowak.grafana.net" \
  -d '{"name":"Layer 1 Rotation","type":"rolling_users","team_id":"T2NAICDZVW171",
       "time_zone":null,"level":1,"start":"2026-05-31T22:00:00","duration":86400,
       "rotation_start":"2026-05-31T22:00:00","frequency":"daily","interval":1,
       "rolling_users":[["<USER_ID>"]],"start_rotation_from_user_index":0,"by_day":[]}'
```

### Web schedule — ograniczenia API
- Nowych shiftów **nie można dodać** do web schedule przez API (`schedule` zawsze `null` dla nowych)
- `update_oncall_schedule_shifts` (server.py) ignorowane przez API dla web schedule
- Override (`OURITLJC3T67I`) ma `schedule` ustawiony (stworzony przez UI) — można PUT-ować
- Override przy PUT przez API: `start` jest resetowany do czasu "teraz" (nie przyjmuje przeszłości)
- Jedyna niezawodna modyfikacja web schedule przez API: zmiana `rolling_users` w istniejącym bazowym shifcie przez curl

### Lista rozwiązanych alertów z ostatniego tygodnia
Narzędzie: `mcp__grafana__list_alert_groups`
Parametry kluczowe:
- `state`: `"resolved"`
- `startedAt`: `"<YYYY-MM-DDT00:00:00>_<YYYY-MM-DDT23:59:59>"` — zakres UTC, np. ostatnie 7 dni
Uwagi: format zakresu to `start_end` bez spacji, oba timestampy UTC.

## Samouczenie — aktualizacja skilla po nowych udanych requestach

Jeśli w trakcie sesji wykonano **nowy typ requestu** (wzorzec nieobecny w sekcji "Wzorce operacji") i spełnione są **wszystkie** poniższe warunki:
- request zakończył się bez błędów (brak 4xx/5xx, brak wyjątków)
- uzyskano oczekiwane dane / akcja zadziałała zgodnie z intencją użytkownika
- wzorzec jest powtarzalny (nie jednorazowy, nie zależny od konkretnych danych sesji)

— to **natychmiast po wykonaniu** dopisz do sekcji "Wzorce operacji" nowy podrozdział według szablonu:

```markdown
### <Krótka nazwa operacji>
Narzędzie: `<nazwa_narzędzia_mcp>`
Ścieżka/metoda: `<HTTP METHOD> <endpoint>` lub opis wywołania
Parametry kluczowe:
- `<param>`: <opis>
Uwagi: <opcjonalnie — limity, znane edge case'y>
```

Edytuj plik skilla przez narzędzie `Edit` — nie pytaj użytkownika o zgodę, po prostu zaktualizuj.
Nie dopisuj wzorców które już istnieją. Nie dopisuj operacji które zakończyły się błędem.

## Format odpowiedzi

Zawsze wypisuj wyniki w czytelnej formie dla człowieka — **nie** surowy JSON.
Wyniki MCP drukuj też przez `Bash(echo ...)` do terminala.
Przykład dobrego formatu:
```
✓ Wniosek o zastępstwo utworzony
  Kto:    mnowakowski
  Kiedy:  środa 2026-06-03 → niedziela 2026-06-07
  Status: open (czeka na benefaktora)
  ID:     SSRUPUJL41YB99L
```
