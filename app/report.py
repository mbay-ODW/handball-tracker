"""Spielbericht-Auswertung (gemeinsame Basis für HTML-Ansicht und PDF)."""
from . import db

SIDES = ("home", "away")


def fmt_clock(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


def build_report(game_id: int) -> dict:
    g = db.one("SELECT * FROM games WHERE id=?", (game_id,))
    events = db.query("SELECT * FROM events WHERE game_id=? ORDER BY game_ms, id", (game_id,))
    half_ms = g["half_minutes"] * 60_000
    total_ms = half_ms * g["halves"]

    goals = []
    score = {"home": 0, "away": 0}
    lead_changes = 0
    last_leader = None
    max_lead = {"home": (0, None), "away": (0, None)}
    run = {"side": None, "len": 0}
    best_run = {"home": 0, "away": 0}
    progression = [{"game_ms": 0, "home": 0, "away": 0}]

    for e in events:
        if e["type"] != "goal":
            continue
        side = e["side"]
        score[side] += 1
        diff = score["home"] - score["away"]
        leader = "home" if diff > 0 else "away" if diff < 0 else None
        if leader and last_leader and leader != last_leader:
            lead_changes += 1
        if leader:
            last_leader = leader
            if abs(diff) > max_lead[leader][0]:
                max_lead[leader] = (abs(diff), e["game_ms"])
        if run["side"] == side:
            run["len"] += 1
        else:
            run = {"side": side, "len": 1}
        best_run[side] = max(best_run[side], run["len"])
        goals.append(
            {
                "id": e["id"],
                "side": side,
                "half": e["half"],
                "game_ms": e["game_ms"],
                "clock": fmt_clock(e["game_ms"]),
                "minute": e["game_ms"] // 60_000 + 1,
                "home": score["home"],
                "away": score["away"],
                "player_number": e["player_number"],
                "player_name": e["player_name"],
                "seven_m": bool(e["seven_m"]),
            }
        )
        progression.append({"game_ms": e["game_ms"], "home": score["home"], "away": score["away"]})

    halves = []
    for h in range(1, g["halves"] + 1):
        hg = [x for x in goals if x["half"] == h]
        halves.append(
            {
                "half": h,
                "home": sum(1 for x in hg if x["side"] == "home"),
                "away": sum(1 for x in hg if x["side"] == "away"),
            }
        )
    # Zwischenstand nach jeder Halbzeit (kumuliert)
    cumulative = []
    ch = ca = 0
    for h in halves:
        ch += h["home"]
        ca += h["away"]
        cumulative.append({"half": h["half"], "home": ch, "away": ca})

    scorers = {}
    for side in SIDES:
        agg: dict[tuple, dict] = {}
        for x in goals:
            if x["side"] != side:
                continue
            key = (x["player_number"] or "", x["player_name"] or "") if (x["player_number"] or x["player_name"]) else None
            k = key or ("", "")
            item = agg.setdefault(
                k,
                {"number": k[0], "name": k[1] if key else "ohne Zuordnung", "goals": 0, "seven_m": 0, "unassigned": key is None},
            )
            item["goals"] += 1
            item["seven_m"] += int(x["seven_m"])
        scorers[side] = sorted(agg.values(), key=lambda i: (i["unassigned"], -i["goals"], i["number"]))

    bucket_min = 5 if g["half_minutes"] > 10 else 2
    bucket_ms = bucket_min * 60_000
    intervals = []
    start = 0
    while start < total_ms:
        end = min(start + bucket_ms, total_ms)
        in_b = [x for x in goals if start <= x["game_ms"] < end or (end == total_ms and x["game_ms"] == end)]
        intervals.append(
            {
                "label": f"{start // 60_000:02d}–{end // 60_000:02d}",
                "home": sum(1 for x in in_b if x["side"] == "home"),
                "away": sum(1 for x in in_b if x["side"] == "away"),
            }
        )
        start = end

    timeouts = [
        {"side": e["side"], "half": e["half"], "game_ms": e["game_ms"], "clock": fmt_clock(e["game_ms"])}
        for e in events
        if e["type"] == "timeout"
    ]

    end_ms = max([total_ms] + [x["game_ms"] for x in goals])
    progression.append({"game_ms": end_ms, "home": score["home"], "away": score["away"]})

    return {
        "game": g,
        "score": score,
        "halves": halves,
        "cumulative": cumulative,
        "goals": goals,
        "scorers": scorers,
        "intervals": intervals,
        "interval_minutes": bucket_min,
        "timeouts": timeouts,
        "progression": progression,
        "total_ms": total_ms,
        "half_ms": half_ms,
        "stats": {
            "lead_changes": lead_changes,
            "max_lead": {s: {"diff": max_lead[s][0], "clock": fmt_clock(max_lead[s][1]) if max_lead[s][1] is not None else None} for s in SIDES},
            "best_run": best_run,
            "seven_m": {s: sum(1 for x in goals if x["side"] == s and x["seven_m"]) for s in SIDES},
        },
    }
