"""Normalize a point CSV into the ``Label,X,Y,Tol`` format used by drawing.

By default, the first column is treated as the label and the first two numeric
columns are normalized independently into the 0..100 drawing range. ``Tol`` is
generated as a small random value below 0.1 percent of that normalized range.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections.abc import Sequence
from pathlib import Path

DEFAULT_DECIMALS = 3
DEFAULT_TOL_DECIMALS = 6
DEFAULT_TOL_PERCENT = 0.0005

def normalize_csv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    label_column: str | None = None,
    x_column: str | None = None,
    y_column: str | None = None,
    decimals: int = DEFAULT_DECIMALS,
    tol_decimals: int = DEFAULT_TOL_DECIMALS,
    tol_percent: float = DEFAULT_TOL_PERCENT,
    seed: int | None = None,
) -> None:
    """Write ``input_path`` as normalized ``Label,X,Y,Tol`` rows."""

    source = Path(input_path)
    destination = Path(output_path)

    with source.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"{source} does not contain a header row")
        rows = list(reader)

    if not rows:
        raise ValueError(f"{source} does not contain any data rows")

    headers = tuple(reader.fieldnames)
    label_header = _resolve_column(label_column, headers, default=headers[0])
    numeric_headers = _numeric_columns(rows, headers)

    x_header = _resolve_axis_column("x", x_column, numeric_headers)
    remaining_numeric = tuple(header for header in numeric_headers if header != x_header)
    y_header = _resolve_axis_column("y", y_column, remaining_numeric)

    x_values = [_csv_float(row[x_header], source, row_number, x_header) for row_number, row in _numbered(rows)]
    y_values = [_csv_float(row[y_header], source, row_number, y_header) for row_number, row in _numbered(rows)]

    normed_x = _normalize_values(x_values, x_header)
    normed_y = _normalize_values(y_values, y_header)
    tolerances = _random_tolerances(len(rows), tol_percent=tol_percent, decimals=tol_decimals, seed=seed)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("Label", "X", "Y", "Tol"))
        for row, x, y, tol in zip(rows, normed_x, normed_y, tolerances, strict=True):
            label = row[label_header].strip()
            if not label:
                raise ValueError(f"{source} has an empty label in column {label_header!r}")
            writer.writerow(
                (
                    label,
                    _format_float(x, decimals, trim=False),
                    _format_float(y, decimals, trim=False),
                    _format_float(tol, tol_decimals, trim=True),
                )
            )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Normalize a CSV to Label,X,Y,Tol for draw_cover.py/read_cover.py.",
    )
    parser.add_argument("input", type=Path, help="source CSV")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="output CSV; defaults to INPUT_STEM_norm.csv next to the source",
    )
    parser.add_argument("--label-column", help="input column to use as Label")
    parser.add_argument("--x-column", help="input column to normalize as X")
    parser.add_argument("--y-column", help="input column to normalize as Y")
    parser.add_argument(
        "--decimals",
        type=int,
        default=DEFAULT_DECIMALS,
        help="decimal places for X and Y",
    )
    parser.add_argument(
        "--tol-decimals",
        type=int,
        default=DEFAULT_TOL_DECIMALS,
        help="decimal places for generated Tol values",
    )
    parser.add_argument(
        "--tol-percent",
        type=float,
        default=DEFAULT_TOL_PERCENT,
        help="maximum Tol as a percentage of the normalized 0..100 range",
    )
    parser.add_argument("--seed", type=int, help="random seed for reproducible Tol values")

    args = parser.parse_args(argv)
    output = args.output or args.input.with_name(f"{args.input.stem}_norm.csv")
    normalize_csv(
        args.input,
        output,
        label_column=args.label_column,
        x_column=args.x_column,
        y_column=args.y_column,
        decimals=args.decimals,
        tol_decimals=args.tol_decimals,
        tol_percent=args.tol_percent,
        seed=args.seed,
    )


def _numbered(rows: list[dict[str, str]]) -> Sequence[tuple[int, dict[str, str]]]:
    return tuple(enumerate(rows, start=2))


def _resolve_column(requested: str | None, headers: Sequence[str], *, default: str) -> str:
    if requested is None:
        return default
    matches = {header.casefold(): header for header in headers}
    try:
        return matches[requested.casefold()]
    except KeyError as error:
        raise ValueError(f"unknown column {requested!r}; available columns: {', '.join(headers)}") from error


def _resolve_axis_column(axis: str, requested: str | None, headers: Sequence[str]) -> str:
    if requested is None:
        if not headers:
            raise ValueError(f"could not infer {axis.upper()} column; provide --{axis}-column")
        return headers[0]
    return _resolve_column(requested, headers, default=headers[0] if headers else "")


def _numeric_columns(rows: Sequence[dict[str, str]], headers: Sequence[str]) -> tuple[str, ...]:
    numeric = []
    for header in headers:
        try:
            for row_number, row in _numbered(list(rows)):
                _csv_float(row[header], Path("<csv>"), row_number, header)
        except ValueError:
            continue
        numeric.append(header)
    if len(numeric) < 2:
        raise ValueError("input CSV must contain at least two numeric columns")
    return tuple(numeric)


def _csv_float(value: str | None, path: Path, row_number: int, column: str) -> float:
    try:
        if value is None:
            raise ValueError
        return float(value.strip())
    except ValueError as error:
        raise ValueError(f"{path}:{row_number} has a non-numeric {column!r} value: {value!r}") from error


def _normalize_values(values: Sequence[float], column: str) -> list[float]:
    low = min(values)
    high = max(values)
    span = high - low
    if span == 0:
        raise ValueError(f"cannot normalize {column!r}; all values are {low:g}")
    return [100.0 * (value - low) / span for value in values]


def _random_tolerances(
    count: int,
    *,
    tol_percent: float,
    decimals: int,
    seed: int | None,
) -> list[float]:
    if tol_percent <= 0:
        raise ValueError("--tol-percent must be greater than zero")
    maximum = tol_percent
    minimum = 10 ** -decimals
    rng = random.Random(seed)
    return [rng.random()/rng.choice([10,50,100,500]) for _ in range(count)]
    #return [rng.uniform(minimum, maximum) for _ in range(count)]

def _format_float(value: float, decimals: int, *, trim: bool) -> str:
    if decimals < 0:
        raise ValueError("decimal counts must be non-negative")
    text = f"{value:.{decimals}f}"
    if trim and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


if __name__ == "__main__":
    main()
