"""PDF-Spielbericht mit ReportLab."""
import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GREY = colors.HexColor("#6b7280")
LIGHT = colors.HexColor("#f3f4f6")
LINE = colors.HexColor("#d1d5db")

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=_ss["Title"], fontSize=20, spaceAfter=2)
SUB = ParagraphStyle("sub", parent=_ss["Normal"], alignment=TA_CENTER, textColor=GREY, fontSize=10)
H2 = ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("body", parent=_ss["Normal"], fontSize=9.5, leading=12)
TEAM = ParagraphStyle("team", parent=_ss["Normal"], fontSize=14, leading=17, alignment=TA_CENTER, fontName="Helvetica-Bold")
SCORE = ParagraphStyle("score", parent=_ss["Normal"], fontSize=36, leading=40, alignment=TA_CENTER, fontName="Helvetica-Bold")


def _hex(c: str) -> colors.Color:
    try:
        return colors.HexColor(c)
    except Exception:
        return colors.HexColor("#1e6fd9")


def _p(text, style=BODY):
    return Paragraph(escape(str(text)), style)


def _base_table_style(header=True):
    cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    return cmds


def _chart(rep: dict, width: float, height: float) -> Drawing:
    g = rep["game"]
    d = Drawing(width, height)
    left, bottom, right, top = 26, 18, 8, 8
    pw, ph = width - left - right, height - bottom - top
    total = max(rep["progression"][-1]["game_ms"], rep["total_ms"], 1)
    ymax = max(rep["score"]["home"], rep["score"]["away"], 1)
    step = 1 if ymax <= 10 else 2 if ymax <= 20 else 5
    ymax = ((ymax + step - 1) // step) * step

    def x(ms):
        return left + pw * ms / total

    def y(v):
        return bottom + ph * v / ymax

    d.add(Rect(left, bottom, pw, ph, fillColor=None, strokeColor=LINE, strokeWidth=0.5))
    for v in range(0, ymax + 1, step):
        d.add(Line(left, y(v), left + pw, y(v), strokeColor=LINE, strokeWidth=0.3))
        d.add(String(left - 4, y(v) - 3, str(v), fontSize=7, fillColor=GREY, textAnchor="end"))
    minute_step = 5 if total <= 60 * 60_000 else 10
    for m in range(0, total // 60_000 + 1, minute_step):
        d.add(String(x(m * 60_000), bottom - 10, f"{m}'", fontSize=7, fillColor=GREY, textAnchor="middle"))
    for h in range(1, g["halves"]):
        hx = x(h * rep["half_ms"])
        d.add(Line(hx, bottom, hx, bottom + ph, strokeColor=GREY, strokeWidth=0.6, strokeDashArray=[3, 2]))

    for side, color in (("home", _hex(g["home_color"])), ("away", _hex(g["away_color"]))):
        pts = []
        prev = 0
        for p in rep["progression"]:
            pts += [x(p["game_ms"]), y(prev), x(p["game_ms"]), y(p[side])]
            prev = p[side]
        d.add(PolyLine(pts, strokeColor=color, strokeWidth=1.8))
    return d


def _logo(raw: bytes | None, max_w: float, max_h: float):
    """Logo proportional in eine Box einpassen; None, wenn keins vorhanden/lesbar."""
    if not raw:
        return None
    try:
        iw, ih = ImageReader(io.BytesIO(raw)).getSize()
        scale = min(max_w / iw, max_h / ih)
        return Image(io.BytesIO(raw), width=iw * scale, height=ih * scale)
    except Exception:
        return None


def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(18 * mm, 10 * mm, f"Erstellt {datetime.now(ZoneInfo(os.environ.get('TZ', 'Europe/Berlin'))).strftime('%d.%m.%Y %H:%M')} · Handball-Tracker")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Seite {doc.page}")
    canvas.restoreState()


def _fmt_date(s: str) -> str:
    try:
        return datetime.fromisoformat(s).strftime("%d.%m.%Y %H:%M" if "T" in s else "%d.%m.%Y")
    except Exception:
        return s


def render_pdf(rep: dict) -> bytes:
    g = rep["game"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Spielbericht {g['home_name']} – {g['away_name']}", author="Handball-Tracker",
    )
    W = A4[0] - 36 * mm
    story = [Paragraph("Spielbericht", H1)]
    meta = " · ".join(x for x in (g["competition"], _fmt_date(g["game_date"]), g["venue"]) if x)
    if meta:
        story.append(_p(meta, SUB))
    story.append(Spacer(1, 6 * mm))

    hc, ac = _hex(g["home_color"]), _hex(g["away_color"])
    ht = rep["cumulative"][0] if rep["cumulative"] else {"home": 0, "away": 0}
    logos = rep.get("logos") or {}
    home_logo = _logo(logos.get("home"), W * 0.3, 24 * mm)
    away_logo = _logo(logos.get("away"), W * 0.3, 24 * mm)
    rows = [
        [_p(g["home_name"], TEAM), _p(f"{rep['score']['home']} : {rep['score']['away']}", SCORE), _p(g["away_name"], TEAM)],
        [_p("Heim", SUB), _p(f"Halbzeit {ht['home']} : {ht['away']}" if g["halves"] > 1 else "", SUB), _p("Gast", SUB)],
    ]
    if home_logo or away_logo:
        rows.insert(0, [home_logo or "", "", away_logo or ""])
    score_tbl = Table(rows, colWidths=[W * 0.36, W * 0.28, W * 0.36])
    score_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LINEABOVE", (0, 0), (0, 0), 4, hc),
                ("LINEABOVE", (2, 0), (2, 0), 4, ac),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
            ]
        )
    )
    story += [score_tbl, Spacer(1, 4 * mm)]

    # Kennzahlen
    st = rep["stats"]

    def lead(side):
        m = st["max_lead"][side]
        return f"+{m['diff']} ({m['clock']})" if m["diff"] else "–"

    rows = [
        ["", g["home_name"], g["away_name"]],
        ["Tore", rep["score"]["home"], rep["score"]["away"]],
    ]
    for h in rep["halves"]:
        rows.append([f"Tore {h['half']}. Halbzeit", h["home"], h["away"]])
    rows += [
        ["davon 7m", st["seven_m"]["home"], st["seven_m"]["away"]],
        ["Höchste Führung", lead("home"), lead("away")],
        ["Längster Lauf (Tore in Folge)", st["best_run"]["home"], st["best_run"]["away"]],
        ["Team-Timeouts", sum(1 for t in rep["timeouts"] if t["side"] == "home"), sum(1 for t in rep["timeouts"] if t["side"] == "away")],
    ]
    t = Table([[_p(c) if i == 0 and isinstance(c, str) else c for i, c in enumerate(r)] for r in rows],
              colWidths=[W * 0.44, W * 0.28, W * 0.28])
    t.setStyle(TableStyle(_base_table_style() + [("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    story += [Paragraph("Kennzahlen", H2), t,
              _p(f"Führungswechsel: {st['lead_changes']}", ParagraphStyle("n", parent=BODY, textColor=GREY, spaceBefore=3))]

    # Verlauf
    legend = Table(
        [["", g["home_name"], "", g["away_name"]]],
        colWidths=[6 * mm, W * 0.4, 6 * mm, W * 0.4],
    )
    legend.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), hc), ("BACKGROUND", (2, 0), (2, 0), ac),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(KeepTogether([Paragraph("Spielverlauf", H2), _chart(rep, W, 62 * mm), Spacer(1, 2 * mm), legend]))

    # Intervalle
    iv = rep["intervals"]
    rows = [["Minute"] + [i["label"] for i in iv], [g["home_name"][:18]] + [i["home"] for i in iv], [g["away_name"][:18]] + [i["away"] for i in iv]]
    first = W * 0.2
    t = Table(rows, colWidths=[first] + [(W - first) / len(iv)] * len(iv))
    t.setStyle(TableStyle(_base_table_style() + [
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5 if len(iv) > 10 else 9),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
    ]))
    story.append(KeepTogether([Paragraph(f"Tore je {rep['interval_minutes']} Minuten", H2), t]))

    # Torschützen
    def scorer_table(side):
        rows = [["Nr.", "Spieler", "Tore", "7m"]]
        for s in rep["scorers"][side]:
            rows.append([s["number"], _p(s["name"]), s["goals"], s["seven_m"] or ""])
        if len(rows) == 1:
            rows.append(["", _p("keine Tore"), "", ""])
        tb = Table(rows, colWidths=[10 * mm, W / 2 - 38 * mm, 12 * mm, 10 * mm], repeatRows=1)
        tb.setStyle(TableStyle(_base_table_style() + [("ALIGN", (2, 0), (-1, -1), "CENTER"), ("ALIGN", (0, 0), (0, -1), "CENTER")]))
        return tb

    both = Table(
        [[_p(g["home_name"], ParagraphStyle("t", parent=BODY, fontName="Helvetica-Bold")),
          _p(g["away_name"], ParagraphStyle("t", parent=BODY, fontName="Helvetica-Bold"))],
         [scorer_table("home"), scorer_table("away")]],
        colWidths=[W / 2, W / 2],
    )
    both.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (0, 0), 2, hc), ("LINEBELOW", (1, 0), (1, 0), 2, ac),
        ("RIGHTPADDING", (0, 0), (0, -1), 6), ("LEFTPADDING", (1, 0), (1, -1), 6),
    ]))
    story.append(KeepTogether([Paragraph("Torschützen", H2), both]))

    # Torfolge
    rows = [["#", "Zeit", "Hz.", "Team", "Stand", "Torschütze", "7m"]]
    style = _base_table_style()
    for i, x in enumerate(rep["goals"], start=1):
        name = g["home_name"] if x["side"] == "home" else g["away_name"]
        shooter = " ".join(v for v in (f"#{x['player_number']}" if x["player_number"] else "", x["player_name"] or "") if v)
        rows.append([i, x["clock"], x["half"], _p(name), f"{x['home']}:{x['away']}", _p(shooter or "–"), "7m" if x["seven_m"] else ""])
        style.append(("LINEBEFORE", (3, i), (3, i), 3, hc if x["side"] == "home" else ac))
    if len(rows) == 1:
        rows.append(["", "", "", _p("Keine Tore erfasst"), "", "", ""])
    else:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafafa")))
    t = Table(rows, colWidths=[9 * mm, 15 * mm, 10 * mm, W * 0.30, 16 * mm, None, 10 * mm], repeatRows=1)
    style += [("ALIGN", (0, 0), (2, -1), "CENTER"), ("ALIGN", (4, 0), (4, -1), "CENTER"), ("ALIGN", (6, 0), (6, -1), "CENTER")]
    t.setStyle(TableStyle(style))
    story += [Paragraph("Torfolge", H2), t]

    if rep["timeouts"]:
        rows = [["Zeit", "Halbzeit", "Team"]] + [
            [x["clock"], x["half"], g["home_name"] if x["side"] == "home" else g["away_name"]] for x in rep["timeouts"]
        ]
        t = Table(rows, colWidths=[20 * mm, 20 * mm, W - 40 * mm])
        t.setStyle(TableStyle(_base_table_style()))
        story.append(KeepTogether([Paragraph("Team-Timeouts", H2), t]))

    if (g.get("notes") or "").strip():
        story += [Paragraph("Notizen", H2)] + [_p(line) for line in g["notes"].splitlines() if line.strip()]

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()

