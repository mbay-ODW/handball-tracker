"""Handball-Tracker: Tore live mitzählen, Spielzeit synchron führen, Spielbericht als PDF."""
import asyncio
import base64
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .report import build_report
from .pdf import render_pdf

STATIC_DIR = Path(__file__).parent / "static"
SIDES = ("home", "away")

app = FastAPI(title="Handball-Tracker", docs_url=None, redoc_url=None)

# Versionszähler pro Spiel – SSE-Clients bekommen bei jeder Änderung den neuen Stand.
_versions: dict[int, int] = {}


def bump(game_id: int) -> None:
    _versions[game_id] = _versions.get(game_id, 0) + 1


# ---------------------------------------------------------------- Modelle


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    short: str = Field(default="", max_length=12)
    color: str = Field(default="#1e6fd9", pattern=r"^#[0-9a-fA-F]{6}$")


class LogoIn(BaseModel):
    # PNG/JPEG als Data-URL (wird im Browser bereits verkleinert)
    data_url: str = Field(max_length=3_000_000)


MAX_LOGO_BYTES = 1_500_000


class PlayerIn(BaseModel):
    number: str = Field(default="", max_length=4)
    name: str = Field(default="", max_length=80)


class GameIn(BaseModel):
    home_team_id: int
    away_team_id: int
    competition: str = Field(default="", max_length=120)
    venue: str = Field(default="", max_length=120)
    game_date: str = Field(default="", max_length=32)
    half_minutes: int = Field(default=30, ge=1, le=60)
    halves: int = Field(default=2, ge=1, le=4)


class GameUpdate(BaseModel):
    competition: str | None = Field(default=None, max_length=120)
    venue: str | None = Field(default=None, max_length=120)
    game_date: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=4000)


class ClockIn(BaseModel):
    action: str = Field(pattern=r"^(start|pause|set)$")
    game_ms: float | None = None


class GoalIn(BaseModel):
    side: str = Field(pattern=r"^(home|away)$")
    game_ms: float | None = None
    seven_m: bool = False


class TimeoutIn(BaseModel):
    side: str = Field(pattern=r"^(home|away)$")
    game_ms: float | None = None


class EventUpdate(BaseModel):
    player_id: int | None = None
    clear_player: bool = False
    seven_m: bool | None = None
    game_ms: float | None = None


# ---------------------------------------------------------------- Uhr


def half_len(g: dict) -> int:
    return g["half_minutes"] * 60_000


def elapsed_in_half(g: dict, now: int) -> int:
    e = g["clock_elapsed_ms"]
    if g["clock_running"]:
        e += now - g["clock_anchor_ms"]
    return max(0, min(e, half_len(g)))


def current_game_ms(g: dict, now: int) -> int:
    return (g["clock_half"] - 1) * half_len(g) + elapsed_in_half(g, now)


def clamp_to_half(g: dict, game_ms: float) -> int:
    lo = (g["clock_half"] - 1) * half_len(g)
    return max(lo, min(int(game_ms), lo + half_len(g)))


def normalize(g: dict, now: int) -> bool:
    """Stoppt die Uhr automatisch, wenn die Halbzeit abgelaufen ist."""
    if not g["clock_running"]:
        return False
    raw = g["clock_elapsed_ms"] + now - g["clock_anchor_ms"]
    if raw < half_len(g):
        return False
    with db.transaction() as c:
        c.execute(
            "UPDATE games SET clock_running=0, clock_elapsed_ms=? WHERE id=?",
            (half_len(g), g["id"]),
        )
        c.execute(
            "INSERT INTO events(game_id,type,side,half,game_ms,created_at) VALUES (?,?,?,?,?,?)",
            (g["id"], "half_end", None, g["clock_half"], g["clock_half"] * half_len(g), now),
        )
    g["clock_running"] = 0
    g["clock_elapsed_ms"] = half_len(g)
    bump(g["id"])
    return True


def decode_logo(data_url: str) -> bytes:
    m = re.match(r"^data:image/(png|jpeg);base64,(.+)$", data_url.strip(), re.S)
    if not m:
        raise HTTPException(422, "Logo muss PNG oder JPEG sein")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        raise HTTPException(422, "Logo konnte nicht gelesen werden")
    if len(raw) > MAX_LOGO_BYTES:
        raise HTTPException(413, "Logo zu groß (max. 1,5 MB)")
    if not (raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8")):
        raise HTTPException(422, "Logo muss PNG oder JPEG sein")
    return raw


def logo_mime(raw: bytes) -> str:
    return "image/png" if raw.startswith(b"\x89PNG") else "image/jpeg"


def team_public(t: dict) -> dict:
    logo = t.pop("logo", None)
    t["logo_v"] = (len(logo) if logo else 0)
    return t


def game_logo(g: dict, side: str) -> bytes | None:
    """Logo-Schnappschuss des Spiels, sonst aktuelles Logo der Mannschaft."""
    raw = g.get(f"{side}_logo")
    if raw:
        return raw
    tid = g.get(f"{side}_team_id")
    if tid:
        t = db.one("SELECT logo FROM teams WHERE id=?", (tid,))
        if t and t["logo"]:
            return t["logo"]
    return None


def game_public(g: dict) -> dict:
    for side in SIDES:
        raw = game_logo(g, side)
        g.pop(f"{side}_logo", None)
        g[f"{side}_logo_v"] = len(raw) if raw else 0
    return g


def load_game(game_id: int) -> dict:
    g = db.one("SELECT * FROM games WHERE id=?", (game_id,))
    if not g:
        raise HTTPException(404, "Spiel nicht gefunden")
    normalize(g, db.now_ms())
    return g


def game_state(game_id: int) -> dict:
    g = load_game(game_id)
    now = db.now_ms()
    events = db.query("SELECT * FROM events WHERE game_id=? ORDER BY game_ms, id", (game_id,))
    score = {s: sum(1 for e in events if e["type"] == "goal" and e["side"] == s) for s in SIDES}
    rosters = {}
    for side in SIDES:
        tid = g[f"{side}_team_id"]
        rosters[side] = (
            db.query(
                "SELECT id, number, name FROM players WHERE team_id=? "
                "ORDER BY CAST(number AS INTEGER), number, name",
                (tid,),
            )
            if tid
            else []
        )
    half_ended = elapsed_in_half(g, now) >= half_len(g)
    return {
        "game": game_public(dict(g)),
        "events": events,
        "score": score,
        "rosters": rosters,
        "clock": {
            "half": g["clock_half"],
            "halves": g["halves"],
            "half_ms": half_len(g),
            "running": bool(g["clock_running"]),
            "elapsed_ms": g["clock_elapsed_ms"],
            "anchor_ms": g["clock_anchor_ms"],
            "game_ms": current_game_ms(g, now),
            "half_ended": half_ended,
        },
        "server_time": now,
        "version": _versions.get(game_id, 0),
    }


# ---------------------------------------------------------------- Teams


@app.get("/api/teams")
def list_teams():
    teams = [team_public(t) for t in db.query("SELECT * FROM teams ORDER BY name COLLATE NOCASE")]
    counts = {r["team_id"]: r["n"] for r in db.query("SELECT team_id, COUNT(*) n FROM players GROUP BY team_id")}
    for t in teams:
        t["player_count"] = counts.get(t["id"], 0)
    return teams


@app.post("/api/teams")
def create_team(body: TeamIn):
    tid = db.execute(
        "INSERT INTO teams(name, short, color, created_at) VALUES (?,?,?,?)",
        (body.name.strip(), body.short.strip(), body.color, db.now_ms()),
    )
    return get_team(tid)


@app.get("/api/teams/{team_id}")
def get_team(team_id: int):
    t = db.one("SELECT * FROM teams WHERE id=?", (team_id,))
    if not t:
        raise HTTPException(404, "Mannschaft nicht gefunden")
    team_public(t)
    t["players"] = db.query(
        "SELECT * FROM players WHERE team_id=? ORDER BY CAST(number AS INTEGER), number, name", (team_id,)
    )
    return t


@app.put("/api/teams/{team_id}")
def update_team(team_id: int, body: TeamIn):
    get_team(team_id)
    db.execute(
        "UPDATE teams SET name=?, short=?, color=? WHERE id=?",
        (body.name.strip(), body.short.strip(), body.color, team_id),
    )
    return get_team(team_id)


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int):
    get_team(team_id)
    # Spiele behalten ihren Namens-Schnappschuss, nur die Verknüpfung wird gelöst.
    with db.transaction() as c:
        c.execute("UPDATE games SET home_team_id=NULL WHERE home_team_id=?", (team_id,))
        c.execute("UPDATE games SET away_team_id=NULL WHERE away_team_id=?", (team_id,))
        c.execute("DELETE FROM players WHERE team_id=?", (team_id,))
        c.execute("DELETE FROM teams WHERE id=?", (team_id,))
    return {"ok": True}


@app.put("/api/teams/{team_id}/logo")
def set_team_logo(team_id: int, body: LogoIn):
    get_team(team_id)
    db.execute("UPDATE teams SET logo=? WHERE id=?", (decode_logo(body.data_url), team_id))
    return get_team(team_id)


@app.delete("/api/teams/{team_id}/logo")
def delete_team_logo(team_id: int):
    get_team(team_id)
    db.execute("UPDATE teams SET logo=NULL WHERE id=?", (team_id,))
    return get_team(team_id)


@app.get("/api/teams/{team_id}/logo")
def team_logo(team_id: int):
    t = db.one("SELECT logo FROM teams WHERE id=?", (team_id,))
    if not t or not t["logo"]:
        raise HTTPException(404, "Kein Logo")
    return Response(t["logo"], media_type=logo_mime(t["logo"]), headers={"Cache-Control": "max-age=86400"})


@app.get("/api/games/{game_id}/logo/{side}")
def game_logo_endpoint(game_id: int, side: str):
    if side not in SIDES:
        raise HTTPException(404, "Unbekannte Seite")
    g = db.one("SELECT * FROM games WHERE id=?", (game_id,))
    raw = game_logo(g, side) if g else None
    if not raw:
        raise HTTPException(404, "Kein Logo")
    return Response(raw, media_type=logo_mime(raw), headers={"Cache-Control": "max-age=86400"})


@app.post("/api/teams/{team_id}/players")
def add_player(team_id: int, body: PlayerIn):
    get_team(team_id)
    if not body.number.strip() and not body.name.strip():
        raise HTTPException(422, "Nummer oder Name angeben")
    pid = db.execute(
        "INSERT INTO players(team_id, number, name) VALUES (?,?,?)",
        (team_id, body.number.strip(), body.name.strip()),
    )
    return db.one("SELECT * FROM players WHERE id=?", (pid,))


@app.put("/api/players/{player_id}")
def update_player(player_id: int, body: PlayerIn):
    if not db.one("SELECT id FROM players WHERE id=?", (player_id,)):
        raise HTTPException(404, "Spieler nicht gefunden")
    db.execute("UPDATE players SET number=?, name=? WHERE id=?", (body.number.strip(), body.name.strip(), player_id))
    return db.one("SELECT * FROM players WHERE id=?", (player_id,))


@app.delete("/api/players/{player_id}")
def delete_player(player_id: int):
    db.execute("DELETE FROM players WHERE id=?", (player_id,))
    return {"ok": True}


# ---------------------------------------------------------------- Spiele


@app.get("/api/games")
def list_games():
    games = db.query("SELECT * FROM games ORDER BY created_at DESC")
    goals = db.query("SELECT game_id, side, COUNT(*) n FROM events WHERE type='goal' GROUP BY game_id, side")
    score: dict[int, dict] = {}
    for r in goals:
        score.setdefault(r["game_id"], {"home": 0, "away": 0})[r["side"]] = r["n"]
    for g in games:
        game_public(g)
        g["score"] = score.get(g["id"], {"home": 0, "away": 0})
    return games


@app.post("/api/games")
def create_game(body: GameIn):
    if body.home_team_id == body.away_team_id:
        raise HTTPException(422, "Heim- und Gastmannschaft müssen verschieden sein")
    home = get_team(body.home_team_id)
    away = get_team(body.away_team_id)
    logos = {
        r["id"]: r["logo"]
        for r in db.query("SELECT id, logo FROM teams WHERE id IN (?,?)", (home["id"], away["id"]))
    }
    gid = db.execute(
        "INSERT INTO games(home_team_id, away_team_id, home_name, away_name, home_color, away_color,"
        " home_logo, away_logo, competition, venue, game_date, half_minutes, halves, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            home["id"], away["id"], home["name"], away["name"], home["color"], away["color"],
            logos.get(home["id"]), logos.get(away["id"]),
            body.competition.strip(), body.venue.strip(), body.game_date.strip(),
            body.half_minutes, body.halves, db.now_ms(),
        ),
    )
    return game_state(gid)


@app.get("/api/games/{game_id}")
def get_game(game_id: int):
    return game_state(game_id)


@app.patch("/api/games/{game_id}")
def update_game(game_id: int, body: GameUpdate):
    load_game(game_id)
    for field in ("competition", "venue", "game_date", "notes"):
        val = getattr(body, field)
        if val is not None:
            db.execute(f"UPDATE games SET {field}=? WHERE id=?", (val.strip(), game_id))
    bump(game_id)
    return game_state(game_id)


@app.delete("/api/games/{game_id}")
def delete_game(game_id: int):
    load_game(game_id)
    with db.transaction() as c:
        c.execute("DELETE FROM events WHERE game_id=?", (game_id,))
        c.execute("DELETE FROM games WHERE id=?", (game_id,))
    bump(game_id)
    return {"ok": True}


@app.post("/api/games/{game_id}/clock")
def clock(game_id: int, body: ClockIn):
    g = load_game(game_id)
    now = db.now_ms()
    elapsed = elapsed_in_half(g, now)
    if body.action == "start":
        if elapsed >= half_len(g):
            raise HTTPException(409, "Halbzeit ist abgelaufen – nächste Halbzeit starten")
        if not g["clock_running"]:
            db.execute(
                "UPDATE games SET clock_running=1, clock_elapsed_ms=?, clock_anchor_ms=?, status='live' WHERE id=?",
                (elapsed, now, game_id),
            )
    elif body.action == "pause":
        if g["clock_running"]:
            db.execute("UPDATE games SET clock_running=0, clock_elapsed_ms=? WHERE id=?", (elapsed, game_id))
    else:
        if body.game_ms is None:
            raise HTTPException(422, "game_ms fehlt")
        target = clamp_to_half(g, body.game_ms) - (g["clock_half"] - 1) * half_len(g)
        # Beim Zurückstellen über das Halbzeitende hinaus ein automatisch erzeugtes Halbzeitende entfernen.
        if target < half_len(g):
            db.execute(
                "DELETE FROM events WHERE game_id=? AND type='half_end' AND half=?", (game_id, g["clock_half"])
            )
        db.execute(
            "UPDATE games SET clock_elapsed_ms=?, clock_anchor_ms=? WHERE id=?", (target, now, game_id)
        )
    bump(game_id)
    return game_state(game_id)


@app.post("/api/games/{game_id}/next-half")
def next_half(game_id: int):
    g = load_game(game_id)
    if g["clock_half"] >= g["halves"]:
        raise HTTPException(409, "Das war bereits die letzte Halbzeit")
    now = db.now_ms()
    with db.transaction() as c:
        has_end = c.execute(
            "SELECT 1 FROM events WHERE game_id=? AND type='half_end' AND half=?", (game_id, g["clock_half"])
        ).fetchone()
        if not has_end:
            c.execute(
                "INSERT INTO events(game_id,type,side,half,game_ms,created_at) VALUES (?,?,?,?,?,?)",
                (game_id, "half_end", None, g["clock_half"], current_game_ms(g, now), now),
            )
        c.execute(
            "UPDATE games SET clock_half=clock_half+1, clock_running=0, clock_elapsed_ms=0, clock_anchor_ms=?,"
            " status='live' WHERE id=?",
            (now, game_id),
        )
    bump(game_id)
    return game_state(game_id)


@app.post("/api/games/{game_id}/finish")
def finish(game_id: int):
    g = load_game(game_id)
    now = db.now_ms()
    elapsed = elapsed_in_half(g, now)
    db.execute(
        "UPDATE games SET clock_running=0, clock_elapsed_ms=?, status='finished', finished_at=? WHERE id=?",
        (elapsed, now, game_id),
    )
    bump(game_id)
    return game_state(game_id)


@app.post("/api/games/{game_id}/reopen")
def reopen(game_id: int):
    load_game(game_id)
    db.execute("UPDATE games SET status='live', finished_at=NULL WHERE id=?", (game_id,))
    bump(game_id)
    return game_state(game_id)


def _event_time(g: dict, requested: int | None) -> int:
    now = db.now_ms()
    return clamp_to_half(g, requested) if requested is not None else current_game_ms(g, now)


@app.post("/api/games/{game_id}/goal")
def add_goal(game_id: int, body: GoalIn):
    g = load_game(game_id)
    t = _event_time(g, body.game_ms)
    eid = db.execute(
        "INSERT INTO events(game_id,type,side,half,game_ms,seven_m,created_at) VALUES (?,?,?,?,?,?,?)",
        (game_id, "goal", body.side, g["clock_half"], t, int(body.seven_m), db.now_ms()),
    )
    if g["status"] == "planned":
        db.execute("UPDATE games SET status='live' WHERE id=?", (game_id,))
    bump(game_id)
    state = game_state(game_id)
    state["created_event_id"] = eid
    return state


@app.post("/api/games/{game_id}/timeout")
def add_timeout(game_id: int, body: TimeoutIn):
    g = load_game(game_id)
    now = db.now_ms()
    t = _event_time(g, body.game_ms)
    with db.transaction() as c:
        # Team-Timeout hält die Spielzeit an.
        c.execute(
            "UPDATE games SET clock_running=0, clock_elapsed_ms=? WHERE id=?", (elapsed_in_half(g, now), game_id)
        )
        c.execute(
            "INSERT INTO events(game_id,type,side,half,game_ms,created_at) VALUES (?,?,?,?,?,?)",
            (game_id, "timeout", body.side, g["clock_half"], t, now),
        )
    bump(game_id)
    return game_state(game_id)


@app.patch("/api/events/{event_id}")
def update_event(event_id: int, body: EventUpdate):
    e = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not e:
        raise HTTPException(404, "Ereignis nicht gefunden")
    if body.clear_player:
        db.execute("UPDATE events SET player_id=NULL, player_number=NULL, player_name=NULL WHERE id=?", (event_id,))
    elif body.player_id is not None:
        p = db.one("SELECT * FROM players WHERE id=?", (body.player_id,))
        if not p:
            raise HTTPException(404, "Spieler nicht gefunden")
        db.execute(
            "UPDATE events SET player_id=?, player_number=?, player_name=? WHERE id=?",
            (p["id"], p["number"], p["name"], event_id),
        )
    if body.seven_m is not None:
        db.execute("UPDATE events SET seven_m=? WHERE id=?", (int(body.seven_m), event_id))
    if body.game_ms is not None:
        g = db.one("SELECT * FROM games WHERE id=?", (e["game_id"],))
        lo = (e["half"] - 1) * half_len(g)
        db.execute(
            "UPDATE events SET game_ms=? WHERE id=?", (max(lo, min(int(body.game_ms), lo + half_len(g))), event_id)
        )
    bump(e["game_id"])
    return game_state(e["game_id"])


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int):
    e = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    if not e:
        raise HTTPException(404, "Ereignis nicht gefunden")
    db.execute("DELETE FROM events WHERE id=?", (event_id,))
    bump(e["game_id"])
    return game_state(e["game_id"])


@app.get("/api/games/{game_id}/stream")
async def stream(game_id: int, request: Request):
    load_game(game_id)

    async def gen():
        sent = -1
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            try:
                state = await asyncio.to_thread(game_state, game_id)
            except HTTPException:
                yield "event: gone\ndata: {}\n\n"
                break
            if state["version"] != sent:
                sent = state["version"]
                idle = 0.0
                yield f"data: {json.dumps(state)}\n\n"
            elif idle >= 15:
                idle = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(0.4)
            idle += 0.4

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- Bericht


@app.get("/api/games/{game_id}/report")
def report(game_id: int):
    load_game(game_id)
    rep = build_report(game_id)
    rep["game"] = game_public(rep["game"])
    return rep


@app.get("/api/games/{game_id}/report.pdf")
def report_pdf(game_id: int):
    load_game(game_id)
    rep = build_report(game_id)
    rep["logos"] = {side: game_logo(rep["game"], side) for side in SIDES}
    pdf = render_pdf(rep)
    g = rep["game"]
    base = f"{g['home_name']}_vs_{g['away_name']}"
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        base = base.replace(a, b)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    date = (g["game_date"] or "")[:10]
    filename = f"Spielbericht_{slug}{'_' + date if date else ''}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/healthz")
def healthz():
    db.query("SELECT 1")
    return {"ok": True}


# ---------------------------------------------------------------- Frontend

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

