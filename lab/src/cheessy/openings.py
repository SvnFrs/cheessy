"""A small book of mainline openings used to diversify sparring runs.

Without a book every game from the start position is near-identical, which is
useless for study. Randomising the first few plies instead produces positions no
human would reach. Seeding from named theory gives both variety and games you
can actually file under something you're working on.
"""

from __future__ import annotations

import random

import chess
import chess.pgn

# name -> mainline in SAN
BOOK: dict[str, str] = {
    "Ruy Lopez": "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6",
    "Italian Game": "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6",
    "Scotch Game": "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5",
    "Petrov Defense": "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4",
    "Vienna Game": "e4 e5 Nc3 Nf6 f4 d5",
    "Sicilian Najdorf": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6",
    "Sicilian Dragon": "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6",
    "Sicilian Sveshnikov": "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5",
    "French Defense": "e4 e6 d4 d5 Nc3 Bb4",
    "Caro-Kann": "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5",
    "Scandinavian": "e4 d5 exd5 Qxd5 Nc3 Qa5",
    "Pirc Defense": "e4 d6 d4 Nf6 Nc3 g6",
    "Alekhine Defense": "e4 Nf6 e5 Nd5 d4 d6",
    "Queen's Gambit Declined": "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7",
    "Queen's Gambit Accepted": "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6",
    "Slav Defense": "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4",
    "London System": "d4 d5 Bf4 Nf6 e3 e6 Nf3 c5",
    "King's Indian": "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",
    "Nimzo-Indian": "d4 Nf6 c4 e6 Nc3 Bb4",
    "Queen's Indian": "d4 Nf6 c4 e6 Nf3 b6",
    "Gruenfeld Defense": "d4 Nf6 c4 g6 Nc3 d5",
    "Catalan Opening": "d4 Nf6 c4 e6 g3 d5 Bg2 Be7",
    "Benoni Defense": "d4 Nf6 c4 c5 d5 e6",
    "Dutch Defense": "d4 f5 c4 Nf6 g3 e6",
    "English Opening": "c4 e5 Nc3 Nf6 Nf3 Nc6",
    "Reti Opening": "Nf3 d5 c4 e6 g3 Nf6",
}


class OpeningError(ValueError):
    pass


def line_moves(name: str, board: chess.Board | None = None) -> list[chess.Move]:
    """Parse a book line into moves, validating it against the rules."""
    if name not in BOOK:
        raise OpeningError(f"unknown opening {name!r}")
    board = board or chess.Board()
    moves = []
    for san in BOOK[name].split():
        try:
            move = board.parse_san(san)
        except ValueError as exc:
            raise OpeningError(f"{name}: illegal move {san!r} in book line") from exc
        moves.append(move)
        board.push(move)
    return moves


def pick(rng: random.Random, allowed: list[str] | None = None) -> tuple[str, list[chess.Move]]:
    names = allowed if allowed else list(BOOK)
    for name in names:
        if name not in BOOK:
            raise OpeningError(f"unknown opening {name!r}. Run `cheessy openings` to list.")
    name = rng.choice(names)
    return name, line_moves(name)


def validate_book() -> list[str]:
    """Return the names of any book lines that don't parse. Used by tests."""
    broken = []
    for name in BOOK:
        try:
            line_moves(name)
        except OpeningError:
            broken.append(name)
    return broken
