"""A local viewer for watching sparring games as they are played.

The board is rendered server-side by ``chess.svg`` and pushed to the browser over
Server-Sent Events, so the page carries no chess logic and needs no build step,
no npm, and no CDN. The whole UI is one self-contained HTML string.

Binds to 127.0.0.1 only. This serves your own games on your own machine; it is
not meant to be exposed.
"""

from __future__ import annotations

import json
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess
import chess.svg

BOARD_SIZE = 400
# A late-joining browser replays the current game only, which bounds memory
# without leaving the page blank until the next move lands.
MAX_HISTORY = 400


class EventHub:
    """Fan-out of game events to every connected browser."""

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


def _handler(hub: EventHub, page: bytes):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep the terminal for the game, not the server
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send_page()
            elif self.path == "/events":
                self._send_events()
            else:
                self.send_error(404)

        def _send_page(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def _send_events(self):
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
                        payload = json.dumps(event)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    except queue.Empty:
                        # Comment frame: keeps proxies and the socket from idling out.
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser tab closed
            finally:
                hub.unsubscribe(q)

    return Handler


def board_svg(board: chess.Board, lastmove: chess.Move | None) -> str:
    check = board.king(board.turn) if board.is_check() else None
    return chess.svg.board(
        board, lastmove=lastmove, check=check, size=BOARD_SIZE, coordinates=True
    )


def san_for(board_after: chess.Board, move: chess.Move) -> str:
    """SAN needs the position *before* the move; we're handed the one after."""
    probe = board_after.copy()
    probe.pop()
    return probe.san(move)


def start_server(hub: EventHub, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(hub, PAGE.encode()))
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
<title>cheessy lab</title>
<link rel="icon" href="data:,">  <!-- suppress the favicon request; we serve one route -->
<style>
  :root {
    --bg: #14151a; --panel: #1c1e26; --line: #2b2e3a;
    --text: #e6e7ea; --dim: #8b90a0; --accent: #7aa2f7;
    --good: #9ece6a; --bad: #f7768e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 20px;
  }
  .wrap { max-width: 900px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: baseline;
           gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
  h1 { font-size: 15px; margin: 0; font-weight: 600; letter-spacing: .02em; }
  h1 .dot { color: var(--accent); }
  .counter { color: var(--dim); font-variant-numeric: tabular-nums; }
  .main { display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
  .boardwrap { display: flex; gap: 10px; }
  #board svg { display: block; border-radius: 6px; max-width: 100%; height: auto; }
  #board { width: 400px; max-width: 100%; }
  .evalbar { width: 14px; border-radius: 4px; overflow: hidden;
             background: #2a2d38; position: relative; align-self: stretch; }
  .evalfill { position: absolute; left: 0; right: 0; bottom: 0; background: #e8e8e8;
              height: 50%; transition: height .35s ease; }
  .panel { flex: 1; min-width: 260px; background: var(--panel);
           border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
  .players { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px;
             margin-bottom: 12px; }
  .players .k { color: var(--dim); }
  .players .v { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: 13px; word-break: break-all; }
  .meta { color: var(--dim); font-size: 13px; margin-bottom: 10px; }
  .score { font-variant-numeric: tabular-nums; font-weight: 600;
           font-family: ui-monospace, Menlo, monospace; }
  #moves { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
           font-size: 13px; max-height: 300px; overflow-y: auto;
           border-top: 1px solid var(--line); padding-top: 10px; }
  #moves .row { display: grid; grid-template-columns: 34px 1fr 1fr; gap: 6px; }
  #moves .n { color: var(--dim); }
  #moves .row:nth-child(odd) { background: rgba(255,255,255,.02); }
  .result { margin-top: 12px; padding: 8px 10px; border-radius: 6px;
            background: #232631; font-weight: 600; display: none; }
  .status { color: var(--dim); font-size: 13px; margin-top: 10px; }
  .status.live::before { content: "● "; color: var(--good); }
  .status.done::before { content: "■ "; color: var(--dim); }
  .status.lost::before { content: "▲ "; color: var(--bad); }
  @media (max-width: 720px) { .panel { min-width: 100%; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="dot">▪</span> cheessy lab</h1>
    <div class="counter" id="counter">waiting…</div>
  </header>
  <div class="main">
    <div class="boardwrap">
      <div class="evalbar"><div class="evalfill" id="evalfill"></div></div>
      <div id="board"></div>
    </div>
    <div class="panel">
      <div class="players">
        <div class="k">White</div><div class="v" id="white">—</div>
        <div class="k">Black</div><div class="v" id="black">—</div>
      </div>
      <div class="meta">
        <span id="opening">—</span> · <span class="score" id="evaltext">0.00</span>
      </div>
      <div id="moves"></div>
      <div class="result" id="result"></div>
      <div class="status live" id="status">connecting…</div>
    </div>
  </div>
</div>
<script>
const $ = id => document.getElementById(id);
let ply = 0;

// Same curve the Python side uses, so the bar agrees with the printed report.
const winPct = cp => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);

function evalText(cp) {
  if (Math.abs(cp) >= 9001) {
    const n = 10000 - Math.abs(cp);
    return "#" + (cp < 0 ? "-" : "") + n;
  }
  return (cp >= 0 ? "+" : "") + (cp / 100).toFixed(2);
}

function resetGame(ev) {
  ply = 0;
  $("moves").innerHTML = "";
  $("white").textContent = ev.white;
  $("black").textContent = ev.black;
  $("counter").textContent = `game ${ev.index} / ${ev.total}`;
  $("opening").textContent = ev.opening || "—";
  $("result").style.display = "none";
  $("evaltext").textContent = "0.00";
  $("evalfill").style.height = "50%";
  setStatus("live", "playing");
}

function addMove(san) {
  const moves = $("moves");
  if (ply % 2 === 0) {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<span class="n">${ply / 2 + 1}.</span>` +
                    `<span>${san}</span><span></span>`;
    moves.appendChild(row);
  } else {
    const last = moves.lastElementChild;
    if (last) last.lastElementChild.textContent = san;
  }
  ply++;
  moves.scrollTop = moves.scrollHeight;
}

function setStatus(cls, text) {
  const el = $("status");
  el.className = "status " + cls;
  el.textContent = text;
}

const es = new EventSource("/events");
es.onopen = () => setStatus("live", "connected");
es.onerror = () => setStatus("lost", "disconnected — is the run still going?");
es.onmessage = e => {
  const ev = JSON.parse(e.data);
  if (ev.t === "game_start") {
    resetGame(ev);
  } else if (ev.t === "move") {
    $("board").innerHTML = ev.svg;
    addMove(ev.san);
    if (ev.cp !== null) {
      $("evaltext").textContent = evalText(ev.cp);
      $("evalfill").style.height = winPct(ev.cp).toFixed(1) + "%";
    }
  } else if (ev.t === "game_end") {
    const r = $("result");
    r.textContent = `${ev.result} — ${ev.termination}`;
    r.style.display = "block";
    setStatus("done", "game over");
  } else if (ev.t === "done") {
    $("counter").textContent = `${ev.total} games complete`;
    setStatus("done", "run finished — server still up, Ctrl+C in the terminal to stop");
  }
};
</script>
</body>
</html>
"""
