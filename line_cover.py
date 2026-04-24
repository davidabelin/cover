"""Build and solve a finite line-segment cover for labeled 2D points.

This module owns the mathematical model, independent of where the input came
from and independent of how the result will be drawn. It expects normalized
data:

* ``points`` maps each label to an ``(X, Y)`` coordinate.
* ``tolerance`` is either one global radius or a per-label radius map.

The problem is closest to the classic set cover problem. The universe is the
set of point labels, and each candidate set is the labels covered by one
point-to-point segment. A candidate segment covers another point when the
finite segment intersects that point's tolerance circle. The current solver
uses a NetworkX weighted dominating-set approximation as a practical set-cover
proxy, then removes redundant chosen segments.

Future direction: the same separation should support a 3D version where points
become ``(X, Y, Z)`` and candidate objects are finite 3D segments, rays, or
planes. The set-cover graph does not fundamentally care about dimensionality,
so NetworkX should still work after the geometry predicate is generalized. For
display, prefer building on the existing ``polyhedra`` package tools rather
than inventing a separate 3D visualization stack here.
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import hypot, isfinite
from pathlib import Path

import networkx as nx
from networkx.algorithms import approximation


PointMap = Mapping[str, tuple[float, float]]
ToleranceInput = float | Mapping[str, float]
EXAMPLE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class SegmentCandidate:
    """A finite point-to-point segment available to the cover solver.

    ``a`` and ``b`` are labels of existing input points and define the segment
    endpoints. ``covered`` is the set-cover subset induced by that segment:
    endpoints plus any point whose tolerance circle intersects the segment.
    ``length`` is used only as a deterministic tie-breaker; minimizing the
    number of selected segments is the primary goal.
    """

    a: str
    b: str
    covered: frozenset[str]
    length: float

    @property
    def label(self) -> str:
        return f"{self.a}{self.b}"

    @property
    def is_composite(self) -> bool:
        return len(self.covered) > 2


@dataclass(frozen=True)
class CoverResult:
    """The output of the covering approximation.

    ``selected`` is the solver's chosen cover, suitable for printing or
    highlighting. ``covered_points`` and ``uncovered_points`` are restricted to
    real input labels, while ``graph`` exposes the NetworkX model used to get
    the approximation. ``candidates`` records the candidate list actually fed to
    the graph; callers that want to draw all possible candidates should request
    ``keep_dominated=True`` separately because the solver normally prunes.
    """

    selected: tuple[SegmentCandidate, ...]
    covered_points: frozenset[str]
    uncovered_points: frozenset[str]
    graph: nx.Graph
    candidates: tuple[SegmentCandidate, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.uncovered_points


def point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Return the Euclidean distance from a point to a finite segment.

    This is the geometric predicate behind coverage. A label ``P`` is covered
    by segment ``AB`` exactly when this distance from ``P`` to finite ``AB`` is
    less than or equal to ``P``'s tolerance radius. The projection parameter is
    clamped to ``[0, 1]`` so near misses beyond an endpoint are measured to the
    endpoint, not to the infinite line.
    """

    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay

    segment_length_squared = dx * dx + dy * dy
    if segment_length_squared == 0:
        return hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / segment_length_squared
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    return hypot(px - closest_x, py - closest_y)


def build_segment_candidates(
    points: PointMap,
    tolerance: ToleranceInput,
    *,
    keep_dominated: bool = False,
) -> tuple[SegmentCandidate, ...]:
    """Build all point-pair segment candidates.

    Every pair of points creates a valid candidate segment. A candidate segment
    covers its endpoints and any other point whose tolerance circle intersects
    the finite segment. ``tolerance`` can be a single non-negative float or a
    map from point labels to per-point tolerances. When keep_dominated is false,
    candidates whose covered set is a strict subset of another candidate's
    covered set are removed.

    The resulting candidates are the set-cover subsets. No drawing metadata is
    added here; colors, line widths, and display scales belong in
    ``draw_cover.py``.
    """

    tolerances = _coerce_tolerances(points, tolerance)
    labels = sorted(points)
    candidates: list[SegmentCandidate] = []

    for a, b in combinations(labels, 2):
        start = points[a]
        end = points[b]
        covered = {
            label
            for label, point in points.items()
            if point_to_segment_distance(point, start, end) <= tolerances[label]
        }
        covered.update((a, b))
        candidates.append(
            SegmentCandidate(
                a=a,
                b=b,
                covered=frozenset(covered),
                length=hypot(end[0] - start[0], end[1] - start[1]),
            )
        )

    if keep_dominated:
        return tuple(sorted(candidates, key=_candidate_sort_key))

    return prune_dominated_candidates(candidates)


def prune_dominated_candidates(
    candidates: Iterable[SegmentCandidate],
) -> tuple[SegmentCandidate, ...]:
    """Remove candidates that cannot improve an unweighted set cover.

    If one segment covers a strict subset of another segment, the smaller one is
    never better for minimizing line count. Equal covered sets are deduplicated
    by keeping the shortest stable representative.

    This is intentionally conservative for the current objective: minimize the
    number of selected segments, then use tiny weights/tie-breakers to prefer
    visually and numerically stable answers. Keep dominated candidates when the
    caller wants a complete diagnostic or drawing layer.
    """

    best_by_covered: dict[frozenset[str], SegmentCandidate] = {}
    for candidate in candidates:
        existing = best_by_covered.get(candidate.covered)
        if existing is None or _candidate_sort_key(candidate) < _candidate_sort_key(existing):
            best_by_covered[candidate.covered] = candidate

    unique = sorted(best_by_covered.values(), key=_candidate_sort_key)
    kept: list[SegmentCandidate] = []

    for candidate in unique:
        if any(candidate.covered < other.covered for other in unique):
            continue
        kept.append(candidate)

    return tuple(kept)


def build_cover_graph(
    points: PointMap,
    candidates: Sequence[SegmentCandidate],
) -> nx.Graph:
    """Represent the cover instance as a NetworkX graph.

    Segment nodes connect to the point nodes they cover. A synthetic root node
    connects to every segment node so NetworkX's dominating-set approximation
    can be used as a set-cover approximation.

    The graph is bipartite-ish plus the root:

    * point nodes represent the universe that must be dominated/covered
    * segment nodes represent candidate subsets
    * root prevents segment nodes from needing to dominate one another

    This is an implementation tactic, not a geometric model. If the geometry
    later moves to 3D, this graph layer should remain mostly unchanged.
    """

    graph = nx.Graph()
    graph.add_node("__root__", kind="root", weight=1e-12)

    for label in sorted(points):
        graph.add_node(_point_node(label), kind="point", label=label, weight=1_000_000.0)

    for index, candidate in enumerate(candidates):
        node = _segment_node(index)
        graph.add_node(
            node,
            kind="segment",
            candidate=candidate,
            label=candidate.label,
            weight=_candidate_weight(candidate),
        )
        graph.add_edge("__root__", node)
        for label in candidate.covered:
            graph.add_edge(node, _point_node(label))

    return graph


def approximate_minimum_line_cover(
    points: PointMap,
    tolerance: ToleranceInput,
    *,
    keep_dominated: bool = False,
) -> CoverResult:
    """Approximate the fewest segments needed to cover all points.

    This intentionally treats two-point gray fallback segments and composite
    three-or-more-point segments the same way. Isolated points therefore get
    handled naturally by choosing one of their ordinary endpoint segments.

    Conceptually this solves a finite set cover: choose as few candidate
    point-to-point segments as possible so every input label is covered. The
    implementation uses NetworkX's weighted dominating-set approximation rather
    than an exact integer-programming set-cover solver, which keeps this module
    light and dependency-compatible with the rest of the project.
    """

    if len(points) < 2:
        raise ValueError("at least two points are required")

    candidates = build_segment_candidates(
        points,
        tolerance,
        keep_dominated=keep_dominated,
    )
    graph = build_cover_graph(points, candidates)

    dominating_nodes = approximation.min_weighted_dominating_set(graph, weight="weight")
    selected = _remove_redundant_candidates(
        sorted(
            (
                graph.nodes[node]["candidate"]
                for node in dominating_nodes
                if graph.nodes[node].get("kind") == "segment"
            ),
            key=_candidate_sort_key,
        ),
        required_points=frozenset(points),
    )

    covered = frozenset().union(*(candidate.covered for candidate in selected))
    all_points = frozenset(points)
    return CoverResult(
        selected=selected,
        covered_points=covered & all_points,
        uncovered_points=all_points - covered,
        graph=graph,
        candidates=candidates,
    )


def format_cover(result: CoverResult) -> str:
    """Return a compact, readable description of selected segments.

    This is intentionally text-only. It reports what the solver selected and
    which labels each selected segment covers; it does not depend on the input
    source or drawing conventions.
    """

    lines = []
    for candidate in result.selected:
        kind = "composite" if candidate.is_composite else "gray"
        covered = ", ".join(sorted(candidate.covered))
        lines.append(f"{candidate.label:>4}  {kind:<9} covers {{{covered}}}")

    if result.uncovered_points:
        missing = ", ".join(sorted(result.uncovered_points))
        lines.append(f"uncovered: {{{missing}}}")

    return "\n".join(lines)


def load_points_csv(path: str | Path) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
    """Load normalized point data from a CSV file.

    Required columns are ``label``, ``X``, ``Y``, and ``tol``; header matching
    is case-insensitive. CSV is the direct input format for new data sets:
    coordinates and per-point tolerance radii come from the file and are passed
    unchanged to the solver. Drawing scale choices happen later in
    ``draw_cover.py`` and do not alter these values.
    """

    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        columns = {
            name.strip().lower(): name
            for name in fieldnames
            if name is not None
        }

        required = ("label", "x", "y", "tol")
        missing = [column for column in required if column not in columns]
        if missing:
            available = ", ".join(fieldnames) if fieldnames else "none"
            raise ValueError(
                f"{csv_path} is missing required column(s): {', '.join(missing)} "
                f"(available: {available})"
            )

        label_column = columns["label"]
        x_column = columns["x"]
        y_column = columns["y"]
        tol_column = columns["tol"]
        points: dict[str, tuple[float, float]] = {}
        tolerances: dict[str, float] = {}

        for row_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            label = (row[label_column] or "").strip()
            if not label:
                raise ValueError(f"{csv_path}:{row_number} has an empty label")
            if label in points:
                raise ValueError(f"{csv_path}:{row_number} repeats label {label!r}")

            x = _csv_float(row[x_column], csv_path, row_number, "X")
            y = _csv_float(row[y_column], csv_path, row_number, "Y")
            tol = _csv_float(row[tol_column], csv_path, row_number, "tol")
            _validate_tolerance(tol, label)

            points[label] = (x, y)
            tolerances[label] = tol

    if not points:
        raise ValueError(f"{csv_path} does not contain any points")

    return points, tolerances


def uniform_tolerances(points: PointMap, tolerance: float) -> dict[str, float]:
    """Return a per-label tolerance map using one value for every point.

    This helper exists for examples, command-line overrides, and known drawings
    that do not yet contain recoverable tolerance information. Prefer per-point
    tolerances from CSV or a future image extractor when available.
    """

    return _coerce_tolerances(points, tolerance)


def example_a_points() -> dict[str, tuple[float, float]]:
    """Return the built-in coordinate model derived from example drawing A.

    These coordinates are not read from ``cover_example_A.jpg`` at runtime.
    They are the normalized point data currently associated with that drawing
    by convention. The CSV file can supersede them when explicit coordinates
    and tolerances are desired.
    """

    return {
        "A": (0.0, 8.0),
        "B": (0.0, 1.0),
        "C": (0.0, -3.0),
        "D": (0.6, 5.6),
        "E": (2.0, 0.0),
        "F": (2.0, -2.0),
        "G": (4.0, -1.0),
        "H": (6.0, -8.0),
    }


def example_points() -> dict[str, tuple[float, float]]:
    """Backward-compatible alias for the original example A point set."""

    return example_a_points()


def example_b_points() -> dict[str, tuple[float, float]]:
    """Return the built-in coordinate model for example drawing B.

    B reuses the example A coordinates and adds isolated point ``Q``. As with
    A, this is a known/example mapping rather than general image extraction.
    """

    points = example_a_points()
    points["Q"] = (7.0, 6.0)
    return points


def isolated_Q() -> dict[str, tuple[float, float]]:
    """Backward-compatible alias for the example B point set."""

    return example_b_points()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Approximate a minimal point-to-point line cover.",
    )
    parser.add_argument(
        "csv",
        nargs="?",
        type=Path,
        help="optional CSV with columns label, X, Y, tol",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=EXAMPLE_TOLERANCE,
        help="single tolerance used for the built-in example",
    )
    parser.add_argument(
        "--global-tolerance",
        type=float,
        help="override CSV tol values with one tolerance for every point",
    )
    parser.add_argument(
        "--keep-dominated",
        action="store_true",
        help="keep dominated candidate segments in the solver graph",
    )
    parser.add_argument(
        "--draw",
        action="store_true",
        help="show a Matplotlib diagram of the input map and cover result",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="save the diagram to this image path",
    )
    parser.add_argument(
        "--radius-scale",
        type=float,
        default=100.0,
        help="multiply coordinates and tolerance radii by this display factor when drawing",
    )
    parser.add_argument(
        "--tolerance-display-scale",
        type=float,
        default=4.0,
        help="extra display-only multiplier for tolerance circle radii",
    )
    parser.add_argument(
        "--highlight-selected-two-point",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="draw selected two-point fallback segments with the cover overlay",
    )
    args = parser.parse_args(argv)

    if args.csv:
        points, tolerances = load_points_csv(args.csv)
    else:
        points = example_b_points()
        tolerances = uniform_tolerances(points, args.tolerance)

    if args.global_tolerance is not None:
        tolerances = uniform_tolerances(points, args.global_tolerance)

    cover = approximate_minimum_line_cover(
        points,
        tolerance=tolerances,
        keep_dominated=args.keep_dominated,
    )
    print(format_cover(cover))

    if args.draw or args.output:
        from draw_cover import draw_cover

        all_candidates = build_segment_candidates(
            points,
            tolerances,
            keep_dominated=True,
        )
        draw_cover(
            points,
            tolerances,
            cover,
            candidates=all_candidates,
            output_path=args.output,
            show=args.draw,
            radius_scale=args.radius_scale,
            tolerance_display_scale=args.tolerance_display_scale,
            highlight_selected_two_point=args.highlight_selected_two_point,
        )


def _candidate_weight(candidate: SegmentCandidate) -> float:
    """Return a small tie-breaking weight for the approximation graph.

    All real segment choices are close to weight ``1`` so the solver primarily
    minimizes line count. The tiny coverage and length adjustments only guide
    ambiguous cases toward composite/shorter stable representatives.
    """

    coverage_bonus = 1e-6 * max(0, len(candidate.covered) - 2)
    length_tiebreaker = min(candidate.length, 1_000_000.0) * 1e-12
    return 1.0 - coverage_bonus + length_tiebreaker


def _remove_redundant_candidates(
    candidates: Sequence[SegmentCandidate],
    required_points: frozenset[str],
) -> tuple[SegmentCandidate, ...]:
    selected = list(candidates)

    for candidate in sorted(candidates, key=lambda item: (len(item.covered), -item.length)):
        trial = [item for item in selected if item != candidate]
        covered = frozenset().union(*(item.covered for item in trial))
        if required_points <= covered:
            selected = trial

    return tuple(sorted(selected, key=_candidate_sort_key))


def _candidate_sort_key(candidate: SegmentCandidate) -> tuple[int, float, str, str]:
    return (-len(candidate.covered), candidate.length, candidate.a, candidate.b)


def _coerce_tolerances(points: PointMap, tolerance: ToleranceInput) -> dict[str, float]:
    if isinstance(tolerance, Mapping):
        missing = sorted(set(points) - set(tolerance))
        if missing:
            raise ValueError(f"missing tolerance for point(s): {', '.join(missing)}")

        tolerances: dict[str, float] = {}
        for label in points:
            value = float(tolerance[label])
            _validate_tolerance(value, label)
            tolerances[label] = value
        return tolerances

    value = float(tolerance)
    _validate_tolerance(value)
    return {label: value for label in points}


def _validate_tolerance(value: float, label: str | None = None) -> None:
    if not isfinite(value) or value < 0:
        subject = f" for point {label!r}" if label else ""
        raise ValueError(f"tolerance{subject} must be a finite non-negative number")


def _csv_float(value: str | None, path: Path, row_number: int, column: str) -> float:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{path}:{row_number} has an empty {column} value")

    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{path}:{row_number} has invalid {column} value {text!r}") from exc

    if not isfinite(number):
        raise ValueError(f"{path}:{row_number} has non-finite {column} value {text!r}")
    return number


def _point_node(label: str) -> str:
    return f"point:{label}"


def _segment_node(index: int) -> str:
    return f"segment:{index}"


if __name__ == "__main__":
    main()
