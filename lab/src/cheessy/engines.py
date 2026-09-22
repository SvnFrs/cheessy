"""UCI engine discovery, spec parsing and lifecycle.

An engine is named by a small spec string so runs stay reproducible from the
command line:

    sf                      discovered Stockfish, default search limit
    sf:depth=12             fixed depth
    sf:elo=1600             UCI_LimitStrength at a target rating
    sf:skill=5,movetime=100 Skill Level plus a 100ms per-move budget
    maia:1500               lc0 driving Maia weights for that rating band
    /opt/bin/foo:depth=8    any other UCI binary
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import chess.engine

STOCKFISH_NAMES = ("stockfish", "stockfish-git")
LC0_NAMES = ("lc0", "lczero")

# Where `cheessy fetch-maia` drops weights, and where we look for them.
WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "engines" / "weights"

# Stockfish 16+ refuses UCI_Elo below this.
SF_MIN_ELO = 1320
SF_MAX_ELO = 3190

# Params that shape the search rather than the engine's own options.
LIMIT_KEYS = {"depth", "nodes", "movetime"}


class EngineError(RuntimeError):
    pass


def find_binary(names: tuple[str, ...]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def maia_weights(rating: int) -> Path:
    return WEIGHTS_DIR / f"maia-{rating}.pb.gz"


@dataclass
class EngineSpec:
    """A resolved engine: a binary, its UCI options, and a search limit."""

    label: str
    path: str
    options: dict[str, object] = field(default_factory=dict)
    depth: int | None = None
    nodes: int | None = None
    movetime: int | None = None  # milliseconds

    @property
    def limit(self) -> chess.engine.Limit:
        if self.nodes is not None:
            return chess.engine.Limit(nodes=self.nodes)
        if self.movetime is not None:
            return chess.engine.Limit(time=self.movetime / 1000)
        # Maia is a single-node policy net; searching deeper defeats the point.
        return chess.engine.Limit(depth=self.depth if self.depth is not None else 12)

    @contextmanager
    def open(self):
        try:
            engine = chess.engine.SimpleEngine.popen_uci(self.path)
        except FileNotFoundError as exc:
            raise EngineError(f"{self.label}: binary not found at {self.path}") from exc
        try:
            if self.options:
                engine.configure(self.options)
            yield engine
        finally:
            engine.quit()


def _parse_params(raw: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise EngineError(f"malformed engine param {chunk!r}, expected key=value")
        key, value = chunk.split("=", 1)
        params[key.strip().lower()] = value.strip()
    return params


def _split_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Split ``name:params`` while tolerating absolute paths (which contain ':' rarely
    but do contain '/'), and ``maia:1500`` whose first field is bare."""
    if spec.startswith(("/", "./", "~")):
        # Only treat a colon as a param separator after the path component.
        head, sep, tail = spec.partition(":")
        return head, _parse_params(tail) if sep else {}
    head, sep, tail = spec.partition(":")
    if not sep:
        return head, {}
    # `maia:1500` and `maia:1500,movetime=50` -> promote the bare field to rating=
    first = tail.split(",", 1)[0]
    if "=" not in first and first.isdigit():
        rest = tail.split(",", 1)[1] if "," in tail else ""
        params = _parse_params(rest)
        params["rating"] = first
        return head, params
    return head, _parse_params(tail)


def _int_param(params: dict[str, str], key: str) -> int | None:
    if key not in params:
        return None
    try:
        return int(params[key])
    except ValueError as exc:
        raise EngineError(f"{key} must be an integer, got {params[key]!r}") from exc


def _build_stockfish(params: dict[str, str], label: str) -> EngineSpec:
    # Validate the spec before touching the filesystem, so a typo reports the
    # typo rather than a missing binary.
    options: dict[str, object] = {}

    elo = _int_param(params, "elo")
    if elo is not None:
        if not SF_MIN_ELO <= elo <= SF_MAX_ELO:
            raise EngineError(
                f"Stockfish UCI_Elo must be {SF_MIN_ELO}-{SF_MAX_ELO}, got {elo}. "
                f"For weaker play use skill=0..20 instead."
            )
        options["UCI_LimitStrength"] = True
        options["UCI_Elo"] = elo

    skill = _int_param(params, "skill")
    if skill is not None:
        if not 0 <= skill <= 20:
            raise EngineError(f"Stockfish skill must be 0-20, got {skill}")
        options["Skill Level"] = skill

    threads = _int_param(params, "threads")
    if threads is not None:
        options["Threads"] = threads
    hash_mb = _int_param(params, "hash")
    if hash_mb is not None:
        options["Hash"] = hash_mb

    path = find_binary(STOCKFISH_NAMES)
    if not path:
        raise EngineError(
            "Stockfish not found on PATH. Install it with:  sudo pacman -S stockfish"
        )
    return EngineSpec(
        label=label,
        path=path,
        options=options,
        depth=_int_param(params, "depth"),
        nodes=_int_param(params, "nodes"),
        movetime=_int_param(params, "movetime"),
    )


def _build_maia(params: dict[str, str], label: str) -> EngineSpec:
    path = find_binary(LC0_NAMES)
    if not path:
        raise EngineError(
            "Maia needs lc0, which is not on PATH and not in your Arch repos.\n"
            "  Install from the AUR:  yay -S lc0\n"
            "  Then fetch weights:    cheessy fetch-maia\n"
            "Until then, use sf:elo=1500 as a stand-in sparring partner."
        )
    rating = _int_param(params, "rating") or 1500
    weights = maia_weights(rating)
    if not weights.exists():
        raise EngineError(
            f"Maia weights for {rating} not found at {weights}.\n"
            f"Fetch them with:  cheessy fetch-maia --rating {rating}"
        )
    return EngineSpec(
        label=label,
        path=path,
        options={"WeightsFile": str(weights)},
        # Maia models human move choice in one forward pass; a real search would
        # turn it back into an engine. One node is the whole point.
        nodes=_int_param(params, "nodes") or 1,
    )


def resolve(spec: str) -> EngineSpec:
    """Turn a spec string into a launchable EngineSpec."""
    name, params = _split_spec(spec.strip())
    key = name.lower()

    unknown = set(params) - LIMIT_KEYS - {"skill", "elo", "threads", "hash", "rating"}
    if unknown:
        raise EngineError(f"unknown engine param(s): {', '.join(sorted(unknown))}")

    if key in ("sf", "stockfish"):
        return _build_stockfish(params, spec)
    if key == "maia":
        return _build_maia(params, spec)
    if name.startswith(("/", "./", "~")):
        path = str(Path(name).expanduser())
        return EngineSpec(
            label=spec,
            path=path,
            depth=_int_param(params, "depth"),
            nodes=_int_param(params, "nodes"),
            movetime=_int_param(params, "movetime"),
        )
    raise EngineError(
        f"unknown engine {name!r}. Use 'sf', 'maia:<rating>', or an absolute path."
    )


def discover() -> dict[str, str | None]:
    """What's installed right now, for `cheessy engines`."""
    return {
        "stockfish": find_binary(STOCKFISH_NAMES),
        "lc0": find_binary(LC0_NAMES),
    }
