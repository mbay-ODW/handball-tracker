# Betrieb & Deployment

Wie die App auf dem Server läuft, wie man sie aktualisiert, sichert und bei Problemen untersucht.

- [Überblick](#überblick)
- [Portainer-Stack](#portainer-stack)
- [Update einspielen](#update-einspielen)
- [Rollback](#rollback)
- [Backup & Wiederherstellung](#backup--wiederherstellung)
- [Monitoring & Logs](#monitoring--logs)
- [Fehlersuche](#fehlersuche)
- [Entwicklung](#entwicklung)

---

## Überblick

```
 Handy/Tablet ──HTTPS──▶ Cloudflare ──▶ Traefik ──▶ Authelia (Login) ──▶ handball-tracker:8000
                                        (websecure,                       FastAPI + SQLite
                                         *.bay-ram.de-Zertifikat)          /data ⇄ /mnt/apps/handball-tracker/data

 git push main ──▶ GitHub Actions ──▶ ghcr.io/mbay-odw/handball-tracker:latest / :sha-<commit> ──▶ Portainer „Re-pull“
```

| | |
|---|---|
| **URL** | https://handball.bay-ram.de |
| **Repo** | https://github.com/mbay-ODW/handball-tracker |
| **Image** | `ghcr.io/mbay-odw/handball-tracker:latest` (öffentlich, kein Registry-Login nötig) |
| **Portainer** | Stack `handball-tracker` (ID 66), Environment `primary` |
| **Container** | `handball-tracker`, Port 8000 (nur intern) |
| **Daten** | `/mnt/apps/handball-tracker/data/handball.db` (SQLite im WAL-Modus) |
| **Traefik-Router** | `handball` – ``Host(`handball.bay-ram.de`)`` |

## Portainer-Stack

Die Datei [`docker-compose.yml`](../docker-compose.yml) ist 1:1 der Stack. Wichtige Teile:

```yaml
image: ${IMAGE:-ghcr.io/mbay-odw/handball-tracker:latest}   # per Stack-Variable IMAGE überschreibbar
volumes:
  - /mnt/apps/handball-tracker/data:/data:rw               # SQLite-Datenbank inkl. Logos
labels:
  - traefik.http.routers.handball.rule=Host(`handball.bay-ram.de`)
  - traefik.http.routers.handball.entrypoints=websecure
  - traefik.http.routers.handball.tls.certresolver=mydnschallenge
  - traefik.http.routers.handball.middlewares=middlewares-rate-limit@file,middlewares-authelia@file,middlewares-secure-headers@file
  - traefik.http.services.handball.loadbalancer.server.port=8000
```

- **Authelia** schützt alles (`middlewares-authelia@file`). Wer die App nutzen darf, regelt Authelia.
- **Rate-Limit** aus `/rules/middleware.yml` (300/s, Burst 1000) – für die App unkritisch.
- **Healthcheck** im Image: `GET /healthz` alle 30 s.
- Umgebungsvariablen: `DATA_DIR` (Standard `/data`), `TZ` (für Zeitstempel im PDF, Standard `Europe/Berlin`).

## Update einspielen

1. Änderung auf `main` pushen → **GitHub Actions** baut in ~30 s das Image
   (`latest` und `sha-<commit>`). Reine Doku-Änderungen (`docs/**`, `*.md`) lösen keinen Build aus.
2. **Prüfen, dass kein Spiel läuft** – ein Neustart dauert nur Sekunden, aber genau dann getippte Tore/Rücknahmen
   landen im Leeren (die App wiederholt Rücknahmen zwar automatisch, sicher ist sicher):

   ```bash
   docker exec handball-tracker python -c "import sqlite3; c=sqlite3.connect('/data/handball.db'); \
     print(c.execute(\"select id, home_name, away_name, clock_running from games where status!='finished'\").fetchall())"
   ```

   Leere Liste `[]` bzw. keine laufende Uhr (`clock_running = 0`) → Update ist unkritisch.
3. **Portainer** → *Stacks* → `handball-tracker` → *Editor* → **Update the stack** mit Haken bei
   **„Re-pull image and redeploy“**.
4. Kontrolle: https://handball.bay-ram.de neu laden. Auf den Handys die App einmal schließen und neu öffnen
   (CSS/JS werden über `?v=` in `index.html` versioniert – bei Frontend-Änderungen dort hochzählen).

**Alternative ohne GitHub Actions:** Das Repo ist öffentlich, Docker kann direkt daraus bauen:

```bash
docker build -t handball-tracker:latest https://github.com/mbay-ODW/handball-tracker.git#main
# danach im Stack IMAGE=handball-tracker:latest setzen
```

## Rollback

Jeder Build ist zusätzlich als `ghcr.io/mbay-odw/handball-tracker:sha-<commit>` verfügbar.

1. Commit-Hash der guten Version aus der [Commit-Liste](https://github.com/mbay-ODW/handball-tracker/commits/main) holen.
2. Im Stack die Variable `IMAGE=ghcr.io/mbay-odw/handball-tracker:sha-<voller-hash>` setzen → *Update the stack*.
3. Zurück auf aktuell: Variable wieder entfernen.

Die Datenbank ist abwärtskompatibel: Neue Spalten werden nur ergänzt, nie entfernt.

## Backup & Wiederherstellung

Alles steckt in **einer Datei**: `/mnt/apps/handball-tracker/data/handball.db` (Mannschaften, Logos, Spiele, Tore).
Wegen WAL-Modus nicht einfach im laufenden Betrieb kopieren, sondern die SQLite-Backup-Funktion nutzen:

```bash
docker exec handball-tracker python -c "import sqlite3; \
  sqlite3.connect('/data/handball.db').backup(sqlite3.connect('/data/backup-$(date +%F).db'))"
```

→ landet als `/mnt/apps/handball-tracker/data/backup-JJJJ-MM-TT.db` auf dem Host und kann von dort ins reguläre Backup (Nextcloud/TrueNAS-Snapshot).

**Wiederherstellen:** Stack stoppen → `handball.db` durch das Backup ersetzen (und `handball.db-wal`/`-shm` löschen) → Stack starten.

## Monitoring & Logs

- **Healthcheck:** `https://handball.bay-ram.de/healthz` (hinter Authelia) bzw. intern `http://handball-tracker:8000/healthz` – gut für Uptime-Kuma.
- **App-Logs:** Dozzle oder `docker logs -f handball-tracker` (Uvicorn-Access-Log: jede Anfrage mit Status).
- **Traefik-Access-Log** (zeigt auch Fehler, die die App gar nicht erreicht haben, z. B. 502 bei Neustart):

  ```bash
  docker exec traefik sh -c "tail -c 50000000 /traefik.log | grep handball.bay-ram.de | grep -vE '\" (200|304) '"
  ```

## Fehlersuche

| Symptom | Ursache / Lösung |
|---|---|
| **502 Bad Gateway** | Container startet gerade neu oder ist abgestürzt → `docker ps`, Logs prüfen. Kurz nach einem Update normal. |
| **Tor/Rücknahme „fehlgeschlagen“** im Traefik-Log als `502` | Siehe oben – fiel mit einem Neustart zusammen. Update-Regel (kein laufendes Spiel) beachten. |
| **Live-Stand aktualisiert sich nicht** | Verbindungspunkt rot? Die App verbindet sich nach 3 s neu und holt zusätzlich alle 30 s den Stand. Sonst Seite neu laden. |
| **Uhr springt nach Neuladen** | Normal, falls das Gerät vorher falsch synchronisiert war – maßgeblich ist die Serveruhr. |
| **Weiterleitung auf Authelia-Login** | Session abgelaufen → neu anmelden. |
| **PDF: Zeitstempel falsch** | `TZ` im Stack prüfen. |
| **Logo-Upload „zu groß“** | max. 1,5 MB nach Verkleinerung – sehr große SVGs vorher als PNG exportieren. |
| **iPhone vibriert nicht** | *Einstellungen → Töne & Haptik → Systemhaptik* an; App neu öffnen; *Rückmeldung testen* muss „iOS-Schalter (Fingertipp)“ zeigen. |

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload     # http://localhost:8000
```

- Kein Build-Schritt fürs Frontend – `app/static/*` direkt bearbeiten, Browser neu laden.
- Nach Frontend-Änderungen die Versionsnummern `?v=` in `app/static/index.html` erhöhen (Cache der Handys).
- Neue DB-Spalten in `db.SCHEMA` **und** in `db._migrate` eintragen.
- Commit-Nachrichten: `feat: …`, `fix: …`, `docs: …`, `chore: …`.

**Wie die iPhone-Vibration funktioniert** (falls man daran schraubt): Safari hat keine Vibrations-API.
iOS spielt aber Systemhaptik, wenn der **Finger** einen `<input type="checkbox" switch>` umlegt.
Deshalb sind TOR-Tasten, *Rückgängig* und *Rückmeldung testen* `<label>`-Elemente mit einem eingebetteten,
unsichtbaren Switch (`hsw()` / `bindTap()` in `app.js`). Programmatisches `label.click()` reicht auf aktuellem iOS **nicht**.
Android nutzt `navigator.vibrate()`.
