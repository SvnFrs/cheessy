"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import chess
import chess.engine
import chess.pgn
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

from . import engines, openings, report, spar, watch
from .annotate import annotate_game
from .engines import EngineError

MAIA_URL = "https://github.com/CSSLab/maia-chess/raw/master/maia_weights/maia-{r}.pb.gz"
MAIA_RATINGS = tuple(range(1100, 2000, 100))

console = Console()
err_console = Console(stderr=True)


def _progress() -> Progress:
    return Progress(
        TextColumn("[dim]{task.description}"),
        BarColumn(),
        TextColumn("[dim]{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    )


def cmd_engines(args: argparse.Namespace) -> int:
    found = engines.discover()
    for name, path in found.items():
        if path:
            console.print(f"[green]found[/]    {name:<12} {path}")
        else:
            console.print(f"[yellow]missing[/]  {name:<12} -")
    if not found["stockfish"]:
        console.print("\n  Install Stockfish:  [bold]sudo pacman -S stockfish[/]")
    if not found["lc0"]:
        console.print("  Install lc0 (only needed for Maia):  [bold]yay -S lc0[/]")

    weights = sorted(engines.WEIGHTS_DIR.glob("maia-*.pb.gz")) if engines.WEIGHTS_DIR.exists() else []
    if weights:
        console.print("\n[bold]Maia weights[/]")
        for w in weights:
            console.print(f"  {w.stem.replace('.pb', '')}  [dim]{w}[/]")
    return 0


def cmd_openings(args: argparse.Namespace) -> int:
    broken = openings.validate_book()
    for name, line in openings.BOOK.items():
        flag = " [red](invalid)[/]" if name in broken else ""
        console.print(f"  [bold]{name:<26}[/] [dim]{line}[/]{flag}")
    return 1 if broken else 0


def cmd_fetch_maia(args: argparse.Namespace) -> int:
    ratings = [args.rating] if args.rating else list(MAIA_RATINGS)
    engines.WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    for rating in ratings:
        if rating not in MAIA_RATINGS:
            err_console.print(
                f"[red]Maia has no {rating} model.[/] Available: "
                + ", ".join(str(r) for r in MAIA_RATINGS)
            )
            return 2
        dest = engines.maia_weights(rating)
        if dest.exists() and not args.force:
            console.print(f"[dim]have[/]  maia-{rating}  {dest}")
            continue
        url = MAIA_URL.format(r=rating)
        console.print(f"[dim]get[/]   maia-{rating}  {url}")
        try:
            urllib.request.urlretrieve(url, dest)
        except (urllib.error.URLError, OSError) as exc:
            err_console.print(f"[red]download failed:[/] {exc}")
            return 1
        console.print(f"[green]ok[/]    maia-{rating}  {dest}")
    return 0


def cmd_spar(args: argparse.Namespace) -> int:
    white = engines.resolve(args.white)
    black = engines.resolve(args.black)

    cfg = spar.SparConfig(
        games=args.games,
        seed=args.seed,
        max_plies=args.max_plies,
        resign_cp=args.resign_cp,
        allowed_openings=args.opening,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    games: list[chess.pgn.Game] = []

    console.print(f"[bold]{white.label}[/] vs [bold]{black.label}[/]  ({cfg.games} games)")
    with out_path.open("w", encoding="utf-8") as fh, _progress() as bar:
        task = bar.add_task("sparring", total=cfg.games)
        for game in spar.run(white, black, cfg):
            print(game, file=fh, end="\n\n", flush=True)
            games.append(game)
            bar.advance(task)

    console.print(f"[green]wrote[/] {len(games)} games -> {out_path}")

    if args.review:
        return _review_games(games, args.review_depth, out_path.with_suffix(".annotated.pgn"))
    console.print(f"\nReview them with:  [bold]cheessy review {out_path}[/]")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    white = engines.resolve(args.white)
    black = engines.resolve(args.black)
    cfg = spar.SparConfig(
        games=args.games,
        seed=args.seed,
        max_plies=args.max_plies,
        resign_cp=args.resign_cp,
        allowed_openings=args.opening,
    )

    hub = watch.EventHub()
    try:
        server = watch.start_server(hub, args.port)
    except OSError as exc:
        err_console.print(f"[red]could not bind port {args.port}:[/] {exc}")
        return 1
    url = f"http://127.0.0.1:{args.port}"
    console.print(f"[bold]{white.label}[/] vs [bold]{black.label}[/]  ({cfg.games} games)")
    console.print(f"[green]viewer[/] {url}")
    if not args.no_browser:
        watch.open_in_browser(url)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    games: list[chess.pgn.Game] = []

    def on_game_start(index, total, white_label, black_label, opening):
        hub.publish({
            "t": "game_start", "index": index, "total": total,
            "white": white_label, "black": black_label, "opening": opening,
        })

    def on_move(board, move, cp_white):
        hub.publish({
            "t": "move",
            "svg": watch.board_svg(board, move),
            "san": watch.san_for(board, move),
            "cp": cp_white,
        })

    def on_game(game):
        hub.publish({
            "t": "game_end",
            "result": game.headers.get("Result", "*"),
            "termination": game.headers.get("Termination", ""),
        })

    try:
        with out_path.open("w", encoding="utf-8") as fh:
            for game in spar.run(white, black, cfg, on_game=on_game,
                                 on_move=on_move, on_game_start=on_game_start):
                print(game, file=fh, end="\n\n", flush=True)
                games.append(game)
    except KeyboardInterrupt:
        console.print("\n[yellow]stopped[/]")
    hub.publish({"t": "done", "total": len(games)})

    console.print(f"[green]wrote[/] {len(games)} games -> {out_path}")
    console.print(f"Review them with:  [bold]cheessy review {out_path}[/]")
    console.print("[dim]viewer still up; Ctrl+C to stop[/]")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/]")
    finally:
        server.shutdown()
    return 0


def _load_games(path: Path) -> list[chess.pgn.Game]:
    games = []
    with path.open(encoding="utf-8") as fh:
        while (game := chess.pgn.read_game(fh)) is not None:
            games.append(game)
    return games


def _review_games(games: list[chess.pgn.Game], depth: int, out_path: Path | None) -> int:
    try:
        analyser = engines.resolve(f"sf:depth={depth}")
    except EngineError as exc:
        err_console.print(f"[red]{exc}[/]")
        return 2

    total_plies = sum(len(list(g.mainline_moves())) + 1 for g in games)
    reports = []
    out_fh = out_path.open("w", encoding="utf-8") if out_path else None

    try:
        with analyser.open() as engine, _progress() as bar:
            task = bar.add_task(f"analysing at depth {depth}", total=total_plies)
            for game in games:
                book_plies = int(game.headers.get("BookPlies", 0) or 0)
                rep = annotate_game(
                    game, engine, analyser.limit,
                    book_plies=book_plies,
                    progress=lambda: bar.advance(task),
                )
                reports.append(rep)
                if out_fh:
                    print(report.annotated_pgn(game, rep), file=out_fh, end="\n\n")
    finally:
        if out_fh:
            out_fh.close()

    for rep in reports:
        report.print_report(rep, console)
    if len(reports) > 1:
        report.print_match_summary(reports, console)
    if out_path:
        console.print(f"\n[green]wrote[/] annotated PGN -> {out_path}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    path = Path(args.pgn)
    if not path.exists():
        err_console.print(f"[red]no such file:[/] {path}")
        return 2
    games = _load_games(path)
    if not games:
        err_console.print(f"[red]no games found in[/] {path}")
        return 2
    if args.limit:
        games = games[: args.limit]
    out = Path(args.output) if args.output else path.with_suffix(".annotated.pgn")
    return _review_games(games, args.depth, out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cheessy",
        description="Local chess sparring and game review.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("engines", help="show which engines are installed")
    p.set_defaults(func=cmd_engines)

    p = sub.add_parser("openings", help="list the sparring opening book")
    p.set_defaults(func=cmd_openings)

    p = sub.add_parser("fetch-maia", help="download Maia weights (needs lc0 to use)")
    p.add_argument("--rating", type=int, help=f"one of {MAIA_RATINGS}; default all")
    p.add_argument("--force", action="store_true", help="re-download existing weights")
    p.set_defaults(func=cmd_fetch_maia)

    p = sub.add_parser("spar", help="play engine vs engine games")
    p.add_argument("--white", default="sf:depth=12", help="engine spec, e.g. sf:elo=1600")
    p.add_argument("--black", default="sf:elo=1500", help="engine spec")
    p.add_argument("-n", "--games", type=int, default=10)
    p.add_argument("-o", "--output", default="games/spar.pgn")
    p.add_argument("--seed", type=int, help="fix opening selection for reproducible runs")
    p.add_argument("--opening", action="append", help="restrict to this opening (repeatable)")
    p.add_argument("--max-plies", type=int, default=300)
    p.add_argument("--resign-cp", type=int, default=900)
    p.add_argument("--review", action="store_true", help="analyse immediately after")
    p.add_argument("--review-depth", type=int, default=18)
    p.set_defaults(func=cmd_spar)

    p = sub.add_parser("watch", help="play games in a live browser viewer")
    p.add_argument("--white", default="sf:depth=12", help="engine spec")
    p.add_argument("--black", default="sf:elo=1500", help="engine spec")
    p.add_argument("-n", "--games", type=int, default=10)
    p.add_argument("-o", "--output", default="games/watch.pgn")
    p.add_argument("--port", type=int, default=7777)
    p.add_argument("--no-browser", action="store_true", help="don't auto-open a tab")
    p.add_argument("--seed", type=int)
    p.add_argument("--opening", action="append", help="restrict to this opening")
    p.add_argument("--max-plies", type=int, default=300)
    p.add_argument("--resign-cp", type=int, default=900)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("review", help="analyse and annotate a PGN")
    p.add_argument("pgn")
    p.add_argument("-d", "--depth", type=int, default=18)
    p.add_argument("-o", "--output", help="annotated PGN path")
    p.add_argument("--limit", type=int, help="only review the first N games")
    p.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except EngineError as exc:
        err_console.print(f"[red]{exc}[/]")
        return 2
    except openings.OpeningError as exc:
        err_console.print(f"[red]{exc}[/]")
        return 2
    except chess.engine.EngineTerminatedError as exc:
        err_console.print(f"[red]engine crashed:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        err_console.print("\n[yellow]interrupted[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
