# cheessy-lab

Local chess sparring and game review. Generates engine-vs-engine games from named
openings, then annotates them at depth so you have something worth studying.

No account, no opponent, no platform. A few hundred games an hour instead of one
per ten minutes.

## Setup

```bash
sudo pacman -S stockfish        # the engine itself (Stockfish 18)
cd lab && uv venv && uv pip install -e .
cheessy engines                 # confirm what was found
```

## Use

```bash
# 20 games, strong engine against a ~1500 opponent, reviewed immediately
cheessy spar --white "sf:depth=14" --black "sf:elo=1500" -n 20 --review

# watch it play live in a browser
cheessy watch --white "sf:depth=12" --black "sf:elo=1600" -n 10

# study one opening in isolation
cheessy spar --opening "Sicilian Najdorf" --opening "French Defense" -n 10 -o games/french.pgn

# review any PGN, including games exported from chess.com or lichess
cheessy review games/french.pgn --depth 20
```

`watch` opens a board at <http://127.0.0.1:7777> that updates move by move, with
an eval bar, the move list, and the opening name. It writes the same PGN as
`spar`, so you can review the run afterwards. `--port` to move it, `--no-browser`
to skip auto-opening a tab.

`review` writes a `.annotated.pgn` next to the input with `[%eval]` comments and
`?!`/`?`/`??`/`!!` glyphs. That file opens directly in lichess's analysis board,
SCID, or ChessBase.

### Engine specs

| Spec | Meaning |
| --- | --- |
| `sf` | Stockfish, default depth 12 |
| `sf:depth=14` | fixed depth |
| `sf:elo=1500` | `UCI_LimitStrength` at a target rating (1320–3190) |
| `sf:skill=5` | Skill Level 0–20, weaker than the Elo limiter |
| `sf:movetime=100` | 100ms per move |
| `maia:1500` | lc0 + Maia weights, needs `yay -S lc0` then `cheessy fetch-maia` |
| `/path/to/engine:depth=8` | any other UCI binary |

Maia is worth the setup if you want a sparring partner that plays like a human at
a rating band rather than like a weakened engine. Stockfish at low Elo plays
accurately and then throws in a random blunder; Maia makes the mistakes a human
of that strength actually makes.

## How the analysis works

**One search per position, not two per move.** For a position `p` with the mover
to play, `E(p)` is the evaluation from the side-to-move's point of view. After
move `m` reaches `p'`, `E(p')` is reported from the *opponent's* view, so the
value of `p'` to the mover is `-E(p')`:

```
centipawn loss(m) = E(p) - (-E(p')) = E(p) + E(p')
```

A single pass over the game yields every move's loss. This is the identity
lichess's analysis uses, and it halves engine time.

**Classification runs on win probability, not raw centipawns.** Dropping 100cp at
0.00 is a real mistake; dropping 100cp while up a queen is noise. Raw centipawn
loss is still reported because people expect to see it.

**Book moves are excluded from accuracy.** They're theory, not decisions, and
scoring them flatters both sides.

**Sacrifices are measured after the tactics resolve.** Counting material one ply
after the move sees every capture and none of the recaptures, which makes routine
trades look like brilliancies. The engine's own principal variation is replayed to
a balanced depth before material is counted, and a sacrifice in an already-won
position is technique rather than brilliance.

## The viewer

The board is rendered server-side by `chess.svg` and pushed to the browser over
Server-Sent Events. The page holds no chess logic, so there is no npm, no bundler,
no CDN, and no build step -- the whole UI is one HTML string in `watch.py`, and
the browser only swaps in SVG and appends to a list.

It binds to `127.0.0.1` only. A late-joining tab replays the current game so it
isn't blank until the next move lands.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

The evaluation sweep is driven by a scripted fake engine, so the point-of-view
arithmetic is checked against hand-computed numbers rather than against whatever
Stockfish happens to say today.
