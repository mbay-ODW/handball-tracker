# REST-API

Die Web-App nutzt ausschließlich diese API – alles, was die Oberfläche kann, geht auch per Skript, n8n oder `curl`.

- **Basis-URL:** `https://handball.bay-ram.de` (bzw. intern `http://handball-tracker:8000`)
- **Format:** JSON (`Content-Type: application/json`), Zeiten in **Millisekunden**
- **Fehler:** HTTP-Status + `{"detail": "Meldung"}` (z. B. `404`, `409`, `422`)

> ### 🔐 Zugriff
> Die öffentliche Adresse liegt hinter **Authelia**. Im Browser funktioniert die API, weil man dort angemeldet ist.
> Für Skripte/n8n gibt es zwei Wege:
> 1. **Intern aus dem Docker-Netz** `traefik`: `http://handball-tracker:8000/api/...` – ohne Authelia (z. B. aus dem n8n-Container, wenn der im selben Netz hängt).
> 2. Mit einer **Authelia-Session** (Cookie `authelia_session`) gegen die öffentliche Adresse.
>
> Die App selbst hat bewusst keine eigene Benutzerverwaltung.

**Inhalt**

- [Mannschaften](#mannschaften) · [Logos](#logos) · [Kader](#kader)
- [Spiele](#spiele) · [Spieluhr](#spieluhr) · [Tore & Timeouts](#tore--timeouts) · [Ereignisse bearbeiten](#ereignisse-bearbeiten)
- [Live-Stream](#live-stream-sse) · [Bericht & PDF](#bericht--pdf)
- [Beispiele](#beispiele) · [Datenmodell](#datenmodell)

---

## Mannschaften

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| `GET` | `/api/teams` | – | Liste, inkl. `player_count`, `logo_v` |
| `POST` | `/api/teams` | `TeamIn` | Mannschaft inkl. `players` |
| `GET` | `/api/teams/{id}` | – | Mannschaft inkl. `players` |
| `PUT` | `/api/teams/{id}` | `TeamIn` | Mannschaft |
| `DELETE` | `/api/teams/{id}` | – | `{"ok": true}` – Spiele bleiben erhalten (Namens-/Farb-/Logo-Schnappschuss) |

**`TeamIn`**

| Feld | Typ | Pflicht | Regeln |
|---|---|---|---|
| `name` | string | ✔ | 1–80 Zeichen |
| `short` | string | | max. 12 Zeichen |
| `color` | string | | `#rrggbb`, Standard `#1e6fd9` |

```json
// POST /api/teams
{ "name": "TV Grünwald", "short": "TVG", "color": "#1e6fd9" }

// → 200
{ "id": 1, "name": "TV Grünwald", "short": "TVG", "color": "#1e6fd9",
  "created_at": 1790496711707, "logo_v": 0, "players": [] }
```

`logo_v` > 0 bedeutet: Logo vorhanden (der Wert dient als Cache-Buster in der Logo-URL).

## Logos

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| `PUT` | `/api/teams/{id}/logo` | `{"data_url": "data:image/png;base64,…"}` | Mannschaft |
| `DELETE` | `/api/teams/{id}/logo` | – | Mannschaft |
| `GET` | `/api/teams/{id}/logo` | – | Bild (`image/png` / `image/jpeg`), `404` wenn keins |
| `GET` | `/api/games/{id}/logo/{home\|away}` | – | Logo des Spiels (Schnappschuss, sonst aktuelles Team-Logo) |

- Erlaubt: **PNG oder JPEG** als Data-URL, max. **1,5 MB** (`413` wenn größer, `422` bei anderem Format).
- Die Web-App verkleinert Bilder vorher auf max. 400 px und schickt PNG – bei Skripten am besten ebenso.

## Kader

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| `POST` | `/api/teams/{id}/players` | `{"number": "7", "name": "Müller"}` | Spieler |
| `PUT` | `/api/players/{id}` | `{"number": "7", "name": "Müller"}` | Spieler |
| `DELETE` | `/api/players/{id}` | – | `{"ok": true}` |

`number` (max. 4 Zeichen) oder `name` (max. 80) – mindestens eins muss gesetzt sein.

---

## Spiele

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| `GET` | `/api/games` | – | Liste (neueste zuerst) inkl. `score` |
| `POST` | `/api/games` | `GameIn` | **Spielstand** |
| `GET` | `/api/games/{id}` | – | **Spielstand** |
| `PATCH` | `/api/games/{id}` | `competition`, `venue`, `game_date`, `notes` (alle optional) | Spielstand |
| `DELETE` | `/api/games/{id}` | – | `{"ok": true}` (inkl. aller Ereignisse) |
| `POST` | `/api/games/{id}/next-half` | – | Spielstand · `409` wenn letzte Halbzeit |
| `POST` | `/api/games/{id}/finish` | – | Spielstand, `status = "finished"` |
| `POST` | `/api/games/{id}/reopen` | – | Spielstand, `status = "live"` |

**`GameIn`**

| Feld | Typ | Standard | Regeln |
|---|---|---|---|
| `home_team_id` | int | – | Pflicht |
| `away_team_id` | int | – | Pflicht, ≠ Heim |
| `competition` | string | `""` | max. 120 |
| `venue` | string | `""` | max. 120 |
| `game_date` | string | `""` | ISO, z. B. `2026-09-27T18:00` |
| `half_minutes` | int | 30 | 1–60 |
| `halves` | int | 2 | 1–4 |

### Der Spielstand (`GameState`)

Fast alle Spiel-Endpunkte liefern das komplette aktuelle Bild zurück:

```json
{
  "game":   { "id": 3, "home_name": "TV Grünwald", "away_name": "HSG Süd-Ost",
              "home_color": "#1e6fd9", "away_color": "#ffffff",
              "competition": "Kreisliga", "venue": "Sporthalle Nord", "game_date": "2026-09-27T18:00",
              "half_minutes": 30, "halves": 2, "status": "live", "notes": "",
              "home_logo_v": 5120, "away_logo_v": 0, "...": "..." },
  "events": [ { "id": 41, "type": "goal", "side": "home", "half": 1, "game_ms": 95000,
                "player_id": 7, "player_number": "7", "player_name": "Müller", "seven_m": 0 } ],
  "score":  { "home": 5, "away": 3 },
  "rosters": { "home": [ { "id": 7, "number": "7", "name": "Müller" } ], "away": [] },
  "clock":  { "half": 1, "halves": 2, "half_ms": 1800000, "running": true,
              "elapsed_ms": 742000, "anchor_ms": 1790500000000,
              "game_ms": 744310, "half_ended": false },
  "server_time": 1790500002310,
  "version": 17
}
```

- `status`: `planned` → `live` (beim ersten Anpfiff oder Tor) → `finished`
- Ereignis-`type`: `goal`, `timeout`, `half_end`

## Spieluhr

`POST /api/games/{id}/clock`

| Body | Wirkung |
|---|---|
| `{"action": "start"}` | Uhr läuft (`409`, wenn die Halbzeit abgelaufen ist) |
| `{"action": "pause"}` | Uhr steht |
| `{"action": "set", "game_ms": 744000}` | Uhr auf Gesamt-Spielzeit setzen (wird auf die aktuelle Halbzeit begrenzt) |

**So rechnet die Uhr** – die aktuelle Spielzeit ergibt sich aus:

```
im_halbzeit = elapsed_ms + (running ? jetzt − anchor_ms : 0)      // gedeckelt auf half_ms
game_ms     = (half − 1) × half_ms + im_halbzeit
```

Clients rechnen mit `server_time` einen Versatz zur eigenen Uhr aus und zählen lokal weiter – so zeigen alle Geräte dieselbe Zeit.
Erreicht die Uhr `half_ms`, stoppt der Server sie und legt ein `half_end`-Ereignis an.

## Tore & Timeouts

| Methode | Pfad | Body |
|---|---|---|
| `POST` | `/api/games/{id}/goal` | `{"side": "home", "game_ms": 744000, "seven_m": false}` |
| `POST` | `/api/games/{id}/timeout` | `{"side": "away", "game_ms": 1200000}` |

- `game_ms` ist optional – ohne Angabe nimmt der Server die aktuelle Uhrzeit. Die Web-App schickt die Zeit, die beim Tippen auf dem Display stand.
- Die Zeit wird auf die aktuelle Halbzeit begrenzt.
- `goal` liefert zusätzlich `created_event_id` (für Torschützen-Zuordnung oder Rückgängig).
- `timeout` hält die Uhr an.

## Ereignisse bearbeiten

| Methode | Pfad | Body |
|---|---|---|
| `PATCH` | `/api/events/{id}` | beliebig kombinierbar: `player_id`, `clear_player: true`, `seven_m`, `game_ms` |
| `DELETE` | `/api/events/{id}` | – (z. B. „Rückgängig“) · `404`, wenn schon gelöscht |

Beim Setzen von `player_id` werden Nummer und Name als Schnappschuss ins Ereignis kopiert.

## Live-Stream (SSE)

`GET /api/games/{id}/stream` – `text/event-stream`

- Bei jeder Änderung kommt ein `data:`-Event mit dem kompletten **Spielstand** (siehe oben).
- Alle 15 s ein Kommentar `: ping` als Keep-alive.
- Wird das Spiel gelöscht: `event: gone`.

```js
const es = new EventSource("/api/games/3/stream");
es.onmessage = (m) => console.log(JSON.parse(m.data).score);
```

## Bericht & PDF

| Methode | Pfad | Antwort |
|---|---|---|
| `GET` | `/api/games/{id}/report` | Auswertung als JSON |
| `GET` | `/api/games/{id}/report.pdf` | PDF-Download `Spielbericht_<Heim>_vs_<Gast>_<Datum>.pdf` |

Das Report-JSON enthält u. a. `score`, `halves` (Tore je Halbzeit), `cumulative` (Zwischenstände), `goals` (mit laufendem Stand),
`scorers` (je Seite), `intervals` (Tore je 5 Min.), `timeouts`, `progression` (für das Diagramm) und
`stats` (`lead_changes`, `max_lead`, `best_run`, `seven_m`).

## Sonstiges

| Pfad | Zweck |
|---|---|
| `GET /healthz` | `{"ok": true}` – für Docker-Healthcheck/Uptime-Kuma |

---

## Beispiele

### Mannschaft mit Logo und Kader anlegen (Bash)

```bash
API=http://handball-tracker:8000   # intern, ohne Authelia

TEAM=$(curl -s -X POST $API/api/teams -H 'Content-Type: application/json' \
  -d '{"name":"TV Grünwald","short":"TVG","color":"#1e6fd9"}' | jq -r .id)

# Logo (PNG) als Data-URL hochladen
curl -s -X PUT $API/api/teams/$TEAM/logo -H 'Content-Type: application/json' \
  -d "{\"data_url\":\"data:image/png;base64,$(base64 -w0 logo.png)\"}" > /dev/null

# Kader
for p in "3:Weber" "7:Müller" "11:Özdemir"; do
  curl -s -X POST $API/api/teams/$TEAM/players -H 'Content-Type: application/json' \
    -d "{\"number\":\"${p%%:*}\",\"name\":\"${p#*:}\"}" > /dev/null
done
```

### Kader aus CSV importieren (Python)

```python
import csv, requests

API = "http://handball-tracker:8000"
team = requests.post(f"{API}/api/teams", json={"name": "HSG Süd-Ost", "color": "#ffffff"}).json()

with open("kader.csv", newline="", encoding="utf-8") as f:   # Spalten: nummer;name
    for row in csv.DictReader(f, delimiter=";"):
        requests.post(f"{API}/api/teams/{team['id']}/players",
                      json={"number": row["nummer"], "name": row["name"]}).raise_for_status()
```

### Spiel anlegen und PDF holen

```bash
GAME=$(curl -s -X POST $API/api/games -H 'Content-Type: application/json' \
  -d '{"home_team_id":1,"away_team_id":2,"competition":"Kreisliga","game_date":"2026-10-04T17:00"}' \
  | jq -r .game.id)

# … nach dem Spiel
curl -s -o bericht.pdf $API/api/games/$GAME/report.pdf
```

---

## Datenmodell

SQLite, Datei `$DATA_DIR/handball.db` (im Container `/data/handball.db`).

```
teams     id, name, short, color, logo (BLOB), created_at
players   id, team_id → teams, number, name
games     id, home/away_team_id, home/away_name, home/away_color, home/away_logo (Schnappschüsse),
          competition, venue, game_date, half_minutes, halves, status, notes,
          clock_half, clock_running, clock_elapsed_ms, clock_anchor_ms, created_at, finished_at
events    id, game_id → games, type (goal|timeout|half_end), side (home|away), half, game_ms,
          player_id, player_number, player_name, seven_m, created_at
```

Neue Spalten werden beim Start automatisch nachgerüstet (`db._migrate`), bestehende Daten bleiben erhalten.
