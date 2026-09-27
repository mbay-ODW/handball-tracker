"use strict";

// ------------------------------------------------------------ Helfer
const $view = document.getElementById("view");
const $dialog = document.getElementById("dialog");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtClock = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};
const parseClock = (txt) => {
  const m = String(txt).trim().match(/^(\d{1,3})(?::(\d{1,2}))?$/);
  if (!m) return null;
  return (parseInt(m[1], 10) * 60 + parseInt(m[2] || "0", 10)) * 1000;
};
const fmtDate = (s) => {
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d)) return s;
  return s.includes("T")
    ? d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("de-DE");
};

let toastTimer;
function toast(msg, err = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), err ? 4000 : 2000);
}

// Offset zwischen Server- und Geräteuhr (ms), damit alle Geräte dieselbe Spielzeit anzeigen.
let serverOffset = 0;
let bestRtt = Infinity;

async function api(path, opts = {}) {
  const t0 = Date.now();
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  const t1 = Date.now();
  if (!res.ok) {
    let msg = `Fehler ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = typeof j.detail === "string" ? j.detail : j.detail.map((d) => d.msg).join(", ");
    } catch (_) {}
    throw new Error(msg);
  }
  const data = await res.json();
  if (data && data.server_time) {
    const rtt = t1 - t0;
    if (rtt <= bestRtt * 1.5 || rtt < 150) {
      bestRtt = Math.min(bestRtt, rtt);
      serverOffset = data.server_time - (t0 + rtt / 2);
    }
  }
  return data;
}

const serverNow = () => Date.now() + serverOffset;

function setNav() {
  const h = location.hash || "#/";
  document.querySelectorAll(".topbar nav a").forEach((a) => {
    const target = a.getAttribute("href");
    a.classList.toggle("active", target === "#/" ? h === "#/" || h.startsWith("#/new") : h.startsWith(target));
  });
}

// ------------------------------------------------------------ Router
let cleanup = null;
async function route() {
  if (cleanup) { cleanup(); cleanup = null; }
  document.body.classList.remove("live");
  setNav();
  const parts = (location.hash.replace(/^#\/?/, "") || "").split("/");
  try {
    if (!parts[0]) return await viewGames();
    if (parts[0] === "teams" && parts[1]) return await viewTeam(+parts[1]);
    if (parts[0] === "teams") return await viewTeams();
    if (parts[0] === "new") return await viewNewGame();
    if (parts[0] === "game" && parts[1]) return await viewLive(+parts[1]);
    if (parts[0] === "report" && parts[1]) return await viewReport(+parts[1]);
    location.hash = "#/";
  } catch (e) {
    $view.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------ Spiele-Liste
const statusLabel = { planned: "geplant", live: "läuft", finished: "beendet" };

async function viewGames() {
  const games = await api("/api/games");
  $view.innerHTML = `
    <div class="row"><h1>Spiele</h1><span class="spacer"></span><a class="btn primary" href="#/new">+ Neues Spiel</a></div>
    <div class="list">
      ${games.length ? games.map((g) => `
        <a class="list-item" href="${g.status === "finished" ? "#/report/" : "#/game/"}${g.id}">
          <span class="swatch" style="background:linear-gradient(${esc(g.home_color)} 50%, ${esc(g.away_color)} 50%)"></span>
          <div style="flex:1;min-width:0">
            <div><b>${esc(g.home_name)}</b> – <b>${esc(g.away_name)}</b></div>
            <div class="muted small">${esc([g.competition, fmtDate(g.game_date), g.venue].filter(Boolean).join(" · ") || "—")}</div>
          </div>
          <span class="score-small">${g.score.home}:${g.score.away}</span>
          <span class="badge ${g.status}">${statusLabel[g.status]}</span>
        </a>`).join("") : `<div class="empty">Noch keine Spiele. Lege zuerst die Mannschaften an und starte dann ein neues Spiel.</div>`}
    </div>`;
}

// ------------------------------------------------------------ Mannschaften
const PALETTE = ["#1e6fd9", "#dc2626", "#16a34a", "#f59e0b", "#7c3aed", "#0891b2", "#db2777", "#111827", "#ea580c", "#65a30d"];

async function viewTeams() {
  const teams = await api("/api/teams");
  const color = PALETTE[teams.length % PALETTE.length];
  $view.innerHTML = `
    <h1>Mannschaften</h1>
    <div class="list">
      ${teams.length ? teams.map((t) => `
        <a class="list-item" href="#/teams/${t.id}">
          <span class="swatch" style="background:${esc(t.color)}"></span>
          <div style="flex:1"><b>${esc(t.name)}</b> ${t.short ? `<span class="muted">(${esc(t.short)})</span>` : ""}</div>
          <span class="badge">${t.player_count} Spieler</span>
        </a>`).join("") : `<div class="empty">Noch keine Mannschaften angelegt.</div>`}
    </div>
    <h2>Neue Mannschaft</h2>
    <form class="grid card" id="f">
      <label>Name<input name="name" required maxlength="80" placeholder="z. B. TV Musterstadt"></label>
      <div class="two">
        <label>Kürzel<input name="short" maxlength="12" placeholder="TVM"></label>
        <label>Trikotfarbe<input name="color" type="color" value="${color}"></label>
      </div>
      <button class="btn primary">Mannschaft anlegen</button>
    </form>`;
  document.getElementById("f").onsubmit = async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target));
    try {
      const t = await api("/api/teams", { method: "POST", body: fd });
      location.hash = `#/teams/${t.id}`;
    } catch (e) { toast(e.message, true); }
  };
}

async function viewTeam(id) {
  const t = await api(`/api/teams/${id}`);
  $view.innerHTML = `
    <div class="row"><a class="btn ghost" href="#/teams">← Zurück</a></div>
    <h1><span class="swatch" style="display:inline-block;height:22px;vertical-align:-3px;background:${esc(t.color)}"></span> ${esc(t.name)}</h1>
    <form class="grid card" id="ft">
      <label>Name<input name="name" required maxlength="80" value="${esc(t.name)}"></label>
      <div class="two">
        <label>Kürzel<input name="short" maxlength="12" value="${esc(t.short)}"></label>
        <label>Trikotfarbe<input name="color" type="color" value="${esc(t.color)}"></label>
      </div>
      <div class="row"><button class="btn primary">Speichern</button><span class="spacer"></span><button type="button" class="btn danger" id="del">Löschen</button></div>
    </form>
    <h2>Kader <span class="muted small">(optional – für Torschützen im Bericht)</span></h2>
    <form class="row card" id="fp" style="margin-bottom:10px">
      <input name="number" placeholder="Nr." maxlength="4" inputmode="numeric" style="width:80px;flex:none">
      <input name="name" placeholder="Name" maxlength="80" style="flex:1;min-width:140px">
      <button class="btn primary">+ Hinzufügen</button>
    </form>
    <div class="list">
      ${t.players.length ? t.players.map((p) => `
        <div class="list-item">
          <b style="width:40px;text-align:center">${esc(p.number || "–")}</b>
          <div style="flex:1">${esc(p.name)}</div>
          <button class="btn ghost" data-del="${p.id}" aria-label="Entfernen">✕</button>
        </div>`).join("") : `<div class="empty">Noch keine Spieler eingetragen.</div>`}
    </div>`;

  document.getElementById("ft").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/teams/${id}`, { method: "PUT", body: Object.fromEntries(new FormData(ev.target)) });
      toast("Gespeichert");
      viewTeam(id);
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("del").onclick = async () => {
    if (!confirm(`Mannschaft „${t.name}“ wirklich löschen? Bereits erfasste Spiele bleiben erhalten.`)) return;
    await api(`/api/teams/${id}`, { method: "DELETE" });
    location.hash = "#/teams";
  };
  const fp = document.getElementById("fp");
  fp.onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/teams/${id}/players`, { method: "POST", body: Object.fromEntries(new FormData(fp)) });
      await viewTeam(id);
      document.querySelector("#fp input[name=number]").focus();
    } catch (e) { toast(e.message, true); }
  };
  $view.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    await api(`/api/players/${b.dataset.del}`, { method: "DELETE" });
    viewTeam(id);
  }));
}

// ------------------------------------------------------------ Neues Spiel
async function viewNewGame() {
  const teams = await api("/api/teams");
  if (teams.length < 2) {
    $view.innerHTML = `<h1>Neues Spiel</h1><div class="empty">Du brauchst mindestens zwei Mannschaften.<br><br><a class="btn primary" href="#/teams">Mannschaften anlegen</a></div>`;
    return;
  }
  const opts = (sel) => teams.map((t) => `<option value="${t.id}" ${t.id === sel ? "selected" : ""}>${esc(t.name)}</option>`).join("");
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $view.innerHTML = `
    <h1>Neues Spiel</h1>
    <form class="grid card" id="f">
      <div class="two">
        <label>Heim<select name="home_team_id">${opts(teams[0].id)}</select></label>
        <label>Gast<select name="away_team_id">${opts(teams[1].id)}</select></label>
      </div>
      <label>Wettbewerb / Liga<input name="competition" maxlength="120" placeholder="z. B. Kreisliga, 5. Spieltag"></label>
      <div class="two">
        <label>Datum &amp; Anstoß<input name="game_date" type="datetime-local" value="${now}"></label>
        <label>Halle / Ort<input name="venue" maxlength="120"></label>
      </div>
      <div class="two">
        <label>Minuten je Halbzeit<input name="half_minutes" type="number" min="1" max="60" value="30" inputmode="numeric"></label>
        <label>Anzahl Halbzeiten<input name="halves" type="number" min="1" max="4" value="2" inputmode="numeric"></label>
      </div>
      <p class="muted small" style="margin:0">Tipp: Jugend spielt häufig 2×25 oder 2×20 Minuten.</p>
      <button class="btn primary">Spiel anlegen &amp; zur Live-Erfassung</button>
    </form>`;
  document.getElementById("f").onsubmit = async (ev) => {
    ev.preventDefault();
    const fd = Object.fromEntries(new FormData(ev.target));
    try {
      const st = await api("/api/games", {
        method: "POST",
        body: { ...fd, home_team_id: +fd.home_team_id, away_team_id: +fd.away_team_id, half_minutes: +fd.half_minutes, halves: +fd.halves },
      });
      location.hash = `#/game/${st.game.id}`;
    } catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------ Live-Erfassung
function clockMs(st) {
  // Spielzeit (gesamt, ms) aus dem Serverstand, lokal fortgeschrieben.
  const c = st.clock;
  let e = c.elapsed_ms;
  if (c.running) e += serverNow() - c.anchor_ms;
  e = Math.max(0, Math.min(e, c.half_ms));
  e = Math.round(e);
  return { total: (c.half - 1) * c.half_ms + e, inHalf: e, ended: e >= c.half_ms };
}

async function viewLive(id) {
  document.body.classList.add("live");
  let st = await api(`/api/games/${id}`);
  let pending = null; // zuletzt erfasstes Tor, dem ein Torschütze zugeordnet werden kann
  let wakeLock = null;
  let es = null;
  let connected = true;
  let lastTap = { home: 0, away: 0 };

  const requestWake = async () => {
    try { if ("wakeLock" in navigator && document.visibilityState === "visible") wakeLock = await navigator.wakeLock.request("screen"); } catch (_) {}
  };
  requestWake();
  const onVis = () => { if (document.visibilityState === "visible") { requestWake(); refresh(); } };
  document.addEventListener("visibilitychange", onVis);

  const refresh = async () => { try { apply(await api(`/api/games/${id}`)); } catch (_) {} };

  function apply(newSt) {
    if (!newSt || !newSt.game) return;
    st = newSt;
    if (pending && !st.events.some((e) => e.id === pending)) pending = null;
    render();
  }

  function connect() {
    es = new EventSource(`/api/games/${id}/stream`);
    es.onmessage = (m) => {
      connected = true;
      const data = JSON.parse(m.data);
      if (data.version >= (st.version || 0)) apply(data);
    };
    es.addEventListener("gone", () => { es.close(); location.hash = "#/"; });
    es.onerror = () => { connected = false; renderConn(); };
    es.onopen = () => { connected = true; renderConn(); refresh(); };
  }
  connect();

  const tick = setInterval(renderClock, 200);
  const sync = setInterval(refresh, 30000);
  cleanup = () => {
    clearInterval(tick); clearInterval(sync);
    if (es) es.close();
    document.removeEventListener("visibilitychange", onVis);
    if (wakeLock) wakeLock.release().catch(() => {});
  };

  function renderConn() {
    const el = document.getElementById("conn");
    if (el) { el.classList.toggle("off", !connected); el.title = connected ? "Verbunden" : "Verbindung unterbrochen"; }
  }

  function renderClock() {
    const el = document.getElementById("clock");
    if (!el) return;
    const c = clockMs(st);
    el.textContent = fmtClock(c.total);
    el.className = "clock" + (c.ended ? " ended" : st.clock.running ? "" : " stopped");
    const hi = document.getElementById("halfinfo");
    const lastHalf = st.clock.half >= st.clock.halves;
    const info = c.ended
      ? (lastHalf ? "Spielende – Abpfiff" : `Halbzeit ${st.clock.half} vorbei`)
      : `${st.clock.half}. Halbzeit${st.clock.running ? "" : " · angehalten"}`;
    if (hi.textContent !== info) hi.textContent = info;
    const btnState = c.ended ? "ended" : st.clock.running ? "running" : "paused";
    if (lastBtnState !== btnState) render();
  }
  let lastBtnState = null;

  function render() {
    const g = st.game;
    const c = clockMs(st);
    const lastHalf = st.clock.half >= st.clock.halves;
    const btnState = c.ended ? "ended" : st.clock.running ? "running" : "paused";
    lastBtnState = btnState;
    const finished = g.status === "finished";
    let startLabel = st.clock.running ? "⏸ Zeit anhalten" : (c.inHalf === 0 ? (st.clock.half === 1 ? "▶ Anpfiff" : `▶ ${st.clock.half}. Halbzeit anpfeifen`) : "▶ Zeit weiter");
    let startClass = st.clock.running ? "running" : "paused";
    let startAction = st.clock.running ? "pause" : "start";
    if (c.ended) {
      startLabel = lastHalf ? "🏁 Spiel beenden" : `➡ ${st.clock.half + 1}. Halbzeit vorbereiten`;
      startClass = "";
      startAction = lastHalf ? "finish" : "next";
    }
    if (finished) { startLabel = "📄 Spielbericht"; startAction = "report"; startClass = ""; }

    const goals = st.events.filter((e) => e.type === "goal");
    const pendingEv = pending && st.events.find((e) => e.id === pending);
    const roster = pendingEv ? st.rosters[pendingEv.side] : [];
    const teamName = (s) => (s === "home" ? g.home_name : g.away_name);
    const teamColor = (s) => (s === "home" ? g.home_color : g.away_color);

    // Laufender Spielstand je Ereignis
    let h = 0, a = 0;
    const withScore = st.events.map((e) => {
      if (e.type === "goal") { if (e.side === "home") h++; else a++; }
      return { ...e, sh: h, sa: a };
    });

    $view.innerHTML = `
      <div class="live-wrap">
        <div class="live-head">
          <a class="icon-btn" href="#/" aria-label="Zurück">←</a>
          <div class="title"><span class="conn" id="conn"></span> ${esc([g.competition, fmtDate(g.game_date)].filter(Boolean).join(" · ") || "Live-Erfassung")}</div>
          <a class="icon-btn" href="#/report/${g.id}" aria-label="Bericht">📄</a>
        </div>
        <div class="live-grid">
          <div style="display:grid;gap:12px">
            <div class="board">
              <div class="team"><div class="bar" style="background:${esc(g.home_color)}"></div>${esc(g.home_name)}</div>
              <div class="mid">
                <div class="score">${st.score.home}:${st.score.away}</div>
                <div class="clock" id="clock">${fmtClock(c.total)}</div>
                <div class="halfinfo" id="halfinfo"></div>
              </div>
              <div class="team"><div class="bar" style="background:${esc(g.away_color)}"></div>${esc(g.away_name)}</div>
            </div>
            <div class="goal-buttons">
              ${["home", "away"].map((s) => `
                <button class="goal-btn" data-goal="${s}" style="background:${esc(teamColor(s))}" ${finished ? "disabled" : ""}>
                  TOR
                  <span class="sub">${esc(teamName(s))}</span>
                </button>`).join("")}
            </div>
            <div class="controls">
              <button class="btn start-btn ${startClass}" id="startBtn" data-action="${startAction}">${startLabel}</button>
              <button class="btn" id="undoBtn" ${goals.length && !finished ? "" : "disabled"}>↶ Letztes Tor</button>
              <button class="btn" id="adjBtn">⏱ Zeit</button>
            </div>
            <div class="controls-2">
              <button class="btn" data-to="home" style="border-left:5px solid ${esc(g.home_color)}" ${finished ? "disabled" : ""}>Timeout Heim</button>
              <button class="btn" data-to="away" style="border-left:5px solid ${esc(g.away_color)}" ${finished ? "disabled" : ""}>Timeout Gast</button>
              ${finished
                ? `<button class="btn" id="reopenBtn">Wieder öffnen</button>`
                : !lastHalf && !c.ended
                  ? `<button class="btn" id="nextBtn">Halbzeit ▸</button>`
                  : `<button class="btn" id="finishBtn">Beenden</button>`}
              <a class="btn" href="#/report/${g.id}">Bericht</a>
            </div>
          </div>
          <div style="display:grid;gap:12px;align-content:start">
            ${pendingEv ? `
              <div class="card assign">
                <h3>Tor ${fmtClock(pendingEv.game_ms)} · ${esc(teamName(pendingEv.side))} – Torschütze?</h3>
                <div class="chips">
                  ${roster.map((p) => `<button class="chip ${pendingEv.player_id === p.id ? "on" : ""}" data-player="${p.id}">${esc(p.number ? "#" + p.number : "")} ${esc(p.name)}</button>`).join("")}
                  ${roster.length ? "" : `<span class="muted small">Kein Kader hinterlegt – Spieler unter „Mannschaften“ anlegen.</span>`}
                </div>
                <div class="row" style="margin-top:10px">
                  <button class="chip ${pendingEv.seven_m ? "on" : ""}" id="sevenBtn">7m</button>
                  <span class="spacer"></span>
                  <button class="btn" id="closeAssign">Fertig</button>
                </div>
              </div>` : ""}
            <div class="events">
              ${withScore.length ? withScore.slice().reverse().map((e) => e.type === "half_end"
                ? `<div class="ev marker"><span class="t">${fmtClock(e.game_ms)}</span><span>— Ende ${e.half}. Halbzeit (${e.sh}:${e.sa}) —</span></div>`
                : `<div class="ev">
                    <span class="t">${fmtClock(e.game_ms)}</span>
                    <span class="dot" style="background:${esc(teamColor(e.side))}"></span>
                    <button data-edit="${e.id}">${e.type === "timeout" ? `<i>Team-Timeout</i> ${esc(teamName(e.side))}` : `${esc(teamName(e.side))}${e.player_number || e.player_name ? ` · <b>${esc(e.player_number ? "#" + e.player_number : "")} ${esc(e.player_name || "")}</b>` : ""}${e.seven_m ? " · 7m" : ""}`}</button>
                    <span class="s">${e.type === "goal" ? `${e.sh}:${e.sa}` : "T/O"}</span>
                  </div>`).join("") : `<div class="empty">Noch keine Ereignisse. Anpfiff drücken, sobald das Spiel beginnt.</div>`}
            </div>
          </div>
        </div>
      </div>`;
    renderClock();
    renderConn();
    bind();
  }

  const act = async (fn) => {
    try { apply(await fn()); } catch (e) { toast(e.message, true); }
  };

  function bind() {
    $view.querySelectorAll("[data-goal]").forEach((b) => {
      b.onclick = async () => {
        const side = b.dataset.goal;
        const now = Date.now();
        if (now - lastTap[side] < 700) return; // Doppeltipp-Schutz
        lastTap[side] = now;
        const t = clockMs(st).total;
        b.classList.remove("flash"); void b.offsetWidth; b.classList.add("flash");
        if (navigator.vibrate) navigator.vibrate(60);
        try {
          const res = await api(`/api/games/${id}/goal`, { method: "POST", body: { side, game_ms: t } });
          pending = res.created_event_id;
          apply(res);
        } catch (e) { toast("Tor NICHT gespeichert: " + e.message, true); }
      };
    });
    const sb = document.getElementById("startBtn");
    sb.onclick = () => {
      const a = sb.dataset.action;
      if (a === "report") { location.hash = `#/report/${id}`; return; }
      if (a === "finish") return finishGame();
      if (a === "next") return act(() => api(`/api/games/${id}/next-half`, { method: "POST" }));
      act(() => api(`/api/games/${id}/clock`, { method: "POST", body: { action: a } }));
    };
    document.getElementById("undoBtn").onclick = () => {
      const goals = st.events.filter((e) => e.type === "goal");
      const last = goals.reduce((m, e) => (!m || e.id > m.id ? e : m), null);
      if (!last) return;
      if (!confirm(`Letztes Tor (${fmtClock(last.game_ms)}, ${last.side === "home" ? st.game.home_name : st.game.away_name}) löschen?`)) return;
      act(() => api(`/api/events/${last.id}`, { method: "DELETE" }));
    };
    document.getElementById("adjBtn").onclick = adjustClock;
    $view.querySelectorAll("[data-to]").forEach((b) => (b.onclick = () => {
      if (!confirm(`Team-Timeout für ${b.dataset.to === "home" ? st.game.home_name : st.game.away_name}? Die Uhr wird angehalten.`)) return;
      act(() => api(`/api/games/${id}/timeout`, { method: "POST", body: { side: b.dataset.to, game_ms: clockMs(st).total } }));
    }));
    const nb = document.getElementById("nextBtn");
    if (nb) nb.onclick = () => {
      if (!confirm(`${st.clock.half}. Halbzeit jetzt beenden und ${st.clock.half + 1}. Halbzeit vorbereiten?`)) return;
      act(() => api(`/api/games/${id}/next-half`, { method: "POST" }));
    };
    const fb = document.getElementById("finishBtn");
    if (fb) fb.onclick = finishGame;
    const rb = document.getElementById("reopenBtn");
    if (rb) rb.onclick = () => act(() => api(`/api/games/${id}/reopen`, { method: "POST" }));
    $view.querySelectorAll("[data-player]").forEach((b) => (b.onclick = () => {
      const ev = st.events.find((e) => e.id === pending);
      const same = ev && ev.player_id === +b.dataset.player;
      act(() => api(`/api/events/${pending}`, { method: "PATCH", body: same ? { clear_player: true } : { player_id: +b.dataset.player } }));
    }));
    const seven = document.getElementById("sevenBtn");
    if (seven) seven.onclick = () => {
      const ev = st.events.find((e) => e.id === pending);
      act(() => api(`/api/events/${pending}`, { method: "PATCH", body: { seven_m: !ev.seven_m } }));
    };
    const ca = document.getElementById("closeAssign");
    if (ca) ca.onclick = () => { pending = null; render(); };
    $view.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => editEvent(+b.dataset.edit)));
  }

  function finishGame() {
    if (!confirm("Spiel beenden? Danach wird der Spielbericht angezeigt.")) return;
    act(async () => {
      const r = await api(`/api/games/${id}/finish`, { method: "POST" });
      location.hash = `#/report/${id}`;
      return r;
    });
  }

  function editEvent(evId) {
    const e = st.events.find((x) => x.id === evId);
    if (!e) return;
    if (e.type === "goal") { pending = evId; render(); window.scrollTo({ top: 0, behavior: "smooth" }); }
    $dialog.innerHTML = `
      <h3>${e.type === "goal" ? "Tor" : "Team-Timeout"} bearbeiten</h3>
      <label>Spielzeit (mm:ss)<input id="evTime" class="big-input" value="${fmtClock(e.game_ms)}" inputmode="numeric"></label>
      <div class="row" style="margin-top:14px">
        <button class="btn danger" id="evDel">Löschen</button>
        <span class="spacer"></span>
        <button class="btn" id="evCancel">Abbrechen</button>
        <button class="btn primary" id="evSave">Speichern</button>
      </div>`;
    $dialog.showModal();
    document.getElementById("evCancel").onclick = () => $dialog.close();
    document.getElementById("evDel").onclick = () => {
      if (!confirm("Ereignis wirklich löschen?")) return;
      $dialog.close();
      act(() => api(`/api/events/${evId}`, { method: "DELETE" }));
    };
    document.getElementById("evSave").onclick = () => {
      const ms = parseClock(document.getElementById("evTime").value);
      if (ms === null) return toast("Format mm:ss", true);
      $dialog.close();
      act(() => api(`/api/events/${evId}`, { method: "PATCH", body: { game_ms: ms } }));
    };
  }

  function adjustClock() {
    const c = clockMs(st);
    const lo = (st.clock.half - 1) * st.clock.half_ms;
    $dialog.innerHTML = `
      <h3>Spielzeit an Hallenuhr angleichen</h3>
      <p class="muted small" style="margin-top:0">${st.clock.half}. Halbzeit: ${fmtClock(lo)} – ${fmtClock(lo + st.clock.half_ms)}</p>
      <input id="adjTime" class="big-input" value="${fmtClock(c.total)}" inputmode="numeric">
      <div class="adjust">
        <button class="btn" data-d="-10000">−10 s</button>
        <button class="btn" data-d="-1000">−1 s</button>
        <button class="btn" data-d="1000">+1 s</button>
        <button class="btn" data-d="10000">+10 s</button>
      </div>
      <div class="row">
        <span class="spacer"></span>
        <button class="btn" id="adjCancel">Abbrechen</button>
        <button class="btn primary" id="adjSave">Übernehmen</button>
      </div>`;
    $dialog.showModal();
    const inp = document.getElementById("adjTime");
    // Uhr läuft im Dialog weiter, solange nicht manuell editiert wird.
    let base = c.total, baseAt = serverNow(), dirty = false, offset = 0;
    const iv = setInterval(() => {
      if (dirty) return;
      const cur = st.clock.running ? base + (serverNow() - baseAt) : base;
      inp.value = fmtClock(Math.min(cur + offset, lo + st.clock.half_ms));
    }, 200);
    inp.oninput = () => (dirty = true);
    $dialog.querySelectorAll("[data-d]").forEach((b) => (b.onclick = () => {
      if (dirty) {
        const ms = parseClock(inp.value);
        if (ms !== null) inp.value = fmtClock(Math.max(0, ms + +b.dataset.d));
      } else {
        offset += +b.dataset.d;
      }
    }));
    const close = () => { clearInterval(iv); $dialog.close(); };
    document.getElementById("adjCancel").onclick = close;
    document.getElementById("adjSave").onclick = () => {
      const ms = parseClock(inp.value);
      if (ms === null) return toast("Format mm:ss", true);
      close();
      act(() => api(`/api/games/${id}/clock`, { method: "POST", body: { action: "set", game_ms: ms } }));
    };
    $dialog.addEventListener("close", () => clearInterval(iv), { once: true });
  }

  render();
}

// ------------------------------------------------------------ Bericht
function chartSvg(rep) {
  const g = rep.game;
  const W = 800, H = 280, L = 36, R = 12, T = 12, B = 28;
  const pw = W - L - R, ph = H - T - B;
  const total = Math.max(rep.progression[rep.progression.length - 1].game_ms, rep.total_ms, 1);
  let ymax = Math.max(rep.score.home, rep.score.away, 1);
  const step = ymax <= 10 ? 1 : ymax <= 20 ? 2 : 5;
  ymax = Math.ceil(ymax / step) * step;
  const x = (ms) => L + (pw * ms) / total;
  const y = (v) => T + ph - (ph * v) / ymax;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spielverlauf">`;
  for (let v = 0; v <= ymax; v += step)
    s += `<line x1="${L}" x2="${L + pw}" y1="${y(v)}" y2="${y(v)}" stroke="#334155" stroke-width="1"/><text x="${L - 6}" y="${y(v) + 4}" fill="#94a3b8" font-size="12" text-anchor="end">${v}</text>`;
  const mstep = total <= 3600000 ? 5 : 10;
  for (let m = 0; m <= total / 60000; m += mstep)
    s += `<text x="${x(m * 60000)}" y="${H - 8}" fill="#94a3b8" font-size="12" text-anchor="middle">${m}'</text>`;
  for (let hh = 1; hh < g.halves; hh++)
    s += `<line x1="${x(hh * rep.half_ms)}" x2="${x(hh * rep.half_ms)}" y1="${T}" y2="${T + ph}" stroke="#94a3b8" stroke-dasharray="5 4"/>`;
  for (const [side, color] of [["home", g.home_color], ["away", g.away_color]]) {
    let prev = 0;
    const pts = [];
    for (const p of rep.progression) { pts.push(`${x(p.game_ms)},${y(prev)}`, `${x(p.game_ms)},${y(p[side])}`); prev = p[side]; }
    s += `<polyline points="${pts.join(" ")}" fill="none" stroke="${esc(color)}" stroke-width="3" stroke-linejoin="round"/>`;
  }
  return s + "</svg>";
}

async function viewReport(id) {
  const rep = await api(`/api/games/${id}/report`);
  const g = rep.game;
  const name = (s) => (s === "home" ? g.home_name : g.away_name);
  const color = (s) => (s === "home" ? g.home_color : g.away_color);
  const st = rep.stats;
  const lead = (s) => (st.max_lead[s].diff ? `+${st.max_lead[s].diff} (${st.max_lead[s].clock})` : "–");
  const ht = rep.cumulative[0] || { home: 0, away: 0 };
  $view.innerHTML = `
    <div class="row">
      <a class="btn ghost" href="#/game/${g.id}">← Live-Ansicht</a>
      <span class="spacer"></span>
      <a class="btn primary" href="/api/games/${g.id}/report.pdf" download>⬇ PDF exportieren</a>
    </div>
    <div class="report-head">
      <h1 style="margin-bottom:0">Spielbericht</h1>
      <div class="muted">${esc([g.competition, fmtDate(g.game_date), g.venue].filter(Boolean).join(" · "))}</div>
      <div class="board" style="margin-top:14px">
        <div class="team"><div class="bar" style="background:${esc(g.home_color)}"></div>${esc(g.home_name)}</div>
        <div class="mid"><div class="report-score">${rep.score.home}:${rep.score.away}</div>
          ${g.halves > 1 ? `<div class="muted small">Halbzeit ${ht.home}:${ht.away}</div>` : ""}
          ${g.status !== "finished" ? `<div class="badge live" style="display:inline-block;margin-top:4px">Spiel läuft noch</div>` : ""}</div>
        <div class="team"><div class="bar" style="background:${esc(g.away_color)}"></div>${esc(g.away_name)}</div>
      </div>
    </div>

    <h2>Kennzahlen</h2>
    <div class="card table-scroll"><table>
      <tr><th></th><th class="c">${esc(g.home_name)}</th><th class="c">${esc(g.away_name)}</th></tr>
      <tr><td>Tore</td><td class="c"><b>${rep.score.home}</b></td><td class="c"><b>${rep.score.away}</b></td></tr>
      ${rep.halves.map((h) => `<tr><td>Tore ${h.half}. Halbzeit</td><td class="c">${h.home}</td><td class="c">${h.away}</td></tr>`).join("")}
      <tr><td>davon 7m</td><td class="c">${st.seven_m.home}</td><td class="c">${st.seven_m.away}</td></tr>
      <tr><td>Höchste Führung</td><td class="c">${lead("home")}</td><td class="c">${lead("away")}</td></tr>
      <tr><td>Längster Lauf</td><td class="c">${st.best_run.home}</td><td class="c">${st.best_run.away}</td></tr>
      <tr><td>Team-Timeouts</td><td class="c">${rep.timeouts.filter((t) => t.side === "home").length}</td><td class="c">${rep.timeouts.filter((t) => t.side === "away").length}</td></tr>
    </table>
    <div class="muted small" style="margin-top:6px">Führungswechsel: ${st.lead_changes}</div></div>

    <h2>Spielverlauf</h2>
    ${chartSvg(rep)}
    <div class="row small" style="margin-top:6px">
      <span class="swatch" style="height:10px;width:18px;background:${esc(g.home_color)}"></span>${esc(g.home_name)}
      <span class="swatch" style="height:10px;width:18px;background:${esc(g.away_color)};margin-left:10px"></span>${esc(g.away_name)}
    </div>

    <h2>Tore je ${rep.interval_minutes} Minuten</h2>
    <div class="card table-scroll"><table>
      <tr><th>Minute</th>${rep.intervals.map((i) => `<th class="c">${i.label}</th>`).join("")}</tr>
      <tr><td><b>${esc(g.home_name)}</b></td>${rep.intervals.map((i) => `<td class="c">${i.home}</td>`).join("")}</tr>
      <tr><td><b>${esc(g.away_name)}</b></td>${rep.intervals.map((i) => `<td class="c">${i.away}</td>`).join("")}</tr>
    </table></div>

    <h2>Torschützen</h2>
    <div class="two">
      ${["home", "away"].map((s) => `
        <div class="card"><div style="border-bottom:3px solid ${esc(color(s))};padding-bottom:4px;font-weight:700">${esc(name(s))}</div>
          <table><tr><th>Nr.</th><th>Spieler</th><th class="c">Tore</th><th class="c">7m</th></tr>
          ${rep.scorers[s].length ? rep.scorers[s].map((p) => `<tr><td>${esc(p.number)}</td><td>${p.unassigned ? `<i class="muted">${esc(p.name)}</i>` : esc(p.name)}</td><td class="c"><b>${p.goals}</b></td><td class="c">${p.seven_m || ""}</td></tr>`).join("") : `<tr><td colspan="4" class="muted">keine Tore</td></tr>`}
          </table></div>`).join("")}
    </div>

    <h2>Torfolge</h2>
    <div class="card table-scroll"><table>
      <tr><th>#</th><th>Zeit</th><th>Team</th><th class="c">Stand</th><th>Torschütze</th><th class="c">7m</th></tr>
      ${rep.goals.length ? rep.goals.map((x, i) => `<tr>
        <td>${i + 1}</td><td>${x.clock}</td>
        <td><span class="swatch" style="display:inline-block;height:12px;width:6px;vertical-align:-1px;background:${esc(color(x.side))}"></span> ${esc(name(x.side))}</td>
        <td class="c"><b>${x.home}:${x.away}</b></td>
        <td>${esc([x.player_number ? "#" + x.player_number : "", x.player_name || ""].filter(Boolean).join(" ")) || "–"}</td>
        <td class="c">${x.seven_m ? "7m" : ""}</td></tr>`).join("") : `<tr><td colspan="6" class="muted">Keine Tore erfasst</td></tr>`}
    </table></div>

    ${rep.timeouts.length ? `<h2>Team-Timeouts</h2><div class="card"><table>
      <tr><th>Zeit</th><th>Halbzeit</th><th>Team</th></tr>
      ${rep.timeouts.map((t) => `<tr><td>${t.clock}</td><td>${t.half}.</td><td>${esc(name(t.side))}</td></tr>`).join("")}
    </table></div>` : ""}

    <h2>Notizen</h2>
    <form id="fn" class="grid">
      <textarea name="notes" placeholder="Besonderheiten, Schiedsrichter, Zuschauer …">${esc(g.notes)}</textarea>
      <div class="row"><button class="btn">Notizen speichern</button><span class="spacer"></span>
        <button type="button" class="btn danger" id="delGame">Spiel löschen</button></div>
    </form>`;
  document.getElementById("fn").onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api(`/api/games/${id}`, { method: "PATCH", body: { notes: ev.target.notes.value } });
      toast("Notizen gespeichert – erscheinen im PDF");
    } catch (e) { toast(e.message, true); }
  };
  document.getElementById("delGame").onclick = async () => {
    if (!confirm("Spiel inklusive aller Tore endgültig löschen?")) return;
    await api(`/api/games/${id}`, { method: "DELETE" });
    location.hash = "#/";
  };
}

route();
