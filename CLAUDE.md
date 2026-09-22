# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Layout

The repo holds two things, and only one of them is alive:

- **`lab/`** -- `cheessy-lab`, a Python sparring and review tool. This is the
  active work. See `lab/README.md`.
- **everything at the root** -- a Manifest V3 Chrome extension for chess.com,
  abandoned around late 2025 and **non-functional**. Kept for reference only.
  Read "Why the extension is dead" before extending it.

## The lab (`lab/`)

Generates engine-vs-engine games from a book of named openings, then annotates
them at depth. Study material without a platform, an account, or an opponent.

```bash
cd lab && uv venv && uv pip install -e .
.venv/bin/python -m pytest tests/ -q          # 32 tests, no engine needed
.venv/bin/cheessy spar --white "sf:depth=14" --black "sf:elo=1500" -n 20 --review
.venv/bin/cheessy watch --white "sf:depth=12" --black "sf:elo=1600" -n 10
```

`watch` serves a live board on 127.0.0.1. It is deliberately dependency-free:
`chess.svg` renders each position server-side and it ships to the browser over
SSE, so the page carries no chess logic and the project needs no JS toolchain.
The sparring loop exposes `on_game_start` / `on_move` / `on_game` callbacks for
this; the plain CLI path passes none of them and behaves exactly as before.
Note `on_game_start` fires from inside `play_game`, not `run`, because the
opening isn't chosen until then.

Requires Stockfish on PATH (`sudo pacman -S stockfish`; it is in chaotic-aur, not
the official repos). `lc0` plus Maia weights are optional, needed only for
`maia:NNNN` engine specs.

### Three things that are easy to get wrong here

**The point-of-view flip.** Engine scores come back relative to the side to move.
After a move the score describes the *opponent's* view, so the mover's loss is
`E(p) + E(p')`, not `E(p) - E(p')`. Every sign error in this code has been a
variant of forgetting that. `tests/test_core.py` drives the sweep with a scripted
fake engine precisely so this arithmetic is pinned to hand-computed numbers
rather than to whatever Stockfish says today.

**Mate distances are in moves, not plies.** `chess.engine.Mate(n)` counts moves,
and `score(mate_score=M)` returns `M - n`, so converting back is `M - |cp|` with
no halving. Halving it reports every mate at half its true distance.

**Material must be counted after the tactics resolve.** One ply past a move you
see the opponent's capture and never the recapture, so ordinary trades read as
sacrifices and nearly every quiet move comes back "Brilliant". `_is_sacrifice`
replays the engine's PV to an even ply count before counting material, and a
sacrifice in an already-won position is technique rather than brilliance.

## Why the extension is dead

Two independent reasons, both fatal, both confirmed rather than assumed:

- The Stockfish worker it borrows from chess.com
  (`/bundles/app/js/vendor/jschessengine/stockfish.asm.1abfa10c.js`) is addressed
  by content hash. chess.com has redeployed many times since; that URL is gone.
- The DOM contract it scrapes (`.piece.square-NN`, `.clock-player-turn`) has
  changed since the last commit.

It is also engine assistance during live games, which is the thing chess.com's
fair play policy exists to stop. If the goal is a bot that plays real online
games, Lichess has a sanctioned Bot API where opponents see a `BOT` tag and opt
in knowingly.

### What it was

A Manifest V3 Chrome extension that scrapes the live board on chess.com, builds a FEN, feeds it to Stockfish, and paints the engine's best move onto the board as colored square overlays. Content script only — there is no background/service worker, no popup, and no options page.

### Original commands (obsolete)

There is **no build step**. `manifest.json` loads `src/content/main.js` directly as plain ES — load the repo as an unpacked extension at `chrome://extensions` and reload it there after edits.

The `build` / `dev` / `test` / `lint` scripts in `package.json` are aspirational: there is no `webpack.config.js`, no ESLint config, no Jest config, no test files, and no `node_modules`. Do not suggest `npm test` or `npm run build` as a verification step — they fail. Likewise, the `stockfish.wasm` dependency is declared but never imported (see below).

Verification is manual: open a live chess.com game, open DevTools, and watch the console. Every component logs through a `Logger` with a bracketed prefix (`[ChessyApp]`, `[ChessComAdapter]`, `[SimpleEngine]`, …), including each generated FEN and best move.

### Original architecture

#### Three parallel implementations of the same feature

The same logic exists three times, in decreasing order of structure. They are **hand-kept in sync** — a fix to turn detection or FEN generation generally has to be applied to all three (the three `.md` change logs in the repo root each document one such triple-edit).

| File | Style | Status |
| --- | --- | --- |
| `src/content/main.js` | Class-based (`ChessComAdapter`, `FenGenerator`, `StockfishEngine`, `ChessyUI`, `ChessyApp`), MutationObserver-driven, fixed panel UI with injected `<style>` | **The one `manifest.json` actually loads** |
| `src/content/simple-main.js` | Class-based but closer to the legacy flow; `setInterval` polling, UI prepended into `.board-layout-main` | Alternate; not loaded |
| `scripts-legacy/main.js` | The original single-function console-paste script | Reference for "what is known to work" |

`FIX_SUMMARY.md` claims the manifest points at `simple-main.js` — it does not, it points at `main.js`. Trust `manifest.json`, not the docs.

#### The engine is chess.com's, not ours

All three files instantiate `new Worker("/bundles/app/js/vendor/jschessengine/stockfish.asm.1abfa10c.js")` — chess.com's own bundled Stockfish, reached by same-origin path from the content script. Nothing is shipped in this repo. That path contains a **content hash**: when chess.com redeploys its vendor bundle the hash changes and engine init silently fails. If analysis stops working, check this path first (find the current one in the page's network tab or DevTools sources) and update it in all three files.

#### Board scraping and coordinates

chess.com marks each piece element with two significant classes: a `square-FR` class and a two-character piece class.

- `square-FR` is **file-rank as digits, not algebraic**: `square-52` is e2 (`f`=1–8 for a–h, `r`=1–8). Conversion helpers live in `ChessComAdapter.convertAlgebraicToCoords` / `convertCoordsToAlgebraic`.
- The piece class is the class of length 2 matching `[wb][prnbqk]` — e.g. `wp`, `bq`. The legacy/simple versions find it by scanning for `item.length == 2`.

`FenGenerator` walks rank 8→1, file 1→8, emitting piece letters (uppercase = white) and run-length counts for gaps.

#### FEN is deliberately partial

The generated FEN is the board field plus the active color. `main.js` appends a fixed `' KQkq - 0 1'` tail; the other two append nothing after the color. Castling rights, en passant, and move clocks are never tracked. This is good enough for best-move search but means the FEN is not a faithful game state — don't build features that depend on those fields without adding real tracking.

#### The core domain invariant: player color ≠ active color

This is the bug the whole repo's change-log docs are about, and the thing most likely to be re-broken.

- **Player color** — which side you control. Derived once from `wc-chess-board.classList.contains('flipped')` (flipped ⇒ you are black).
- **Active color** — whose turn it is *now*. Must go into the FEN, and it changes every move.

Active color is read from the clocks: `.clock-component.clock-bottom` / `.clock-top`, whichever carries `.clock-player-turn`, then mapped through the flipped flag (bottom ⇒ `isFlipped ? 'b' : 'w'`). If neither clock resolves, all three implementations fall back to **alternating** `lastActiveColor`, which is why that field must be updated on every read. Putting the player color in the FEN instead yields illegal positions and `bestmove (none)`.

#### Move highlighting

A best move like `e2e4` is split into from/to, converted to `square-NN` coordinates, and rendered as two `<div>`s appended directly to the `wc-chess-board` element, styled `position:absolute` with a translucent background — chess.com's own `.square-NN` CSS does the positioning. Each implementation adds its own marker class purely so cleanup can find them again, and **the names differ**: `cheat-highlight` (legacy), `chessy-highlight` (simple), `cheessy-highlight` (main). Clearing highlights queries that class, so a mismatch leaves stale squares on the board.

#### Change detection

- `main.js`: `MutationObserver` on the board (childList + `class` attribute), debounced 1000 ms, then re-analyze only if the FEN differs from the last one.
- `simple-main.js` / legacy: `setInterval` every 1000 ms regenerating the FEN and diffing. `simple-main.js` compares **only the board field** (`fen.split(' ')[0]`) so a turn flip alone doesn't retrigger.

### Known rough edges

- `manifest.json` references `assets/icon.png`, but `assets/` is gitignored and absent — Chrome logs an icon warning on load.
- `.github/instructions/copilot-instructions.md` belongs to an unrelated project ("MOE Gym", a PyTorch MoE framework). It is stale boilerplate; ignore it entirely.
- `board-black.html` and `board-white.html` are empty (0 bytes). `fix-visualization.html` is a standalone explainer page for the turn-detection fix, not part of the extension.
- `FIX_SUMMARY.md`, `CODE_CHANGES.md`, and `QUICK_REFERENCE.md` all document the same October 2025 turn-detection fix from different angles.
