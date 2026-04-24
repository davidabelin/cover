"""Normalize supported cover inputs before solving or drawing.

This module is the input boundary for the small covering project. It answers
one question: given a source, where do ``points`` and ``tolerances`` come from?
After that, file type should not matter. CSV-derived data, known drawing data,
and any future image-derived data should all be converted into the same
``CoverInput`` shape before being passed to ``line_cover.py`` and
``draw_cover.py``.

Current sources:

* CSV files: read explicit ``Label, X, Y, Tol`` values from disk.
* Known drawings: map the bundled examples to their current built-in point
  coordinates and a uniform tolerance unless overridden.

Important boundary: the drawing examples are not general image recognition.
They are aliases for known coordinate models. A future extractor may derive
coordinates and tolerance radii from an image, but it should still return the
same normalized ``CoverInput`` object so solving and drawing remain unchanged.

Future direction: a 3D input path should normalize to point coordinates plus
tolerance radii in 3D, then feed a generalized solver layer. NetworkX should
remain usable for the candidate-cover graph, while 3D display should prefer
``polyhedra`` package tooling.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from line_cover import (
    EXAMPLE_TOLERANCE,
    approximate_minimum_line_cover,
    build_segment_candidates,
    example_a_points,
    example_b_points,
    format_cover,
    load_points_csv,
    uniform_tolerances,
)


InputKind = Literal["auto", "csv", "drawing"]
PointMap = dict[str, tuple[float, float]]
ToleranceMap = dict[str, float]

CSV_SUFFIXES = {".csv"}
DRAWING_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff"}


@dataclass(frozen=True)
class CoverInput:
    """Normalized input data ready for solving and drawing.

    ``points`` and ``tolerances`` are the canonical handoff between readers,
    solver, and renderer. ``source_kind`` records how the data was obtained,
    while ``source_name`` is for titles and diagnostics only; neither should
    alter solver or drawing behavior.
    """

    points: PointMap
    tolerances: ToleranceMap
    source_kind: Literal["csv", "drawing"]
    source_name: str


def read_cover_input(
    source: str | Path | None = None,
    *,
    kind: InputKind = "auto",
    tolerance: float = EXAMPLE_TOLERANCE,
    global_tolerance: float | None = None,
) -> CoverInput:
    """Read a source and return normalized cover input data.

    ``kind='auto'`` infers from extension first, so ``cover_example_A.csv`` is
    treated as CSV even though its stem resembles a known drawing alias. This
    preserves the rule that file type controls extraction only; once extracted,
    normalized data follows the same solve/draw path.
    """

    source_path = Path(source) if source is not None else None
    resolved_kind = _resolve_kind(source_path, kind)

    if resolved_kind == "csv":
        if source_path is None:
            raise ValueError("CSV input requires a source path")
        points, tolerances = load_points_csv(source_path)
        if global_tolerance is not None:
            tolerances = uniform_tolerances(points, global_tolerance)
        return CoverInput(
            points=dict(points),
            tolerances=dict(tolerances),
            source_kind="csv",
            source_name=str(source_path),
        )

    effective_tolerance = global_tolerance if global_tolerance is not None else tolerance
    return read_drawing_input(source_path, tolerance=effective_tolerance)


def read_drawing_input(
    source: str | Path | None = None,
    *,
    tolerance: float = EXAMPLE_TOLERANCE,
) -> CoverInput:
    """Return normalized data for one of the bundled example drawings.

    This is currently a known-example mapping, not image analysis. The point
    coordinates come from ``line_cover.example_a_points`` or
    ``line_cover.example_b_points``. Tolerances come from the supplied uniform
    value because the current JPG examples do not encode machine-readable
    per-point tolerance radii.
    """

    drawing = _resolve_known_drawing(source)
    if drawing == "A":
        points = example_a_points()
        source_name = "cover_example_A"
    else:
        points = example_b_points()
        source_name = "cover_example_B"

    return CoverInput(
        points=points,
        tolerances=uniform_tolerances(points, tolerance),
        source_kind="drawing",
        source_name=source_name,
    )


def solve_cover_input(
    cover_input: CoverInput,
    *,
    keep_dominated: bool = False,
):
    """Send normalized input data to the line-cover solver."""

    return approximate_minimum_line_cover(
        cover_input.points,
        cover_input.tolerances,
        keep_dominated=keep_dominated,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Read a cover input source and compute its line cover.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        help="CSV path, known drawing path, or omitted for example drawing B",
    )
    parser.add_argument(
        "--kind",
        choices=("auto", "csv", "drawing"),
        default="auto",
        help="input type; auto uses the source extension or known example name",
    )
    parser.add_argument(
        "--example",
        choices=("A", "B"),
        help="use one of the bundled hand-drawn example inputs",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=EXAMPLE_TOLERANCE,
        help="uniform tolerance for drawing/example input",
    )
    parser.add_argument(
        "--global-tolerance",
        type=float,
        help="override CSV tol values, or override drawing tolerance",
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

    if args.example and args.source is not None:
        parser.error("provide either a source path or --example, not both")
    if args.example and args.kind == "csv":
        parser.error("--example requires --kind auto or --kind drawing")

    source = args.source
    kind: InputKind = args.kind
    if args.example:
        source = Path(f"example-{args.example.lower()}")
        kind = "drawing"

    cover_input = read_cover_input(
        source,
        kind=kind,
        tolerance=args.tolerance,
        global_tolerance=args.global_tolerance,
    )
    result = solve_cover_input(cover_input, keep_dominated=args.keep_dominated)
    print(format_cover(result))

    if args.draw or args.output:
        from draw_cover import draw_cover

        all_candidates = build_segment_candidates(
            cover_input.points,
            cover_input.tolerances,
            keep_dominated=True,
        )
        draw_cover(
            cover_input.points,
            cover_input.tolerances,
            result,
            candidates=all_candidates,
            output_path=args.output,
            show=args.draw,
            title=f"Line Cover: {cover_input.source_name}",
            radius_scale=args.radius_scale,
            tolerance_display_scale=args.tolerance_display_scale,
            highlight_selected_two_point=args.highlight_selected_two_point,
        )


def _resolve_kind(source: Path | None, kind: InputKind) -> Literal["csv", "drawing"]:
    """Resolve the extraction path for a source.

    Extension checks intentionally precede drawing-name aliases. A CSV named
    like an example image still contains explicit CSV data and must not be
    redirected to the known-drawing shortcut.
    """

    if kind != "auto":
        return kind
    if source is None:
        return "drawing"

    suffix = source.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return "csv"
    if suffix in DRAWING_SUFFIXES:
        return "drawing"
    if _drawing_alias(source) is not None:
        return "drawing"

    raise ValueError(
        f"could not infer input type from {source!s}; use --kind csv or --kind drawing"
    )


def _resolve_known_drawing(source: str | Path | None) -> Literal["A", "B"]:
    """Resolve a drawing source to one of the bundled example identifiers."""

    alias = _drawing_alias(source)
    if alias is not None:
        return alias

    source_text = "example B" if source is None else str(source)
    raise ValueError(
        f"{source_text!r} is not a recognized drawing input. "
        "Supported drawing inputs are --example A, --example B, "
        "cover_example_A.jpg, and cover_example_B.jpg."
    )


def _drawing_alias(source: str | Path | None) -> Literal["A", "B"] | None:
    """Return the bundled drawing alias named by ``source``, if any."""

    if source is None:
        return "B"

    path = Path(source)
    keys = {
        _normalize_alias(str(source)),
        _normalize_alias(path.name),
        _normalize_alias(path.stem),
    }

    if keys & {"a", "example-a", "cover-example-a"}:
        return "A"
    if keys & {"b", "example-b", "cover-example-b"}:
        return "B"
    return None


def _normalize_alias(value: str) -> str:
    """Normalize loose user-facing drawing aliases for comparison."""

    return value.strip().lower().replace("_", "-").replace(" ", "-")


if __name__ == "__main__":
    main()
