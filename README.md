# Handball-Tracker

Web-App zum Live-Mitzählen von Handball-Toren (Smartphone/Tablet), mit Spielbericht und PDF-Export.

- **Mannschaften** anlegen (Name, Kürzel, Trikotfarbe, optional Kader mit Nummern)
- **Live-Erfassung**: zwei große TOR-Buttons, die Spielzeit wird mit jedem Tor gespeichert
- **Spieluhr** synchron zum echten Spiel: Anpfiff/Anhalten/Weiter, Angleichen an die Hallenuhr (±1 s/±10 s oder mm:ss),
  automatischer Stopp am Halbzeitende, Team-Timeout hält die Uhr an. Die Uhr läuft serverseitig –
  mehrere Geräte zeigen denselben Stand (Server-Sent Events).
- Nach jedem Tor große **Bestätigung** mit Countdown und „Rückgängig“ (Dauer pro Gerät einstellbar, Standard 10 s)
- **Team-Logos** hochladen (PNG/JPG/WebP/SVG, wird im Browser verkleinert) – erscheinen in Live-Ansicht, Bericht und PDF
- Torschütze und 7m nachträglich zuordenbar, Ereignisse korrigier-/löschbar, „Letztes Tor“ rückgängig
- **Spielbericht**: Ergebnis, Halbzeitstand, Kennzahlen (höchste Führung, Läufe, Führungswechsel),
  Verlaufsdiagramm, Tore je 5 Minuten, Torschützen, Torfolge, Timeouts, Notizen – als **PDF** exportierbar

## Stack

FastAPI + SQLite (`/data/handball.db`), ReportLab für das PDF, Vanilla-JS-Frontend.

## Lokal starten

```bash
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload
```

## Deployment (Portainer)

GitHub Actions baut bei jedem Push auf `main` das Image `ghcr.io/mbay-odw/handball-tracker:latest`.
Stack in Portainer aus `docker-compose.yml` anlegen bzw. mit „Re-pull image“ aktualisieren.
Erreichbar unter `https://handball.bay-ram.de` (Traefik-Router ``Host(`handball.bay-ram.de`)``, Authelia davor).
