"""Browser viewers for the lab: live sparring, and review of a finished run.

The board is rendered server-side by ``chess.svg`` and reaches the page either
over Server-Sent Events (live) or by request per ply (review), so the page
carries no chess logic and the project needs no JS toolchain -- no npm, no
bundler, no CDN beyond a webfont.

Binds to 127.0.0.1 only. This serves your own games on your own machine.

Visual system: Modernist -- flat, architectural, Archivo, zero corner radius,
2px rules, flush-left labels, near-mono ink on a light ground with a single red
accent spent only on the last move, the current ply, and blunders.
"""

from __future__ import annotations

import json
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chess
import chess.svg

BOARD_SIZE = 460
MAX_HISTORY = 400

# The board wears the design system's neutral ramp instead of the default
# browns; cburnett's pieces are already pure black and white, so the whole
# board lands monochrome with no filter. Only the last move takes the accent.
BOARD_COLORS = {
    "square light": "#f3f2f2",   # --color-bg
    "square dark": "#bab6b6",    # --color-neutral-400
    "square light lastmove": "#ffc4b8",  # --color-accent-300
    "square dark lastmove": "#ff9783",   # --color-accent-400
    "margin": "#f3f2f2",
    "coord": "#605d5d",          # --color-neutral-700
    "inner border": "#201e1d",   # --color-text, the 2px rule around the grid
    "outer border": "#f3f2f2",
}


class ViewerError(RuntimeError):
    pass


class EventHub:
    """Fan-out of live game events to every connected browser."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []
        self._history: list[dict] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            for event in self._history:
                q.put(event)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            # A new game makes everything before it irrelevant to a fresh viewer.
            if event["t"] == "game_start":
                self._history = [event]
            else:
                self._history.append(event)
                del self._history[:-MAX_HISTORY]
            for q in self._subscribers:
                q.put(event)


def board_svg(board: chess.Board, lastmove: chess.Move | None) -> str:
    check = board.king(board.turn) if board.is_check() else None
    return chess.svg.board(
        board,
        lastmove=lastmove,
        check=check,
        size=BOARD_SIZE,
        coordinates=True,
        colors=BOARD_COLORS,
    )


def san_for(board_after: chess.Board, move: chess.Move) -> str:
    """SAN needs the position *before* the move; we're handed the one after."""
    probe = board_after.copy()
    probe.pop()
    return probe.san(move)


class GameStore:
    """Games the viewer can browse.

    Both modes browse the same way, so they share one shape: a finished run
    loaded from JSON, or a live run accumulating as it plays. The live case is
    why this exists at all -- engine games finish in seconds, so a viewer with
    no memory of earlier games is useless by the time anyone looks at it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.games: list[dict] = []
        self.source = ""

    def __len__(self) -> int:
        with self._lock:
            return len(self.games)

    def index(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "i": i,
                    "white": g["white"],
                    "black": g["black"],
                    "result": g.get("result", "*"),
                    "opening": g.get("opening", ""),
                    "plies": len(g["moves"]),
                    "live": g.get("live", False),
                }
                for i, g in enumerate(self.games)
            ]

    def get(self, i: int) -> dict:
        with self._lock:
            if not 0 <= i < len(self.games):
                raise ViewerError(f"no game {i}")
            return json.loads(json.dumps(self.games[i]))  # snapshot, not a live ref

    def board_at(self, game_index: int, ply: int) -> tuple[chess.Board, chess.Move | None]:
        """Replay `ply` half-moves. ply=0 is the starting position."""
        with self._lock:
            if not 0 <= game_index < len(self.games):
                raise ViewerError(f"no game {game_index}")
            ucis = [m["uci"] for m in self.games[game_index]["moves"]]
        ply = max(0, min(ply, len(ucis)))
        board = chess.Board()
        last: chess.Move | None = None
        for uci in ucis[:ply]:
            last = chess.Move.from_uci(uci)
            board.push(last)
        return board, last


class ReviewData(GameStore):
    """A reviewed run loaded from the JSON sidecar `cheessy review` writes."""

    @classmethod
    def load(cls, path: Path) -> "ReviewData":
        if not path.exists():
            raise ViewerError(
                f"no review data at {path}\n"
                f"Run `cheessy review` on the PGN first -- it writes this sidecar "
                f"alongside the annotated game."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ViewerError(f"{path} is not valid review JSON: {exc}") from exc
        store = cls()
        store.games = payload.get("games", [])
        store.source = path.name
        if not store.games:
            raise ViewerError(f"{path} contains no games")
        return store


class LiveLog(GameStore):
    """Accumulates a sparring run so every game stays browsable after it ends."""

    def __init__(self) -> None:
        super().__init__()
        self.source = "live run"
        self.score: dict[str, float] = {}

    def begin(self, white: str, black: str, opening: str) -> None:
        with self._lock:
            self.games.append({
                "white": white, "black": black, "opening": opening,
                "result": "*", "termination": "", "live": True, "moves": [],
                "summary": None,
            })
            self.score.setdefault(white, 0.0)
            self.score.setdefault(black, 0.0)

    def record(self, san: str, uci: str, cp_white: int | None) -> None:
        with self._lock:
            if not self.games:
                return
            g = self.games[-1]
            ply = len(g["moves"]) + 1
            g["moves"].append({
                "ply": ply,
                "n": (ply + 1) // 2,
                "color": "w" if ply % 2 else "b",
                "san": san, "uci": uci,
                "cp_white": cp_white, "cp": cp_white,
                "label": "", "best": None, "is_best": False,
            })

    def finish(self, result: str, termination: str) -> dict[str, float]:
        with self._lock:
            if not self.games:
                return {}
            g = self.games[-1]
            g.update(result=result, termination=termination, live=False)
            w, b = g["white"], g["black"]
            if result == "1-0":
                self.score[w] = self.score.get(w, 0.0) + 1
            elif result == "0-1":
                self.score[b] = self.score.get(b, 0.0) + 1
            elif result == "1/2-1/2":
                self.score[w] = self.score.get(w, 0.0) + 0.5
                self.score[b] = self.score.get(b, 0.0) + 0.5
            return dict(self.score)

    def snapshot(self) -> dict[str, float]:
        """The whole table, keyed by engine. Colours alternate between games, so
        anything keyed by white/black reads backwards on half of them."""
        with self._lock:
            return dict(self.score)


def _handler(hub: EventHub | None, store: GameStore | None, page: bytes):
    mode = "live" if hub is not None else "review"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep the terminal for the games
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._bytes(page, "text/html; charset=utf-8")
            elif path == "/app.js":
                self._bytes(APP_JS.encode(), "text/javascript; charset=utf-8")
            elif path == "/api/mode":
                self._json({"mode": mode})
            elif path == "/events" and hub is not None:
                self._events()
            elif path == "/api/games" and store is not None:
                self._json({"games": store.index(), "source": store.source})
            elif path.startswith("/api/game/") and store is not None:
                self._game(path)
            elif path.startswith("/api/svg/") and store is not None:
                self._svg(path)
            else:
                self.send_error(404)

        # -- helpers ---------------------------------------------------------

        def _bytes(self, body: bytes, content_type: str):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict):
            self._bytes(json.dumps(payload).encode(), "application/json")

        def _game(self, path: str):
            try:
                self._json(store.get(int(path.rsplit("/", 1)[1])))
            except (ValueError, ViewerError):
                self.send_error(404)

        def _svg(self, path: str):
            try:
                _, game_index, ply = path.rsplit("/", 2)
                board, last = store.board_at(int(game_index), int(ply))
            except (ValueError, ViewerError):
                self.send_error(404)
                return
            self._bytes(board_svg(board, last).encode(), "image/svg+xml")

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub.subscribe()
            try:
                while True:
                    try:
                        event = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    except queue.Empty:
                        # Comment frame: keeps the socket from idling out.
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser tab closed
            finally:
                hub.unsubscribe(q)

    return Handler


def start_server(
    port: int,
    hub: EventHub | None = None,
    store: GameStore | None = None,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), _handler(hub, store, PAGE.encode())
    )
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def open_in_browser(url: str) -> None:
    # Never let a headless or misconfigured browser take the run down with it.
    try:
        webbrowser.open(url)
    except Exception:
        pass


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cheessy Lab</title>
<link rel="icon" href="data:,">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&display=swap" rel="stylesheet">
<style>
/* Modernist tokens. Taken from the design system's styles.css, not guessed. */
:root {
  --bg: #f3f2f2;
  --surface: #eae9e9;
  --text: #201e1d;
  --accent: #ec3013;
  --divider: color-mix(in srgb, #201e1d 40%, transparent);

  --n100:#f8f4f4; --n200:#eae7e7; --n300:#d7d3d3; --n400:#bab6b6;
  --n500:#9b9797; --n600:#7d7979; --n700:#605d5d; --n800:#444141; --n900:#2d2b2b;
  --a200:#ffe0d9; --a300:#ffc4b8; --a600:#dd2b0f; --a700:#ae1800;

  --font: "Archivo", system-ui, -apple-system, "Segoe UI", sans-serif;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s6:24px; --s8:32px;
  --rule: 2px solid var(--divider);
  --ease: cubic-bezier(.16,1,.3,1);
}

*, *::before, *::after { box-sizing: border-box; }

html { background: var(--bg); }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--font); font-size: 15px; line-height: 1.55; font-weight: 400;
  -webkit-font-smoothing: antialiased;
}

/* Browser surfaces wear the system too, not the browser's defaults. */
::selection { background: color-mix(in srgb, var(--accent) 30%, transparent); }
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
* { scrollbar-width: thin; scrollbar-color: var(--n400) transparent; }
*::-webkit-scrollbar { width: 10px; height: 10px; }
*::-webkit-scrollbar-track { background: transparent; }
*::-webkit-scrollbar-thumb { background: var(--n400); border: 3px solid var(--bg); }
*::-webkit-scrollbar-thumb:hover { background: var(--n600); }

h1,h2,h3,h4,h5,h6 { font-weight: 800; line-height: 1.12; letter-spacing: -.015em; margin: 0; }
.label {
  font-size: 13px; font-weight: 800; letter-spacing: .08em;
  text-transform: uppercase; margin: 0;
}
.muted { color: var(--n700); }
.mono { font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1; }

.shell { max-width: 1180px; margin: 0 auto; padding: 0 var(--s6) var(--s8); }

/* — header — */
.nav {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: var(--s4); flex-wrap: wrap;
  padding: var(--s6) 0 var(--s3); border-bottom: var(--rule);
}
.brand { font-size: 20px; font-weight: 800; letter-spacing: -.02em; }
.brand em { font-style: normal; color: var(--accent); }
.nav-meta { display: flex; gap: var(--s6); align-items: baseline; flex-wrap: wrap; }
.nav-stat { display: flex; gap: var(--s2); align-items: baseline; }
.nav-stat .k { font-size: 11px; font-weight: 800; letter-spacing: .08em;
               text-transform: uppercase; color: var(--n700); }
.nav-stat .v { font-size: 15px; font-weight: 800; font-variant-numeric: tabular-nums; }

/* — main grid — */
.stage {
  display: grid; grid-template-columns: auto minmax(280px, 1fr);
  gap: var(--s8); align-items: start; padding: var(--s6) 0;
  border-bottom: var(--rule);
}
.boardcol { display: flex; gap: var(--s3); align-items: stretch; }

/* the eval meter: a column of ground with an ink fill rising from the base */
/* Framed like the board: without the rule the pale half dissolves into the
   ground and the gauge reads as a floating stub rather than a full column. */
.meter { width: 16px; background: var(--text); position: relative; flex: none;
         overflow: hidden; border: 2px solid var(--text); }
.meter-fill {
  position: absolute; inset: 0; background: var(--n100);
  transform-origin: bottom; transform: scaleY(.5);
  transition: transform .5s var(--ease);
}
/* the equality tick, in a neutral that holds against both ink and pale */
.meter-mid { position: absolute; left: 0; right: 0; top: 50%; height: 2px;
             background: var(--n500); z-index: 1; }
#board { width: 460px; max-width: 100%; border: 2px solid var(--text); }
#board svg { display: block; width: 100%; height: auto; }

.panel { display: flex; flex-direction: column; gap: var(--s4); min-width: 0; }
.sides { display: grid; gap: var(--s2); }
.side { display: grid; grid-template-columns: 56px 1fr auto; gap: var(--s3);
        align-items: baseline; }
.side .k { font-size: 11px; font-weight: 800; letter-spacing: .08em;
           text-transform: uppercase; color: var(--n700); }
.side .v { font-size: 14px; font-weight: 600; word-break: break-word; }
.side .s { font-size: 14px; font-weight: 800; font-variant-numeric: tabular-nums; }
.side.turn .k { color: var(--accent); }

.meta-row { display: flex; justify-content: space-between; gap: var(--s3);
            align-items: baseline; border-top: var(--rule); padding-top: var(--s3); }

/* — move list — */
.moves { border-top: var(--rule); padding-top: var(--s2);
         max-height: 340px; overflow-y: auto; }
.mv { display: grid; grid-template-columns: 34px 1fr 1fr; gap: var(--s2);
      font-size: 13px; padding: 2px 0; font-variant-numeric: tabular-nums; }
.mv .n { color: var(--n600); }
.mv b { font-weight: 600; }
.mv button {
  all: unset; cursor: pointer; padding: 1px 5px; margin: -1px -5px;
  font: inherit; font-variant-numeric: tabular-nums;
  justify-self: start;  /* hug the move, don't stripe the whole row */
}
.mv button:hover { background: var(--n200); }
.mv button[aria-current="true"] { background: var(--text); color: var(--bg); }
.tag {
  display: inline-block; font-size: 11px; font-weight: 800; letter-spacing: .06em;
  text-transform: uppercase; padding: 0 4px; margin-left: 4px; vertical-align: 1px;
}
/* Move quality is a status scale, so it escalates in one direction and every
   step also carries its word -- never colour alone. */
.t-brilliant { background: var(--text); color: var(--bg); }
.t-blunder   { background: var(--accent); color: #fff; }
.t-mistake   { color: var(--a700); }
.t-inaccuracy{ color: var(--n700); }

/* — evaluation graph — */
.graph { padding: var(--s6) 0 0; }
.graph-head { display: flex; align-items: baseline; justify-content: space-between;
              gap: var(--s4); margin-bottom: var(--s3); }
/* Proportional figures on the hero number: tabular digits read loose at size. */
.figure { font-size: 34px; font-weight: 800; letter-spacing: -.03em; line-height: 1; }
.chart-wrap { position: relative; }
#chart { display: block; width: 100%; height: 148px; }
#chart .hit { fill: transparent; cursor: crosshair; }
.tip {
  position: absolute; pointer-events: none; background: var(--text); color: var(--bg);
  font-size: 12px; font-weight: 600; padding: var(--s1) var(--s2);
  white-space: nowrap; opacity: 0; transition: opacity .12s var(--ease);
  font-variant-numeric: tabular-nums;
}
.tip[data-show="1"] { opacity: 1; }

/* — transport (review mode) — */
.transport { display: flex; gap: var(--s2); align-items: center;
             padding-top: var(--s4); flex-wrap: wrap; max-width: 100%; }
.btn {
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
  font-family: var(--font); font-weight: 800; font-size: 13px; line-height: 1;
  letter-spacing: .04em; text-transform: uppercase;
  padding: 10px 14px; border: 2px solid var(--text); background: transparent;
  color: var(--text);
}
.btn:hover:not(:disabled) { background: var(--text); color: var(--bg); }
.btn:active:not(:disabled) { background: var(--a700); border-color: var(--a700); color:#fff; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn svg { width: 16px; height: 16px; flex: none; }
.btn-icon { padding: 10px; }
select.btn {
  text-transform: none; letter-spacing: 0; appearance: none; -webkit-appearance: none;
  padding-right: 34px; border-radius: 0;
  flex: 1 1 auto; min-width: 0; max-width: 100%; text-overflow: ellipsis;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23201e1d' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center; background-size: 16px;
}
select.btn:hover { background-color: transparent; color: var(--text); }

/* — status — */
.status { display: flex; align-items: center; gap: var(--s2);
          padding-top: var(--s4); font-size: 13px; color: var(--n700); }
.dot { width: 8px; height: 8px; background: var(--n500); flex: none; }
.status[data-state="live"] .dot { background: var(--accent); }
.status[data-state="lost"] .dot { background: var(--a700); }
@media (prefers-reduced-motion: no-preference) {
  .status[data-state="live"] .dot { animation: pulse 1.6s var(--ease) infinite; }
}
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .25 } }

.empty { padding: var(--s8) 0; color: var(--n700); font-size: 14px; max-width: 60ch; }

@media (max-width: 900px) {
  .stage { grid-template-columns: 1fr; gap: var(--s6); }
  #board { width: 100%; }
  .shell { padding: 0 var(--s4) var(--s6); }
  .figure { font-size: 28px; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
</head>
<body>
<div class="shell">

  <header class="nav">
    <div class="brand">Cheessy<em>.</em>Lab</div>
    <div class="nav-meta" id="navmeta"></div>
  </header>

  <main class="stage">
    <div class="boardcol">
      <div class="meter"><div class="meter-mid"></div><div class="meter-fill" id="meter"></div></div>
      <div id="board"><div class="empty" id="boardempty">Waiting for the first move.</div></div>
    </div>

    <div class="panel">
      <div class="sides" id="sides"></div>
      <div class="meta-row">
        <span class="label" id="opening">&mdash;</span>
        <span class="muted mono" id="result"></span>
      </div>
      <div class="moves" id="moves"></div>
    </div>
  </main>

  <section class="graph">
    <div class="graph-head">
      <h2 class="label">Evaluation</h2>
      <span class="figure" id="figure">0.00</span>
    </div>
    <div class="chart-wrap">
      <svg id="chart" preserveAspectRatio="none" aria-label="Evaluation over the game"></svg>
      <div class="tip" id="tip"></div>
    </div>
    <div class="transport" id="transport" hidden></div>
    <div class="status" data-state="idle" id="status"><span class="dot"></span><span id="statustext">Connecting</span></div>
  </section>

</div>
<script>
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const CLAMP = 1000;           // +/- 10 pawns; past that the bar is pinned anyway
const MATE = 10000;

// Lucide icons (24x24, 2px stroke) -- an icon set, not unicode glyphs.
const ICON = {
  first: "M11 17l-5-5 5-5M18 17l-5-5 5-5",
  prev:  "M15 18l-6-6 6-6",
  next:  "M9 18l6-6-6-6",
  last:  "M13 17l5-5-5-5M6 17l5-5-5-5",
  play:  "M6 3l14 9-14 9V3z",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z",
};
function icon(d) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
         'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
}

const winPct = cp => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
function evalText(cp) {
  if (cp === null || cp === undefined) return "--";
  if (Math.abs(cp) >= MATE - 999) {
    return "#" + (cp < 0 ? "-" : "") + (MATE - Math.abs(cp));
  }
  return (cp >= 0 ? "+" : "") + (cp / 100).toFixed(2);
}
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------- state
const S = { mode: null, series: [], cursor: -1, moves: [], onSeek: null };

function setStatus(state, text) {
  $("status").dataset.state = state;
  $("statustext").textContent = text;
}

function setMeter(cp) {
  const pct = cp === null ? 50 : winPct(cp);
  $("meter").style.transform = "scaleY(" + (pct / 100).toFixed(4) + ")";
  $("figure").textContent = evalText(cp);
}

function renderSides(white, black, turn, scores) {
  const row = (k, v, s, on) =>
    '<div class="side' + (on ? " turn" : "") + '"><span class="k">' + k + '</span>' +
    '<span class="v">' + esc(v) + '</span>' +
    '<span class="s">' + (s === undefined ? "" : s) + '</span></div>';
  $("sides").innerHTML =
    row("White", white, scores && scores.w, turn === "w") +
    row("Black", black, scores && scores.b, turn === "b");
}

// ---------------------------------------------------------------- chart
function drawChart() {
  const svg = $("chart");
  const w = svg.clientWidth || 900, h = svg.clientHeight || 148;
  const axis = 22, plot = h - axis, mid = plot / 2;
  svg.setAttribute("viewBox", "0 0 " + w + " " + h);
  svg.innerHTML = "";

  const pts = S.series;
  const add = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    svg.appendChild(el);
    return el;
  };

  if (pts.length < 2) {
    add("line", { x1: 0, y1: mid, x2: w, y2: mid, stroke: "#201e1d", "stroke-width": 2 });
    return;
  }

  // Inset so the first and last plies -- and the cursor rule on them -- are
  // drawn whole rather than clipped by the viewBox edge.
  const PAD = 4;
  const x = i => PAD + (pts.length === 1 ? 0 : (i / (pts.length - 1)) * (w - PAD * 2));
  const y = cp => mid - (Math.max(-CLAMP, Math.min(CLAMP, cp)) / CLAMP) * mid;

  // Clip the one area path above and below the zero rule, so a crossing splits
  // itself and the two sides can carry different weight. Value-diverging on the
  // neutral ramp: light above is White ahead, dark below is Black ahead -- the
  // board's own logic rather than an arbitrary hue pair.
  const defs = document.createElementNS(NS, "defs");
  defs.innerHTML =
    '<clipPath id="above"><rect x="0" y="0" width="' + w + '" height="' + mid + '"/></clipPath>' +
    '<clipPath id="below"><rect x="0" y="' + mid + '" width="' + w + '" height="' + (plot - mid) + '"/></clipPath>';
  svg.appendChild(defs);

  let line = "M " + x(0) + " " + y(pts[0].cp);
  for (let i = 1; i < pts.length; i++) line += " L " + x(i) + " " + y(pts[i].cp);
  const area = line + " L " + x(pts.length - 1) + " " + mid + " L " + x(0) + " " + mid + " Z";

  add("path", { d: area, fill: "#d7d3d3", "clip-path": "url(#above)" });
  add("path", { d: area, fill: "#605d5d", "clip-path": "url(#below)" });
  add("line", { x1: 0, y1: mid, x2: w, y2: mid, stroke: "#201e1d", "stroke-width": 2 });
  add("path", { d: line, fill: "none", stroke: "#201e1d", "stroke-width": 2,
                "stroke-linejoin": "round" });

  // Axis: solid hairline ticks, every 10 full moves, never dashed.
  for (let i = 0; i < pts.length; i++) {
    const n = pts[i].n;
    if (i === 0 || n % 10 !== 0 || pts[i].color !== "w") continue;
    if (i > 0 && pts[i - 1].n === n) continue;
    add("line", { x1: x(i), y1: plot, x2: x(i), y2: plot + 4,
                  stroke: "#bab6b6", "stroke-width": 1 });
    const t = add("text", { x: x(i), y: h - 6, fill: "#605d5d", "font-size": 11,
                            "font-family": "Archivo, system-ui, sans-serif",
                            "text-anchor": "middle" });
    t.textContent = n;
  }

  if (S.cursor >= 0 && S.cursor < pts.length) {
    add("line", { x1: x(S.cursor), y1: 0, x2: x(S.cursor), y2: plot,
                  stroke: "#ec3013", "stroke-width": 2 });
    add("circle", { cx: x(S.cursor), cy: y(pts[S.cursor].cp), r: 4, fill: "#ec3013",
                    stroke: "#f3f2f2", "stroke-width": 2 });
  }

  // Hit layer last so it sits above the marks; hover reads, it never gates --
  // every value is also in the move list.
  const hit = add("rect", { x: 0, y: 0, width: w, height: plot, class: "hit" });
  const nearest = ev => {
    const r = svg.getBoundingClientRect();
    const rel = (ev.clientX - r.left) / r.width * w - PAD;
    const span = Math.max(1, w - PAD * 2);
    return Math.max(0, Math.min(pts.length - 1, Math.round(rel / span * (pts.length - 1))));
  };
  hit.addEventListener("mousemove", ev => {
    const i = nearest(ev), p = pts[i], tip = $("tip");
    tip.dataset.show = "1";
    tip.textContent = p.n + (p.color === "w" ? "." : "...") + " " + p.san + "   " + evalText(p.cp);
    const r = svg.getBoundingClientRect();
    tip.style.left = Math.min(r.width - tip.offsetWidth - 4,
                              Math.max(0, x(i) / w * r.width - tip.offsetWidth / 2)) + "px";
    tip.style.top = Math.max(0, y(p.cp) - 30) + "px";
  });
  hit.addEventListener("mouseleave", () => { $("tip").dataset.show = "0"; });
  if (S.onSeek) hit.addEventListener("click", ev => S.onSeek(nearest(ev) + 1));
}

let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawChart, 120);
});
</script>
<script src="/app.js"></script>
</body>
</html>
"""


APP_JS = """
// One browsing controller for both modes. A live run and a finished run differ
// only in where the games come from and whether new ones keep arriving.
const V = { mode: null, games: [], gi: -1, game: null, ply: 0,
            following: true, playing: false, timer: null, speed: 1 };
const SPEEDS = [1, 2, 4];
const BASE_MS = 700;

const fmtScore = v => {
  const whole = Math.floor(v);
  return Math.round((v % 1) * 2) === 1 ? (whole ? whole : "") + "\\u00bd" : String(whole);
};

function buildControls() {
  $("transport").hidden = false;
  $("transport").innerHTML =
    '<button class="btn btn-icon" id="tp-first" title="First move (Home)">' + icon(ICON.first) + "</button>" +
    '<button class="btn btn-icon" id="tp-prev" title="Previous move (Left arrow)">' + icon(ICON.prev) + "</button>" +
    '<button class="btn" id="tp-play" title="Replay (Space)">' + icon(ICON.play) + '<span id="tp-playlabel">Replay</span></button>' +
    '<button class="btn btn-icon" id="tp-next" title="Next move (Right arrow)">' + icon(ICON.next) + "</button>" +
    '<button class="btn btn-icon" id="tp-last" title="Last move (End)">' + icon(ICON.last) + "</button>" +
    '<button class="btn" id="tp-speed" title="Playback speed">1&times;</button>' +
    '<select class="btn" id="tp-game" aria-label="Choose game"></select>' +
    '<button class="btn" id="tp-live" hidden title="Jump back to the game being played">Live</button>';

  $("tp-first").onclick = () => { pause(); leaveLive(); seek(0); };
  $("tp-prev").onclick  = () => { pause(); leaveLive(); seek(V.ply - 1); };
  $("tp-next").onclick  = () => { pause(); leaveLive(); seek(V.ply + 1); };
  $("tp-last").onclick  = () => { pause(); leaveLive(); seek(V.game ? V.game.moves.length : 0); };
  $("tp-play").onclick  = () => togglePlay();
  $("tp-speed").onclick = () => {
    V.speed = SPEEDS[(SPEEDS.indexOf(V.speed) + 1) % SPEEDS.length];
    $("tp-speed").innerHTML = V.speed + "&times;";
    if (V.playing) { stopTimer(); startTimer(); }
  };
  $("tp-game").onchange = e => { pause(); leaveLive(); loadGame(Number(e.target.value), false); };
  $("tp-live").onclick  = () => {
    pause(); V.following = true; $("tp-live").hidden = true;
    loadGame(V.games.length - 1, true);
  };

  addEventListener("keydown", e => {
    if (e.target.tagName === "SELECT") return;
    const map = {
      ArrowLeft:  () => { pause(); leaveLive(); seek(V.ply - 1); },
      ArrowRight: () => { pause(); leaveLive(); seek(V.ply + 1); },
      Home:       () => { pause(); leaveLive(); seek(0); },
      End:        () => { pause(); leaveLive(); seek(V.game ? V.game.moves.length : 0); },
      " ":        () => togglePlay(),
    };
    if (map[e.key]) { e.preventDefault(); map[e.key](); }
  });
}

function leaveLive() {
  if (V.mode !== "live" || !V.following) return;
  V.following = false;
  $("tp-live").hidden = false;
}

// -------------------------------------------------------------- playback
function startTimer() {
  V.timer = setInterval(() => {
    if (!V.game || V.ply >= V.game.moves.length) { pause(); return; }
    seek(V.ply + 1);
  }, BASE_MS / V.speed);
}
function stopTimer() { clearInterval(V.timer); V.timer = null; }
function pause() {
  if (!V.playing) return;
  V.playing = false; stopTimer();
  $("tp-play").innerHTML = icon(ICON.play) + '<span id="tp-playlabel">Replay</span>';
}
function togglePlay() {
  if (!V.game || !V.game.moves.length) return;
  if (V.playing) { pause(); return; }
  leaveLive();
  // Replaying from the end would show nothing; start over.
  if (V.ply >= V.game.moves.length) seek(0);
  V.playing = true;
  $("tp-play").innerHTML = icon(ICON.pause) + '<span id="tp-playlabel">Pause</span>';
  startTimer();
}

// ------------------------------------------------------------ navigation
async function seek(target, svg) {
  if (!V.game) return;
  V.ply = Math.max(0, Math.min(target, V.game.moves.length));
  S.cursor = V.ply - 1;
  const m = V.ply > 0 ? V.game.moves[V.ply - 1] : null;
  setMeter(m && m.cp_white !== null ? m.cp_white : 0);
  drawChart();
  markCurrent();
  updateControls();
  if (svg) { $("board").innerHTML = svg; return; }
  const res = await fetch("/api/svg/" + V.gi + "/" + V.ply);
  if (res.ok) $("board").innerHTML = await res.text();
}
S.onSeek = ply => { pause(); leaveLive(); seek(ply); };

function markCurrent() {
  for (const b of document.querySelectorAll(".mv button"))
    b.setAttribute("aria-current", String(Number(b.dataset.ply) === V.ply));
  const active = document.querySelector('.mv button[aria-current="true"]');
  if (!active) return;
  const list = $("moves"), r = active.getBoundingClientRect(), lr = list.getBoundingClientRect();
  if (r.top < lr.top || r.bottom > lr.bottom) list.scrollTop += r.top - lr.top - lr.height / 2;
}

function updateControls() {
  const n = V.game ? V.game.moves.length : 0;
  $("tp-first").disabled = $("tp-prev").disabled = V.ply <= 0;
  $("tp-last").disabled = $("tp-next").disabled = V.ply >= n;
  $("tp-play").disabled = n === 0;
}

// Book plies carry no engine verdict. Dropping them would shorten the series
// while the cursor still counts plies, so the marker drifts further off with
// every opening move; carry the last known evaluation through them instead.
function seriesFrom(moves) {
  let last = 0;
  return moves.map(m => {
    if (m.cp_white !== null && m.cp_white !== undefined) last = m.cp_white;
    return { cp: last, n: m.n, color: m.color, san: m.san };
  });
}

function renderMoves() {
  const rows = V.game.moves.map(m => {
    const tagged = ["Brilliant", "Blunder", "Mistake", "Inaccuracy"].includes(m.label);
    const tag = tagged ? '<span class="tag t-' + m.label.toLowerCase() + '">' + m.label + "</span>" : "";
    const ev = m.cp_white === null || m.cp_white === undefined ? "" : evalText(m.cp_white);
    return '<div class="mv"><span class="n">' + m.n + (m.color === "w" ? "." : "\\u2026") +
      '</span><button data-ply="' + m.ply + '"><b>' + esc(m.san) + "</b>" + tag +
      '</button><span class="muted mono" style="text-align:right">' + ev + "</span></div>";
  });
  $("moves").innerHTML = rows.join("");
  for (const b of document.querySelectorAll(".mv button"))
    b.addEventListener("click", () => { pause(); leaveLive(); seek(Number(b.dataset.ply)); });
}

async function refreshIndex() {
  const res = await fetch("/api/games");
  if (!res.ok) return;
  const data = await res.json();
  V.games = data.games;
  const sel = $("tp-game"), keep = sel.value;
  sel.innerHTML = V.games.map(g =>
    '<option value="' + g.i + '">' + (g.i + 1) + ". " + esc(g.white) + " vs " + esc(g.black) +
    "  " + (g.live ? "playing" : g.result) +
    (g.opening ? "  \\u00b7  " + esc(g.opening) : "") + "</option>").join("");
  if (keep !== "" && Number(keep) < V.games.length) sel.value = keep;
  if (V.mode === "review") {
    $("navmeta").innerHTML = '<div class="nav-stat"><span class="k">Reviewing</span>' +
      '<span class="v">' + esc(data.source) + "</span></div>";
  }
}

async function loadGame(i, toEnd) {
  if (i < 0 || i >= V.games.length) return;
  V.gi = i;
  const res = await fetch("/api/game/" + i);
  if (!res.ok) { setStatus("lost", "Could not load game " + (i + 1)); return; }
  V.game = await res.json();
  $("tp-game").value = String(i);

  const sum = V.game.summary;
  renderSides(V.game.white, V.game.black, null, sum
    ? { w: sum.white.accuracy.toFixed(1) + "%", b: sum.black.accuracy.toFixed(1) + "%" }
    : liveScoreFor(V.game));
  $("opening").textContent = V.game.opening || "\\u2014";
  $("result").textContent = V.game.result === "*"
    ? "in progress"
    : V.game.result + "  \\u00b7  " + V.game.termination;

  S.series = seriesFrom(V.game.moves);
  renderMoves();
  const empty = $("boardempty");
  if (empty) empty.remove();
  if (sum) {
    setStatus("idle", "Accuracy " + sum.white.accuracy.toFixed(1) + "% / " +
      sum.black.accuracy.toFixed(1) + "%  \\u00b7  average loss " +
      sum.white.acpl + " / " + sum.black.acpl + " cp");
  }
  await seek(toEnd ? V.game.moves.length : (V.game.moves.length ? 1 : 0));
}

let LIVE_SCORES = {};   // engine name -> points
const liveScoreFor = g => g && LIVE_SCORES[g.white] !== undefined
  ? { w: fmtScore(LIVE_SCORES[g.white]), b: fmtScore(LIVE_SCORES[g.black]) }
  : { w: "", b: "" };

// ===================================================================== live
function bootLive() {
  buildControls();
  const es = new EventSource("/events");
  es.onopen = () => setStatus("live", "Connected");
  es.onerror = () => setStatus("lost", "Disconnected \\u2014 is the run still going?");

  // Events replay in a burst on connect. An async handler would let their awaits
  // interleave, so a slow game_start could land after done and reinstate
  // "Playing" on a finished run. One chain, strictly in order.
  let chain = Promise.resolve();
  es.onmessage = e => { chain = chain.then(() => handle(JSON.parse(e.data))).catch(() => {}); };

  async function handle(ev) {

    if (ev.t === "game_start") {
      const pad = n => String(n).padStart(2, "0");
      $("navmeta").innerHTML = '<div class="nav-stat"><span class="k">Game</span>' +
        '<span class="v">' + pad(ev.index) + " / " + pad(ev.total) + "</span></div>";
      if (ev.scores) LIVE_SCORES = ev.scores;
      await refreshIndex();
      if (V.following) await loadGame(V.games.length - 1, true);
      setStatus("live", "Playing");

    } else if (ev.t === "move") {
      // While following the game in play we already have the rendered board, so
      // append locally instead of round-tripping for a position we were sent.
      if (!V.following || V.gi !== V.games.length - 1 || !V.game) return;
      const ply = V.game.moves.length + 1;
      V.game.moves.push({
        ply: ply, n: Math.ceil(ply / 2), color: ply % 2 ? "w" : "b",
        san: ev.san, uci: ev.uci, cp_white: ev.cp, cp: ev.cp, label: "",
      });
      S.series = seriesFrom(V.game.moves);
      renderMoves();
      await seek(ply, ev.svg);

    } else if (ev.t === "game_end") {
      if (ev.scores) LIVE_SCORES = ev.scores;
      await refreshIndex();
      if (V.following && V.game) {
        V.game.result = ev.result; V.game.termination = ev.termination;
        $("result").textContent = ev.result + "  \\u00b7  " + ev.termination;
        renderSides(V.game.white, V.game.black, null, liveScoreFor(V.game));
      }
      setStatus("idle", "Game over");

    } else if (ev.t === "done") {
      await refreshIndex();
      setStatus("idle", ev.total + " games played. Pick any of them above, or press Replay.");
    }
  }
}

// =================================================================== review
async function bootReview() {
  buildControls();
  $("tp-live").remove();
  await refreshIndex();
  if (!V.games.length) { setStatus("lost", "No games to review"); return; }
  await loadGame(0, false);
}

fetch("/api/mode").then(r => r.json()).then(m => {
  V.mode = S.mode = m.mode;
  if (m.mode === "review") bootReview(); else bootLive();
}).catch(() => setStatus("lost", "Could not reach the server"));
"""
