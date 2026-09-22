"""Engine-vs-engine game generation.

Games are adjudicated rather than played to bare-king mates: once the evaluation
has been decisive for several plies in a row the result is settled, and a long
dead-drawn tail teaches nothing. Both engines keep their own search limit, so
asymmetric matchups (strong vs. deliberately weak) are the normal case.
"""

from __future__ import annotations

import datetime as _dt
import random
from dataclasses import dataclass

import chess
import chess.engine
import chess.pgn

from . import openings
from .engines import EngineSpec


@dataclass
class SparConfig:
    games: int = 10
    resign_cp: int = 900
    resign_plies: int = 6
    draw_cp: int = 20
    draw_plies: int = 10
    draw_after_ply: int = 80
    max_plies: int = 300
    seed: int | None = None
    event: str = "Cheessy Lab Sparring"
    allowed_openings: list[str] | None = None


@dataclass
class _Streak:
    """Tracks consecutive plies meeting an adjudication condition."""

    decisive_for: chess.Color | None = None
    decisive_count: int = 0
    quiet_count: int = 0

    def update_decisive(self, cp_white: int, threshold: int) -> chess.Color | None:
        if cp_white >= threshold:
            winner = chess.WHITE
        elif cp_white <= -threshold:
            winner = chess.BLACK
        else:
            self.decisive_for, self.decisive_count = None, 0
            return None
        if winner == self.decisive_for:
            self.decisive_count += 1
        else:
            self.decisive_for, self.decisive_count = winner, 1
        return winner

    def update_quiet(self, cp_white: int, threshold: int) -> None:
        self.quiet_count = self.quiet_count + 1 if abs(cp_white) <= threshold else 0


def _headers(
    game: chess.pgn.Game,
    white: EngineSpec,
    black: EngineSpec,
    cfg: SparConfig,
    round_no: int,
    opening: str,
) -> None:
    game.headers["Event"] = cfg.event
    game.headers["Site"] = "local"
    game.headers["Date"] = _dt.date.today().strftime("%Y.%m.%d")
    game.headers["Round"] = str(round_no)
    game.headers["White"] = white.label
    game.headers["Black"] = black.label
    game.headers["Opening"] = opening


def play_game(
    white: EngineSpec,
    black: EngineSpec,
    white_engine: chess.engine.SimpleEngine,
    black_engine: chess.engine.SimpleEngine,
    cfg: SparConfig,
    rng: random.Random,
    round_no: int,
) -> chess.pgn.Game:
    board = chess.Board()
    opening, book_line = openings.pick(rng, cfg.allowed_openings)

    game = chess.pgn.Game()
    _headers(game, white, black, cfg, round_no, opening)
    node: chess.pgn.GameNode = game

    for move in book_line:
        board.push(move)
        node = node.add_variation(move)

    handles = {chess.WHITE: white_engine, chess.BLACK: black_engine}
    specs = {chess.WHITE: white, chess.BLACK: black}
    streak = _Streak()
    termination = "normal"
    result: str | None = None

    while not board.is_game_over(claim_draw=True):
        if board.ply() >= cfg.max_plies:
            result, termination = "1/2-1/2", "max plies reached"
            break

        mover = board.turn
        played = handles[mover].play(
            board, specs[mover].limit, info=chess.engine.INFO_SCORE
        )
        if played.move is None:
            result, termination = "1/2-1/2", "engine returned no move"
            break

        board.push(played.move)
        node = node.add_variation(played.move)

        score = played.info.get("score")
        if score is None:
            continue
        cp_white = score.white().score(mate_score=10_000)
        if cp_white is None:
            continue

        winner = streak.update_decisive(cp_white, cfg.resign_cp)
        if winner is not None and streak.decisive_count >= cfg.resign_plies:
            result = "1-0" if winner == chess.WHITE else "0-1"
            termination = "adjudicated: decisive evaluation"
            break

        streak.update_quiet(cp_white, cfg.draw_cp)
        if board.ply() >= cfg.draw_after_ply and streak.quiet_count >= cfg.draw_plies:
            result, termination = "1/2-1/2", "adjudicated: drawn evaluation"
            break

    if result is None:
        result = board.result(claim_draw=True)
        outcome = board.outcome(claim_draw=True)
        termination = outcome.termination.name.lower().replace("_", " ") if outcome else "unknown"

    game.headers["Result"] = result
    game.headers["Termination"] = termination
    # book_line is exact theory; the review pass must not score it as a decision.
    game.headers["BookPlies"] = str(len(book_line))
    return game


def run(white: EngineSpec, black: EngineSpec, cfg: SparConfig, on_game=None):
    """Play the configured match, alternating colours. Yields finished games."""
    rng = random.Random(cfg.seed)
    with white.open() as we, black.open() as be:
        for i in range(cfg.games):
            # Alternate so a first-move advantage doesn't skew the sample.
            swap = i % 2 == 1
            w_spec, b_spec = (black, white) if swap else (white, black)
            w_eng, b_eng = (be, we) if swap else (we, be)
            game = play_game(w_spec, b_spec, w_eng, b_eng, cfg, rng, i + 1)
            if on_game:
                on_game(game)
            yield game
