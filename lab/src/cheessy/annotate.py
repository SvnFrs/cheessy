"""Per-move analysis: evaluation sweep, loss attribution, move classification.

The sweep costs one search per *position*, not two per move. For a position p
where it is the mover's turn, let E(p) be the engine evaluation from the POV of
the side to move. After the mover plays m reaching p', E(p') is reported from
the *opponent's* POV, so the value of p' to the mover is -E(p').

    centipawn loss(m) = E(p) - (-E(p')) = E(p) + E(p')

So a single pass over the game yields every move's loss. This is the same
identity lichess's analysis uses, and it halves engine time versus the naive
"search before, search after" approach.

Classification runs on the drop in *win probability*, not raw centipawns:
giving up 100cp at 0.00 is a real mistake, giving up 100cp while up a queen is
noise. Raw centipawn loss is still reported because people expect to see it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn

# Mate scores are folded into centipawns at this magnitude before comparison.
MATE_CP = 10_000
# Losses are capped so a single resignation-grade blunder can't swamp an average.
MAX_CPL = 1000

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Win-probability drop (percentage points) at or below which each label applies.
THRESHOLDS = (
    (2.0, "Excellent"),
    (5.0, "Good"),
    (10.0, "Inaccuracy"),
    (20.0, "Mistake"),
)
BLUNDER = "Blunder"

# A sacrifice must give up at least this much material, and hold at least this
# evaluation afterwards, to read as brilliant rather than as a losing gift.
SAC_MATERIAL = 150
SAC_MIN_EVAL = -50
# How far into the principal variation to look before counting material.
SAC_PV_PLIES = 10
# Above this evaluation the game is already decided, and giving material back to
# simplify is sound technique rather than brilliance.
SAC_MAX_PRIOR_EVAL = 300


def win_percent(cp: int) -> float:
    """Map a centipawn evaluation to a 0-100 win expectancy (lichess's curve)."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_drop: float) -> float:
    """Lichess's per-move accuracy curve over the win-probability drop."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * win_drop) - 3.1669))


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material from ``color``'s point of view, in centipawns."""
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += value * len(board.pieces(piece_type, color))
        total -= value * len(board.pieces(piece_type, not color))
    return total


@dataclass
class PositionEval:
    """One engine verdict about one position, from the side-to-move's POV."""

    cp: int
    pv: list[chess.Move] = field(default_factory=list)
    is_mate: bool = False
    mate_in: int | None = None

    @property
    def best(self) -> chess.Move | None:
        return self.pv[0] if self.pv else None


@dataclass
class Annotation:
    ply: int
    move_number: int
    color: chess.Color
    san: str
    uci: str
    cp_before: int
    cp_after: int
    cpl: int
    win_before: float
    win_after: float
    win_drop: float
    accuracy: float
    best_san: str | None
    is_best: bool
    label: str

    @property
    def is_error(self) -> bool:
        return self.label in ("Inaccuracy", "Mistake", BLUNDER)


@dataclass
class SideSummary:
    accuracy: float
    acpl: int
    counts: dict[str, int]


@dataclass
class GameReport:
    headers: dict[str, str]
    annotations: list[Annotation]
    summaries: dict[chess.Color, SideSummary]

    def errors(self) -> list[Annotation]:
        return [a for a in self.annotations if a.is_error]


def _to_cp(score: chess.engine.PovScore) -> PositionEval:
    relative = score.relative
    mate = relative.mate()
    cp = relative.score(mate_score=MATE_CP)
    return PositionEval(cp=cp, is_mate=mate is not None, mate_in=mate)


def evaluate_positions(
    game: chess.pgn.Game,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    progress=None,
) -> tuple[list[chess.Board], list[chess.Move], list[PositionEval]]:
    """Walk the mainline, evaluating every position including the final one."""
    board = game.board()
    boards: list[chess.Board] = []
    moves: list[chess.Move] = []
    evals: list[PositionEval] = []

    mainline = list(game.mainline_moves())
    for move in mainline:
        boards.append(board.copy(stack=False))
        info = engine.analyse(board, limit)
        ev = _to_cp(info["score"])
        ev.pv = list(info.get("pv") or [])
        evals.append(ev)
        moves.append(move)
        board.push(move)
        if progress:
            progress()

    # Terminal position: a finished game has no move to search for.
    boards.append(board.copy(stack=False))
    if board.is_game_over():
        outcome = board.outcome()
        if outcome and outcome.winner is not None:
            # Side to move has been mated, so it is lost from their POV.
            evals.append(PositionEval(cp=-MATE_CP, is_mate=True, mate_in=0))
        else:
            evals.append(PositionEval(cp=0))
    else:
        info = engine.analyse(board, limit)
        ev = _to_cp(info["score"])
        ev.pv = list(info.get("pv") or [])
        evals.append(ev)
    if progress:
        progress()

    return boards, moves, evals


def _is_sacrifice(
    board_before: chess.Board,
    move: chess.Move,
    after_eval: PositionEval,
    mover: chess.Color,
) -> bool:
    """Did this move hand over material that the engine's own line never wins back?

    Material must be counted *after the tactics resolve*, not one ply later. Stopping
    at the opponent's reply sees every capture and none of the recaptures, which makes
    routine trades look like sacrifices: after 5.h3 Bxf3 White is a knight down for
    exactly one ply, and 6.Qxf3 takes it straight back.

    So we replay the engine's own principal variation and measure at the end of it.
    The ply count is forced even so both sides have moved the same number of times --
    an odd cut-off would score the position mid-trade, which has the same bias in
    miniature. A move only reads as a sacrifice if the engine's best line leaves the
    mover genuinely down material.
    """
    pv = after_eval.pv[:SAC_PV_PLIES]
    # Even count => opponent and mover have replied to each other equally.
    usable = (len(pv) // 2) * 2
    if usable == 0:
        return False  # no line to resolve; refuse to guess

    probe = board_before.copy()
    probe.push(move)
    for reply in pv[:usable]:
        if reply not in probe.legal_moves:
            return False  # stale PV, don't guess from a broken line
        probe.push(reply)

    lost = material_balance(board_before, mover) - material_balance(probe, mover)
    return lost >= SAC_MATERIAL


def classify(
    win_drop: float,
    is_best: bool,
    forced: bool,
    in_book: bool,
    sacrificed: bool,
    cp_after: int,
    cp_before: int = 0,
) -> str:
    if forced:
        return "Forced"
    if in_book:
        return "Book"
    if (
        sacrificed
        and is_best
        and cp_after >= SAC_MIN_EVAL
        and cp_before <= SAC_MAX_PRIOR_EVAL  # nothing brilliant about a won game
        and win_drop < 2.0
    ):
        return "Brilliant"
    if is_best and win_drop < 0.5:
        return "Best"
    for ceiling, label in THRESHOLDS:
        if win_drop < ceiling:
            return label
    return BLUNDER


def annotate_game(
    game: chess.pgn.Game,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    book_plies: int = 0,
    progress=None,
) -> GameReport:
    boards, moves, evals = evaluate_positions(game, engine, limit, progress)
    annotations: list[Annotation] = []

    for i, move in enumerate(moves):
        board = boards[i]
        mover = board.turn
        before, after = evals[i], evals[i + 1]

        cp_before = before.cp
        # `after` is scored from the opponent's POV; flip it to the mover's.
        cp_after = -after.cp
        cpl = max(0, min(MAX_CPL, cp_before - cp_after))

        win_before = win_percent(cp_before)
        win_after = win_percent(cp_after)
        win_drop = max(0.0, win_before - win_after)

        best = before.best
        is_best = best is not None and best == move
        best_san = board.san(best) if best and best in board.legal_moves else None
        forced = board.legal_moves.count() == 1
        in_book = i < book_plies

        sacrificed = False
        if not forced and not in_book and win_drop < 2.0:
            sacrificed = _is_sacrifice(board, move, after, mover)

        annotations.append(
            Annotation(
                ply=i + 1,
                move_number=board.fullmove_number,
                color=mover,
                san=board.san(move),
                uci=move.uci(),
                cp_before=cp_before,
                cp_after=cp_after,
                cpl=cpl,
                win_before=win_before,
                win_after=win_after,
                win_drop=win_drop,
                accuracy=move_accuracy(win_drop),
                best_san=best_san,
                is_best=is_best,
                label=classify(
                    win_drop, is_best, forced, in_book, sacrificed,
                    cp_after, cp_before,
                ),
            )
        )

    return GameReport(
        headers=dict(game.headers),
        annotations=annotations,
        summaries={
            chess.WHITE: _summarise(annotations, chess.WHITE),
            chess.BLACK: _summarise(annotations, chess.BLACK),
        },
    )


def _summarise(annotations: list[Annotation], color: chess.Color) -> SideSummary:
    mine = [a for a in annotations if a.color == color]
    # Book moves are theory, not decisions; scoring them flatters both sides.
    scored = [a for a in mine if a.label not in ("Book", "Forced")]
    counts: dict[str, int] = {}
    for a in mine:
        counts[a.label] = counts.get(a.label, 0) + 1
    if not scored:
        return SideSummary(accuracy=100.0, acpl=0, counts=counts)
    return SideSummary(
        accuracy=sum(a.accuracy for a in scored) / len(scored),
        acpl=round(sum(a.cpl for a in scored) / len(scored)),
        counts=counts,
    )
