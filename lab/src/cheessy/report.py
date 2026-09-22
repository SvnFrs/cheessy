"""Rendering: annotated PGN out, and a readable summary in the terminal."""

from __future__ import annotations

import chess
import chess.pgn
from rich.console import Console
from rich.table import Table

from .annotate import MATE_CP, Annotation, GameReport

# Numeric Annotation Glyphs, so the PGN renders with ?!/?/??/!! anywhere.
NAGS = {
    "Brilliant": 3,   # !!
    "Inaccuracy": 6,  # ?!
    "Mistake": 2,     # ?
    "Blunder": 4,     # ??
}

STYLES = {
    "Brilliant": "bold cyan",
    "Best": "green",
    "Excellent": "green",
    "Good": "dim green",
    "Book": "dim",
    "Forced": "dim",
    "Inaccuracy": "yellow",
    "Mistake": "orange1",
    "Blunder": "bold red",
}

LABEL_ORDER = [
    "Brilliant", "Best", "Excellent", "Good",
    "Book", "Forced", "Inaccuracy", "Mistake", "Blunder",
]


def eval_text(cp: int) -> str:
    """Format an evaluation the way PGN readers expect: pawns, or #N for mate.

    python-chess reports ``Mate(n)`` with n already counted in *moves*, and
    ``score(mate_score=M)`` returns ``M - n``. So the distance is ``M - |cp|``
    directly -- halving it again (as if n were plies) reports every mate at
    roughly half its true distance. ``#0`` means mate is already on the board.
    """
    if abs(cp) >= MATE_CP - 999:
        moves = MATE_CP - abs(cp)
        return f"#{'-' if cp < 0 else ''}{moves}"
    return f"{cp / 100:+.2f}"


def annotated_pgn(game: chess.pgn.Game, report: GameReport) -> chess.pgn.Game:
    """Rebuild the game with eval comments and NAGs on every move."""
    out = chess.pgn.Game()
    out.headers.update(game.headers)
    out.headers["Annotator"] = "cheessy-lab"
    for color, side in (("White", chess.WHITE), ("Black", chess.BLACK)):
        summary = report.summaries[side]
        out.headers[f"{color}Accuracy"] = f"{summary.accuracy:.1f}"
        out.headers[f"{color}ACPL"] = str(summary.acpl)

    node: chess.pgn.GameNode = out
    for move, ann in zip(game.mainline_moves(), report.annotations):
        node = node.add_variation(move)
        if ann.label in NAGS:
            node.nags.add(NAGS[ann.label])
        # Evals are written from White's POV, which is the PGN convention.
        white_pov = ann.cp_after if ann.color == chess.WHITE else -ann.cp_after
        comment = f"[%eval {eval_text(white_pov)}]"
        if ann.is_error and ann.best_san and not ann.is_best:
            comment += f" {ann.label}. Better was {ann.best_san}."
        elif ann.label in ("Brilliant", "Best"):
            comment += f" {ann.label}."
        node.comment = comment
    return out


def _summary_table(report: GameReport) -> Table:
    table = Table(box=None, pad_edge=False)
    table.add_column("", style="dim")
    table.add_column(report.headers.get("White", "White"), justify="right")
    table.add_column(report.headers.get("Black", "Black"), justify="right")

    w, b = report.summaries[chess.WHITE], report.summaries[chess.BLACK]
    table.add_row("Accuracy", f"{w.accuracy:.1f}%", f"{b.accuracy:.1f}%")
    table.add_row("Avg loss", f"{w.acpl} cp", f"{b.acpl} cp")
    for label in LABEL_ORDER:
        wc, bc = w.counts.get(label, 0), b.counts.get(label, 0)
        if wc or bc:
            style = STYLES.get(label, "")
            table.add_row(f"[{style}]{label}[/]" if style else label, str(wc), str(bc))
    return table


def _moment_line(ann: Annotation) -> str:
    dots = "." if ann.color == chess.WHITE else "..."
    style = STYLES.get(ann.label, "")
    better = f"  better: [green]{ann.best_san}[/]" if ann.best_san and not ann.is_best else ""
    return (
        f"  {ann.move_number}{dots}{ann.san:<8} "
        f"[{style}]{ann.label:<10}[/] "
        f"{eval_text(ann.cp_before):>7} -> {eval_text(ann.cp_after):>7}"
        f"  (-{ann.win_drop:.0f}% win){better}"
    )


def print_report(report: GameReport, console: Console, max_moments: int = 8) -> None:
    h = report.headers
    console.print(
        f"\n[bold]{h.get('White', '?')}[/] vs [bold]{h.get('Black', '?')}[/]"
        f"  [dim]{h.get('Result', '*')}"
        f"{'  ' + h['Opening'] if h.get('Opening') else ''}"
        f"{'  (' + h['Termination'] + ')' if h.get('Termination') else ''}[/]"
    )
    console.print(_summary_table(report))

    moments = sorted(report.errors(), key=lambda a: a.win_drop, reverse=True)
    if moments:
        console.print("\n[bold]Critical moments[/]")
        for ann in moments[:max_moments]:
            console.print(_moment_line(ann))
        if len(moments) > max_moments:
            console.print(f"  [dim]... and {len(moments) - max_moments} more[/]")

    brilliant = [a for a in report.annotations if a.label == "Brilliant"]
    if brilliant:
        console.print("\n[bold cyan]Sacrifices that worked[/]")
        for ann in brilliant:
            console.print(_moment_line(ann))


def print_match_summary(reports: list[GameReport], console: Console) -> None:
    """Aggregate across a whole sparring run, keyed by engine label."""
    if not reports:
        return
    per_engine: dict[str, list[float]] = {}
    per_engine_cpl: dict[str, list[int]] = {}
    score: dict[str, float] = {}

    for report in reports:
        names = {chess.WHITE: report.headers.get("White", "?"),
                 chess.BLACK: report.headers.get("Black", "?")}
        for color, name in names.items():
            per_engine.setdefault(name, []).append(report.summaries[color].accuracy)
            per_engine_cpl.setdefault(name, []).append(report.summaries[color].acpl)
            score.setdefault(name, 0.0)
        result = report.headers.get("Result", "*")
        if result == "1-0":
            score[names[chess.WHITE]] += 1
        elif result == "0-1":
            score[names[chess.BLACK]] += 1
        elif result == "1/2-1/2":
            score[names[chess.WHITE]] += 0.5
            score[names[chess.BLACK]] += 0.5

    table = Table(title=f"\n{len(reports)} games", box=None)
    table.add_column("Engine")
    table.add_column("Score", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Avg loss", justify="right")
    for name, accs in per_engine.items():
        cpls = per_engine_cpl[name]
        table.add_row(
            name,
            f"{score[name]:g}/{len(accs)}",
            f"{sum(accs) / len(accs):.1f}%",
            f"{round(sum(cpls) / len(cpls))} cp",
        )
    console.print(table)


def report_to_dict(game: chess.pgn.Game, report: GameReport) -> dict:
    """Serialise a reviewed game for the browser viewer.

    Evaluations are carried twice on purpose: `cp` from the mover's point of
    view (what "this move lost 40cp" means) and `cp_white` from White's, which
    is the only frame an evaluation graph can be drawn in without the line
    flipping sign every ply.
    """
    moves = []
    for ann in report.annotations:
        moves.append({
            "ply": ann.ply,
            "n": ann.move_number,
            "color": "w" if ann.color == chess.WHITE else "b",
            "san": ann.san,
            "uci": ann.uci,
            "cp": ann.cp_after,
            "cp_white": ann.cp_after if ann.color == chess.WHITE else -ann.cp_after,
            "label": ann.label,
            "best": ann.best_san,
            "is_best": ann.is_best,
            "drop": round(ann.win_drop, 1),
            "acc": round(ann.accuracy, 1),
        })

    def side(color: chess.Color) -> dict:
        s = report.summaries[color]
        return {"accuracy": round(s.accuracy, 1), "acpl": s.acpl, "counts": s.counts}

    h = report.headers
    return {
        "white": h.get("White", "?"),
        "black": h.get("Black", "?"),
        "result": h.get("Result", "*"),
        "opening": h.get("Opening", ""),
        "termination": h.get("Termination", ""),
        "book_plies": int(h.get("BookPlies", 0) or 0),
        "summary": {"white": side(chess.WHITE), "black": side(chess.BLACK)},
        "moves": moves,
    }
