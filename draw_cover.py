"""Draw normalized line-cover inputs and solver results with Matplotlib.

This module is deliberately downstream of input parsing and solving. It does
not decide whether data came from CSV, a known drawing, or a future image
extraction pipeline. It receives normalized point coordinates, per-point
tolerances, and a ``CoverResult``-like object, then renders those facts.

The visual grammar is:

* all point-to-point candidate segments: thin gray background network
* tolerance radii: low-alpha circles centered on each point
* composite candidates covering 3+ points: vibrant colored lines
* selected cover segments: wider translucent overlays

Selected 2-point fallback segments are real covering lines, but their overlay
stays gray so they do not masquerade as a 3+ composite line. Composite line
colors come from the covered point closest to the segment midpoint.

Display scale is not solver scale. ``radius_scale`` multiplies coordinates and
base tolerance radii for readability, preserving geometric offsets. Then
``tolerance_display_scale`` expands only the drawn tolerance circles so tiny
radii remain visible. The solver still uses the raw values supplied to
``line_cover.py``.

Future direction: a 3D renderer should likely live beside this module but use
the ``polyhedra`` package tools for display. The solver graph can remain
NetworkX-based as long as the 3D geometry layer emits normalized candidate
coverage sets.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
from math import isfinite
from pathlib import Path
from typing import Any

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib.colors import to_hex, to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

PointMap = Mapping[str, tuple[float, float]]
ToleranceMap = Mapping[str, float]
Candidate = Any
DEFAULT_RADIUS_SCALE = 100.0
DEFAULT_TOLERANCE_DISPLAY_SCALE = 1.0

BASE_NETWORK_WIDTH = 0.5
COMPOSITE_LINE_WIDTH = 0.5
SELECTED_OVERLAY_WIDTH = 3.0
SELECTED_TWO_POINT_COLOR = "#444842"
POINT_SIZE = 4
CIRCLE_FILL_ALPHA = 0.02
CIRCLE_EDGE_ALPHA = 0.95
CIRCLE_EDGE_WIDTH = 0.2

def draw_cover(
    points: PointMap,
    tolerances: ToleranceMap,
    result: Any,
    *,
    candidates: Sequence[Candidate] | None = None,
    output_path: str | Path | None = None,
    show: bool = False,
    ax: Any | None = None,
    title: str = "Line Cover",
    radius_scale: float = DEFAULT_RADIUS_SCALE,
    tolerance_display_scale: float = DEFAULT_TOLERANCE_DISPLAY_SCALE,
    highlight_selected_two_point: bool = True,
) -> tuple[Any, Any]:
    """Draw the input point map with candidate and selected cover overlays.

    ``radius_scale`` is a display scale applied to both coordinates and
    tolerance radii. Keeping them on the same scale preserves the line-to-point
    offsets used by the coverage test. ``tolerance_display_scale`` then expands
    tolerance circles only, so very small radii remain discernible.

    ``points`` and ``tolerances`` should already be normalized by
    ``read_cover.py`` or ``line_cover.load_points_csv``. ``result`` is expected
    to provide a ``selected`` sequence of segment candidates. ``candidates`` is
    optional but should contain the full unpruned candidate list when the caller
    wants all 3+ candidates drawn, not merely the selected cover.
    """

    labels = sorted(points)
    if not labels:
        raise ValueError("at least one point is required to draw a cover")
    if not isfinite(radius_scale) or radius_scale < 0:
        raise ValueError("radius_scale must be a finite non-negative number")
    if not isfinite(tolerance_display_scale) or tolerance_display_scale < 0:
        raise ValueError("tolerance_display_scale must be a finite non-negative number")

    missing = sorted(set(points) - set(tolerances))
    if missing:
        raise ValueError(f"missing tolerance for point(s): {', '.join(missing)}")

    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    else:
        fig = ax.figure

    colors = _point_colors(labels)
    selected = tuple(getattr(result, "selected", ()))
    all_candidates = tuple(candidates if candidates is not None else selected)
    display_points = _scale_points(points, radius_scale)
    display_tolerances = _scale_tolerances(
        tolerances,
        radius_scale * tolerance_display_scale,
    )

    ax.set_title(title, fontsize=14, weight="bold")
    ax.set_facecolor("#f2f2f2")
    ax.grid(True, color="#d1d5db", linewidth=0.8)
    ax.set_axisbelow(True)

    _draw_complete_network(ax, display_points, labels)
    _draw_tolerance_circles(ax, display_points, display_tolerances, labels, colors)
    _draw_composite_candidates(ax, display_points, all_candidates, colors)
    _draw_selected_cover(
        ax,
        display_points,
        selected,
        colors,
        highlight_selected_two_point=highlight_selected_two_point,
    )
    _draw_points(ax, display_points, labels, colors)
    _set_bounds(ax, display_points, display_tolerances)
    _draw_legend(ax, highlight_selected_two_point=highlight_selected_two_point)

    ax.set_aspect("equal", adjustable="box")
    axis_suffix = f" (x{radius_scale:g})" if radius_scale != 1.0 else ""
    ax.set_xlabel(f"X{axis_suffix}")
    ax.set_ylabel(f"Y{axis_suffix}")

    if output_path:
        fig.savefig(output_path, dpi=180, facecolor=fig.get_facecolor())
    if show:
        plt.show()

    return fig, ax


def _draw_complete_network(ax: Any, points: PointMap, labels: Sequence[str]) -> None:
    """Draw every point-to-point segment as the low-emphasis base network."""

    for a, b in combinations(labels, 2):
        ax.plot(
            [points[a][0], points[b][0]],
            [points[a][1], points[b][1]],
            color="#525558",
            linewidth=BASE_NETWORK_WIDTH,
            alpha=0.2,
            zorder=1,
        )


def _draw_tolerance_circles(
    ax: Any,
    points: PointMap,
    tolerances: ToleranceMap,
    labels: Sequence[str],
    colors: Mapping[str, str],
) -> None:
    """Draw per-point tolerance circles in display coordinates.

    These circles show the radius used by the coverage predicate, after the
    drawing-only scale factors have been applied by ``draw_cover``.
    """

    for label in labels:
        color = colors[label]
        circle = Circle(
            points[label],
            tolerances[label],
            facecolor=to_rgba(color, CIRCLE_FILL_ALPHA),
            edgecolor=to_rgba(color, CIRCLE_EDGE_ALPHA),
            linewidth=CIRCLE_EDGE_WIDTH,
            zorder=2,
        )
        ax.add_patch(circle)


def _draw_composite_candidates(
    ax: Any,
    points: PointMap,
    candidates: Sequence[Candidate],
    colors: Mapping[str, str],
) -> None:
    """Draw all 3+ point candidate segments before selected overlays."""

    for candidate in candidates:
        if len(candidate.covered) < 3:
            continue
        color = _candidate_color(candidate, points, colors)
        ax.plot(
            [points[candidate.a][0], points[candidate.b][0]],
            [points[candidate.a][1], points[candidate.b][1]],
            color=color,
            linewidth=COMPOSITE_LINE_WIDTH,
            alpha=0.8,
            solid_capstyle="round",
            zorder=3,
        )


def _draw_selected_cover(
    ax: Any,
    points: PointMap,
    selected: Sequence[Candidate],
    colors: Mapping[str, str],
    *,
    highlight_selected_two_point: bool,
) -> None:
    """Draw translucent overlays for the chosen covering segments.

    Composite selected segments retain their midpoint-derived point color.
    Selected 2-point fallback segments are highlighted in gray, matching their
    role as ordinary fallback cover lines rather than composite lines.
    """

    for candidate in selected:
        if len(candidate.covered) < 3 and not highlight_selected_two_point:
            continue

        xs = [points[candidate.a][0], points[candidate.b][0]]
        ys = [points[candidate.a][1], points[candidate.b][1]]
        color = (
            _candidate_color(candidate, points, colors)
            if len(candidate.covered) >= 3
            else SELECTED_TWO_POINT_COLOR
        )
        ax.plot(
            xs,
            ys,
            color=color,
            linewidth=SELECTED_OVERLAY_WIDTH,
            alpha=0.2,
            solid_capstyle="round",
            zorder=4,
        )


def _draw_points(
    ax: Any,
    points: PointMap,
    labels: Sequence[str],
    colors: Mapping[str, str],
) -> None:
    """Draw small point markers and labels above the line/circle layers."""

    for label in labels:
        x, y = points[label]
        ax.scatter(
            [x],
            [y],
            s=POINT_SIZE,
            color=colors[label],
            edgecolor="#ffffff",
            linewidth=0.6,
            zorder=6,
        )
        text = ax.annotate(
            label,
            (x, y),
            xytext=(6, 6),
            textcoords="offset points",
            color="#111827",
            fontsize=10,
            weight="bold",
            zorder=7,
        )
        text.set_path_effects(
            [path_effects.withStroke(linewidth=1.2, foreground="#f2f2f2")]
        )


def _set_bounds(ax: Any, points: PointMap, tolerances: ToleranceMap) -> None:
    """Set plot bounds to include all scaled points and tolerance circles."""

    left = min(x - tolerances[label] for label, (x, _y) in points.items())
    right = max(x + tolerances[label] for label, (x, _y) in points.items())
    bottom = min(y - tolerances[label] for label, (_x, y) in points.items())
    top = max(y + tolerances[label] for label, (_x, y) in points.items())

    width = max(right - left, 1.0)
    height = max(top - bottom, 1.0)
    pad = max(width, height) * 0.08
    ax.set_xlim(left - pad, right + pad)
    ax.set_ylim(bottom - pad, top + pad)


def _draw_legend(ax: Any, *, highlight_selected_two_point: bool) -> None:
    """Add a compact legend for the drawing grammar."""

    selected_label = (
        "selected cover overlay"
        if highlight_selected_two_point
        else "selected 3+ cover overlay"
    )
    handles = [
        Line2D(
            [0],
            [0],
            color="#464151",
            linewidth=BASE_NETWORK_WIDTH,
            alpha=0.25,
            label="point-to-point segments",
        ),
        Line2D(
            [0],
            [0],
            color="#2533eb",
            linewidth=COMPOSITE_LINE_WIDTH,
            alpha=0.8,
            label="3+ point candidates",
        ),
        Line2D(
            [0],
            [0],
            color="#2563eb",
            linewidth=SELECTED_OVERLAY_WIDTH,
            alpha=0.2,
            label=selected_label,
        ),
    ]
    ax.legend(handles=handles, loc="best", frameon=True, facecolor="#f9fafb")


def _candidate_color(
    candidate: Candidate,
    points: PointMap,
    colors: Mapping[str, str],
) -> str:
    """Choose the display color for a composite candidate.

    The color is keyed to the covered point closest to the segment midpoint,
    matching the visual convention requested for 3+ point lines.
    """

    midpoint = (
        (points[candidate.a][0] + points[candidate.b][0]) / 2.0,
        (points[candidate.a][1] + points[candidate.b][1]) / 2.0,
    )
    middle_label = min(
        candidate.covered,
        key=lambda label: (
            _squared_distance(points[label], midpoint),
            label,
        ),
    )
    return colors[middle_label]


def _squared_distance(
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _scale_points(points: PointMap, scale: float) -> dict[str, tuple[float, float]]:
    """Return point coordinates in drawing units."""

    return {
        label: (point[0] * scale, point[1] * scale)
        for label, point in points.items()
    }


def _scale_tolerances(tolerances: ToleranceMap, scale: float) -> dict[str, float]:
    """Return tolerance radii in drawing units."""

    return {
        label: tolerance * scale
        for label, tolerance in tolerances.items()
    }


def _point_colors(labels: Sequence[str]) -> dict[str, str]:
    """Assign stable, vibrant colors to point labels."""

    vibrant = (
        "#0067ff",
        "#ff7a00",
        "#00a33c",
        "#d800a6",
        "#e00022",
        "#00a7b5",
        "#7a3cff",
        "#8ab800",
        "#ffbf00",
        "#ff4f8b",
        "#00856f",
        "#a35a00",
        "#4a6cff",
        "#d43d00",
        "#0091ff",
        "#b000d4",
    )
    if len(labels) <= len(vibrant):
        colors = list(vibrant[: len(labels)])
    else:
        cmap = colormaps["hsv"].resampled(len(labels) + 1)
        colors = [to_hex(cmap(index)) for index in range(len(labels))]

    return dict(zip(labels, colors, strict=True))
