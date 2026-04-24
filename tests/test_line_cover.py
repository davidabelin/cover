import pytest

from line_cover import (
    EXAMPLE_TOLERANCE,
    approximate_minimum_line_cover,
    build_segment_candidates,
    example_a_points,
    example_b_points,
    load_points_csv,
    point_to_segment_distance,
    uniform_tolerances,
)


def _candidates_by_label():
    return {
        candidate.label: candidate
        for candidate in build_segment_candidates(
            example_a_points(),
            EXAMPLE_TOLERANCE,
            keep_dominated=True,
        )
    }


def test_point_to_segment_distance_uses_finite_segment():
    assert point_to_segment_distance((1.0, 1.0), (0.0, 0.0), (2.0, 0.0)) == pytest.approx(1.0)
    assert point_to_segment_distance((3.0, 0.0), (0.0, 0.0), (2.0, 0.0)) == pytest.approx(1.0)


def test_example_a_candidates_match_colored_composites():
    candidates = _candidates_by_label()
    expected = {
        "AC": {"A", "B", "C"},
        "AE": {"A", "D", "E"},
        "BG": {"B", "E", "G"},
        "BH": {"B", "F", "H"},
        "CG": {"C", "F", "G"},
    }

    for label, covered in expected.items():
        assert candidates[label].covered == covered

    composite_labels = {
        label
        for label, candidate in candidates.items()
        if candidate.is_composite
    }
    assert composite_labels == set(expected)
    assert "G" not in candidates["DH"].covered


def test_solver_covers_example_a_with_three_composite_lines():
    result = approximate_minimum_line_cover(
        example_a_points(),
        tolerance=EXAMPLE_TOLERANCE,
    )

    assert result.is_complete
    assert len(result.selected) == 3
    assert {candidate.label for candidate in result.selected} == {"AE", "BH", "CG"}
    assert all(candidate.is_composite for candidate in result.selected)


def test_solver_handles_isolated_q_with_one_gray_line():
    result = approximate_minimum_line_cover(
        example_b_points(),
        tolerance=EXAMPLE_TOLERANCE,
    )
    q_segments = [
        candidate
        for candidate in result.selected
        if "Q" in candidate.covered
    ]

    assert result.is_complete
    assert len(result.selected) == 4
    assert {candidate.label for candidate in result.selected} == {"AE", "BH", "CG", "DQ"}
    assert len(q_segments) == 1
    assert not q_segments[0].is_composite
    assert q_segments[0].covered == {"D", "Q"}


def test_negative_tolerance_is_rejected():
    with pytest.raises(ValueError, match="tolerance"):
        build_segment_candidates(example_a_points(), tolerance=-1.0)


def test_per_point_tolerance_uses_segment_circle_intersection():
    points = {
        "A": (0.0, 0.0),
        "B": (2.0, 0.0),
        "C": (1.0, 0.2),
    }

    wide_tolerances = {"A": 0.0, "B": 0.0, "C": 0.25}
    wide_candidates = {
        candidate.label: candidate
        for candidate in build_segment_candidates(
            points,
            wide_tolerances,
            keep_dominated=True,
        )
    }
    assert wide_candidates["AB"].covered == {"A", "B", "C"}

    tight_tolerances = {"A": 0.0, "B": 0.0, "C": 0.1}
    tight_candidates = {
        candidate.label: candidate
        for candidate in build_segment_candidates(
            points,
            tight_tolerances,
            keep_dominated=True,
        )
    }
    assert tight_candidates["AB"].covered == {"A", "B"}


def test_load_points_csv_reads_coordinates_and_tolerances(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text(
        "label,X,Y,tol\nA,0,1,0.2\nB,2,3,0.4\n",
        encoding="utf-8",
    )

    points, tolerances = load_points_csv(path)

    assert points == {"A": (0.0, 1.0), "B": (2.0, 3.0)}
    assert tolerances == {"A": 0.2, "B": 0.4}


def test_draw_cover_saves_png(tmp_path):
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    from draw_cover import SELECTED_OVERLAY_WIDTH, SELECTED_TWO_POINT_COLOR, draw_cover

    points = example_b_points()
    tolerances = uniform_tolerances(points, 0.2)
    result = approximate_minimum_line_cover(points, tolerances)
    candidates = build_segment_candidates(points, tolerances, keep_dominated=True)
    output_path = tmp_path / "cover.png"

    fig, _ax = draw_cover(
        points,
        tolerances,
        result,
        candidates=candidates,
        output_path=output_path,
    )
    try:
        assert output_path.exists()
        assert output_path.stat().st_size > 0
        assert sorted(patch.radius for patch in _ax.patches) == [80.0] * len(points)
        selected_overlay_lines = [
            line
            for line in _ax.lines
            if line.get_linewidth() == SELECTED_OVERLAY_WIDTH
        ]
        assert len(selected_overlay_lines) == len(result.selected)
        two_point_overlay_lines = [
            line
            for line in selected_overlay_lines
            if line.get_color() == SELECTED_TWO_POINT_COLOR
        ]
        assert len(two_point_overlay_lines) == 1
    finally:
        plt.close(fig)


def test_draw_cover_uses_radius_scale_in_data_units(tmp_path):
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    from draw_cover import draw_cover

    path = tmp_path / "points.csv"
    path.write_text(
        "Label,X,Y,Tol\nA,0,0,0.003\nB,1,0,0.015\nC,0.5,0.01,0.0025\n",
        encoding="utf-8",
    )
    points, tolerances = load_points_csv(path)
    result = approximate_minimum_line_cover(points, tolerances)

    fig, ax = draw_cover(points, tolerances, result, radius_scale=100.0)
    try:
        assert sorted(patch.radius for patch in ax.patches) == pytest.approx([1.0, 1.2, 6.0])
        assert ax.patches[0].center == pytest.approx((0.0, 0.0))
        assert ax.patches[1].center == pytest.approx((100.0, 0.0))
        assert ax.patches[2].center == pytest.approx((50.0, 1.0))
        assert list(ax.lines[0].get_xdata()) == pytest.approx([0.0, 100.0])
        assert list(ax.lines[0].get_ydata()) == pytest.approx([0.0, 0.0])
    finally:
        plt.close(fig)
