"""Tests for the pure logic: no engine binary required.

The evaluation sweep is driven by a scripted fake engine so the POV arithmetic
is checked against hand-computed numbers rather than against whatever Stockfish
happens to say today.
"""

from __future__ import annotations

import io

import chess
import chess.engine
import chess.pgn
import pytest

from cheessy import openings
from cheessy.annotate import (
    MATE_CP,
    annotate_game,
    classify,
    material_balance,
    move_accuracy,
    win_percent,
)
from cheessy.engines import EngineError, resolve
from cheessy.report import eval_text


class FakeEngine:
    """Returns scripted side-to-move-POV centipawn scores, one per analyse()."""

    def __init__(self, scores: list[int], pvs: list[list[str]] | None = None):
        self.scores = list(scores)
        self.pvs = list(pvs) if pvs else []
        self.calls = 0

    def analyse(self, board: chess.Board, limit):
        cp = self.scores[self.calls]
        pv_sans = self.pvs[self.calls] if self.calls < len(self.pvs) else []
        self.calls += 1
        pv = []
        probe = board.copy()
        for san in pv_sans:
            move = probe.parse_san(san)
            pv.append(move)
            probe.push(move)
        return {
            "score": chess.engine.PovScore(chess.engine.Cp(cp), board.turn),
            "pv": pv,
        }


def game_from_sans(sans: list[str]) -> chess.pgn.Game:
    game = chess.pgn.Game()
    node = game
    board = chess.Board()
    for san in sans:
        move = board.parse_san(san)
        node = node.add_variation(move)
        board.push(move)
    return game


# --- opening book -----------------------------------------------------------

def test_every_book_line_is_legal():
    assert openings.validate_book() == []


def test_book_lines_are_distinct_positions():
    seen = {}
    for name in openings.BOOK:
        board = chess.Board()
        for move in openings.line_moves(name):
            board.push(move)
        seen.setdefault(board.board_fen(), []).append(name)
    dupes = {fen: names for fen, names in seen.items() if len(names) > 1}
    assert not dupes, f"book lines transpose into the same position: {dupes}"


def test_unknown_opening_raises():
    with pytest.raises(openings.OpeningError):
        openings.line_moves("Nonexistent Defense")


# --- win probability --------------------------------------------------------

def test_win_percent_is_symmetric_and_monotonic():
    assert win_percent(0) == pytest.approx(50.0)
    assert win_percent(300) == pytest.approx(100 - win_percent(-300))
    assert win_percent(-500) < win_percent(0) < win_percent(500)


def test_accuracy_falls_with_bigger_drops():
    assert move_accuracy(0) == pytest.approx(100.0, abs=0.5)
    assert move_accuracy(5) > move_accuracy(20) > move_accuracy(50)
    assert 0 <= move_accuracy(100) <= 100


# --- the POV identity -------------------------------------------------------

def test_loss_uses_opponent_pov_flip():
    """White plays 1.e4, engine said +50 before and -20 after (Black's POV).

    -20 for Black is +20 for White, so White gave up 30cp.
    """
    game = game_from_sans(["e4"])
    engine = FakeEngine([50, -20])
    report = annotate_game(game, engine, limit=None)

    (ann,) = report.annotations
    assert ann.color == chess.WHITE
    assert ann.cp_before == 50
    assert ann.cp_after == 20
    assert ann.cpl == 30


def test_loss_is_zero_when_evaluation_holds():
    game = game_from_sans(["e4"])
    # +50 for White, then -50 for Black == +50 for White: nothing lost.
    report = annotate_game(game, FakeEngine([50, -50]), limit=None)
    assert report.annotations[0].cpl == 0


def test_black_moves_are_scored_from_blacks_side():
    game = game_from_sans(["e4", "e5"])
    # p0 White +30 | p1 Black -30 (equal) | p2 White +400 (Black collapsed)
    report = annotate_game(game, FakeEngine([30, -30, 400]), limit=None)
    black_move = report.annotations[1]
    assert black_move.color == chess.BLACK
    assert black_move.cp_before == -30
    assert black_move.cp_after == -400
    assert black_move.cpl == 370
    assert black_move.label == "Blunder"


def test_one_analysis_per_position_including_the_last():
    game = game_from_sans(["e4", "e5", "Nf3"])
    engine = FakeEngine([20, -20, 20, -20])
    annotate_game(game, engine, limit=None)
    assert engine.calls == 4  # 3 moves + terminal position


def test_terminal_mate_is_not_searched():
    """A finished game has no move to look for; the mated side is simply lost."""
    game = game_from_sans(["f3", "e5", "g4", "Qh4#"])
    engine = FakeEngine([0, 0, 0, 0])  # only 4 scores: no 5th analyse call
    report = annotate_game(game, engine, limit=None)
    assert engine.calls == 4
    assert report.annotations[-1].cp_after == MATE_CP


# --- classification ---------------------------------------------------------

@pytest.mark.parametrize(
    "drop,expected",
    [(0.1, "Excellent"), (3.0, "Good"), (7.0, "Inaccuracy"),
     (15.0, "Mistake"), (40.0, "Blunder")],
)
def test_classification_bands(drop, expected):
    assert classify(drop, is_best=False, forced=False, in_book=False,
                    sacrificed=False, cp_after=0) == expected


def test_best_move_beats_the_excellent_band():
    assert classify(0.1, is_best=True, forced=False, in_book=False,
                    sacrificed=False, cp_after=0) == "Best"


def test_forced_and_book_outrank_everything():
    assert classify(90.0, is_best=False, forced=True, in_book=False,
                    sacrificed=False, cp_after=0) == "Forced"
    assert classify(90.0, is_best=False, forced=False, in_book=True,
                    sacrificed=False, cp_after=0) == "Book"


def test_sacrifice_only_brilliant_when_it_holds_up():
    assert classify(0.2, is_best=True, forced=False, in_book=False,
                    sacrificed=True, cp_after=120) == "Brilliant"
    # Same sacrifice, but the position is lost afterwards: not brilliant.
    assert classify(0.2, is_best=True, forced=False, in_book=False,
                    sacrificed=True, cp_after=-400) == "Best"


def test_book_plies_are_excluded_from_accuracy():
    game = game_from_sans(["e4", "e5", "Nf3"])
    # A dreadful third move that should still leave book moves unscored.
    report = annotate_game(game, FakeEngine([20, -20, 20, 600]), limit=None, book_plies=2)
    labels = [a.label for a in report.annotations]
    assert labels[:2] == ["Book", "Book"]
    assert report.summaries[chess.WHITE].counts["Book"] == 1
    # White's accuracy reflects only move 2 (Nf3), not the book opener.
    assert report.summaries[chess.WHITE].accuracy < 60


# --- material and formatting ------------------------------------------------

def test_material_balance_is_zero_at_the_start():
    assert material_balance(chess.Board(), chess.WHITE) == 0


def test_material_balance_counts_a_missing_queen():
    board = chess.Board()
    board.remove_piece_at(chess.D8)  # black queen off
    assert material_balance(board, chess.WHITE) == 900
    assert material_balance(board, chess.BLACK) == -900


def test_eval_text_formats_pawns_and_mate():
    assert eval_text(0) == "+0.00"
    assert eval_text(-135) == "-1.35"
    assert eval_text(MATE_CP - 5) == "#5"
    assert eval_text(-(MATE_CP - 5)) == "#-5"
    assert eval_text(MATE_CP) == "#0"  # mate already on the board


def test_mate_distance_survives_a_round_trip_through_povscore():
    """Regression: Mate(n) counts moves, not plies. Halving it under-reports."""
    for n in (1, 2, 3, 7, 12):
        score = chess.engine.PovScore(chess.engine.Mate(n), chess.WHITE)
        cp = score.relative.score(mate_score=MATE_CP)
        assert eval_text(cp) == f"#{n}", f"Mate({n}) rendered as {eval_text(cp)}"
        neg = chess.engine.PovScore(chess.engine.Mate(-n), chess.WHITE)
        assert eval_text(neg.relative.score(mate_score=MATE_CP)) == f"#-{n}"


# --- engine specs -----------------------------------------------------------

def test_spec_rejects_out_of_range_elo():
    with pytest.raises(EngineError, match="UCI_Elo"):
        resolve("sf:elo=600")


def test_spec_rejects_unknown_params():
    with pytest.raises(EngineError, match="unknown engine param"):
        resolve("sf:aggression=11")


def test_spec_rejects_unknown_engine():
    with pytest.raises(EngineError, match="unknown engine"):
        resolve("houdini")


# --- sacrifice detection ----------------------------------------------------
# Regression cover for the "one ply deep" bug: looking only at the opponent's
# reply sees every capture and none of the recaptures, so ordinary trades read
# as sacrifices and almost every quiet move came back labelled Brilliant.

from cheessy.annotate import PositionEval, _is_sacrifice  # noqa: E402


def _pv(board: chess.Board, sans: list[str]) -> list[chess.Move]:
    probe, moves = board.copy(), []
    for san in sans:
        move = probe.parse_san(san)
        moves.append(move)
        probe.push(move)
    return moves


def test_capture_then_recapture_is_not_a_sacrifice():
    """5.h3 Bxf3 6.Qxf3 is an even trade, not a knight sacrifice."""
    board = chess.Board()
    for san in ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5", "Nf3", "Bg4"]:
        board.push_san(san)

    move = board.parse_san("h3")
    after = board.copy()
    after.push(move)
    ev = PositionEval(cp=-100, pv=_pv(after, ["Bxf3", "Qxf3", "c6"]))

    assert not _is_sacrifice(board, move, ev, chess.WHITE)


def test_real_sacrifice_is_detected():
    """Greek gift: Bxh7+ Kxh7 Ng5+ leaves White a bishop down for one pawn."""
    board = chess.Board(
        "r1bq1rk1/ppp2ppp/2n1pn2/3p4/1b1P4/2NBPN2/PPP2PPP/R1BQ1RK1 w - - 0 1"
    )
    move = board.parse_san("Bxh7+")
    after = board.copy()
    after.push(move)
    ev = PositionEval(cp=-50, pv=_pv(after, ["Kxh7", "Ng5+", "Kg8"]))

    assert _is_sacrifice(board, move, ev, chess.WHITE)


def test_empty_pv_never_claims_a_sacrifice():
    board = chess.Board()
    move = board.parse_san("e4")
    assert not _is_sacrifice(board, move, PositionEval(cp=0, pv=[]), chess.WHITE)


def test_odd_length_pv_is_truncated_to_a_balanced_line():
    """A single-ply PV can only show the capture, never the recapture."""
    board = chess.Board()
    for san in ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5", "Nf3", "Bg4"]:
        board.push_san(san)
    move = board.parse_san("h3")
    after = board.copy()
    after.push(move)
    # Only Bxf3 given: too short to resolve, so we must decline rather than guess.
    ev = PositionEval(cp=-100, pv=_pv(after, ["Bxf3"]))
    assert not _is_sacrifice(board, move, ev, chess.WHITE)


def test_quiet_move_with_a_quiet_pv_is_not_brilliant():
    game = game_from_sans(["e4", "e5", "Nf3"])
    engine = FakeEngine(
        [30, -30, 30, -30],
        # Each PV is from the POV of whoever is to move in that position.
        pvs=[["e4"], ["e5"], ["Nf3"], ["Nc6", "Bb5", "a6"]],
    )
    report = annotate_game(game, engine, limit=None)
    assert all(a.label != "Brilliant" for a in report.annotations)


def test_sacrifice_in_an_already_won_position_is_not_brilliant():
    """Giving back material at +8 is technique. Brilliance needs stakes."""
    assert classify(0.2, is_best=True, forced=False, in_book=False,
                    sacrificed=True, cp_after=800, cp_before=848) == "Best"
    # The same sacrifice from a balanced position still counts.
    assert classify(0.2, is_best=True, forced=False, in_book=False,
                    sacrificed=True, cp_after=60, cp_before=40) == "Brilliant"
