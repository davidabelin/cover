import pytest

from line_cover import example_a_points, example_b_points
from read_cover import main, read_cover_input


def test_read_cover_input_auto_detects_csv_with_title_case_headers(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text(
        "Label,X,Y,Tol\nA,0,1,0.2\nB,2,3,0.4\n",
        encoding="utf-8",
    )

    cover_input = read_cover_input(path)

    assert cover_input.source_kind == "csv"
    assert cover_input.points == {"A": (0.0, 1.0), "B": (2.0, 3.0)}
    assert cover_input.tolerances == {"A": 0.2, "B": 0.4}


def test_read_cover_input_prefers_csv_extension_over_example_alias(tmp_path):
    path = tmp_path / "cover_example_A.csv"
    path.write_text(
        "Label,X,Y,Tol\nA,0,1,0.2\nB,2,3,0.4\n",
        encoding="utf-8",
    )

    cover_input = read_cover_input(path)

    assert cover_input.source_kind == "csv"
    assert cover_input.points == {"A": (0.0, 1.0), "B": (2.0, 3.0)}
    assert cover_input.tolerances == {"A": 0.2, "B": 0.4}


def test_read_cover_input_can_override_csv_tolerances(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text(
        "Label,X,Y,Tol\nA,0,1,0.2\nB,2,3,0.4\n",
        encoding="utf-8",
    )

    cover_input = read_cover_input(path, global_tolerance=0.5)

    assert cover_input.tolerances == {"A": 0.5, "B": 0.5}


def test_read_cover_input_recognizes_example_drawing_filename():
    cover_input = read_cover_input("cover_example_A.jpg")

    assert cover_input.source_kind == "drawing"
    assert cover_input.points == example_a_points()
    assert cover_input.tolerances == {label: 1e-9 for label in example_a_points()}


def test_read_cover_input_defaults_to_example_b_drawing():
    cover_input = read_cover_input()

    assert cover_input.source_kind == "drawing"
    assert cover_input.points == example_b_points()


def test_unknown_drawing_is_rejected(tmp_path):
    path = tmp_path / "new_sketch.jpg"
    path.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="not a recognized drawing input"):
        read_cover_input(path)


def test_read_cover_cli_writes_drawn_output(tmp_path, capsys):
    import matplotlib

    matplotlib.use("Agg", force=True)

    output_path = tmp_path / "cover.png"

    main(
        [
            "--example",
            "B",
            "--tolerance",
            "0.2",
            "--output",
            str(output_path),
        ]
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert "DQ" in capsys.readouterr().out
