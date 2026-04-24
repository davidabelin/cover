# cover

`cover` is a small, still-under-development project for experimenting with
geometric covering problems. The current implementation solves a 2D
point-to-point line-segment covering problem:

1. Start with labeled points and a tolerance radius for each point.
2. Build every finite segment between every pair of points.
3. Treat a segment as covering its endpoints and any other point whose
   tolerance circle intersects that finite segment.
4. Choose a small set of segments whose covered points include the whole input.

The solver is currently approximate. It models the problem as a finite set
cover and uses NetworkX's weighted dominating-set approximation as a practical
stand-in for an exact minimum set-cover solver.

## Project Status

This is not a finished general-purpose package yet. It is a working prototype
with a useful separation between input normalization, cover solving, and
drawing.

Current capabilities:

- Read normalized point data from CSV files.
- Use known built-in examples for `cover_example_A` and `cover_example_B`.
- Approximate a minimal line-segment cover.
- Draw the full point-to-point network, tolerance circles, composite candidate
  lines, and selected cover lines with Matplotlib.
- Normalize arbitrary CSV point data into the project's `Label,X,Y,Tol` format.

Current limitations:

- Drawing/image input is not image recognition. The recognized drawing names
  are aliases for built-in example coordinates.
- The geometric rule is 2D finite line segments only.
- The cover optimizer is approximate, not guaranteed exact.
- Tolerances matter. Very small tolerances only detect exact or near-exact
  collinearity.

## Repository Layout

```text
cover/
  README.md             this maintainer guide
  covering_rules.md     design notes for current and possible future rules
  line_cover.py         core geometry, candidate generation, solver, CSV loader
  read_cover.py         input boundary for CSV and known drawing examples
  draw_cover.py         Matplotlib renderer for normalized inputs and results
  norm2draw.py          utility for normalizing arbitrary CSV data
  *_norm.csv            sample normalized input files
  hillpnts.csv          source/sample point data
  tests/                pytest coverage for solver, input reading, and drawing
  pytest.ini            pytest path/pythonpath configuration
```

The most important design boundary is:

```text
input source -> normalized points/tolerances -> candidates -> cover result -> drawing
```

Once an input has been normalized, the solver and renderer should not care
whether the data came from a CSV file, a known drawing alias, or a future image
extractor.

## Dependencies

The project uses the Python environment from the parent `geometry` workspace.
The relevant runtime/test dependencies are:

- `networkx`
- `matplotlib`
- `pytest`

From the parent `geometry` directory, install the workspace requirements if the
environment is not already prepared:

```powershell
python -m pip install -r requirements.txt
```

Most commands below assume the current working directory is `geometry\cover`:

```powershell
cd C:\Users\David\Documents\Local_Python\geometry\cover
```

## Input Format

CSV input must contain these columns, matched case-insensitively:

```csv
Label,X,Y,Tol
A,0,0,0.01
B,10,0,0.01
C,5,0.005,0.01
```

Column meanings:

- `Label`: unique point identifier.
- `X`: point x-coordinate.
- `Y`: point y-coordinate.
- `Tol`: tolerance radius for that point.

The tolerance radius is in the same coordinate units as `X` and `Y`. Segment
`AB` covers point `P` when the finite-segment distance from `P` to `AB` is less
than or equal to `P`'s tolerance.

## Running The Solver

Use `read_cover.py` as the main entry point when you want input-type handling:

```powershell
python read_cover.py runpnts_norm.csv
```

Use a built-in example:

```powershell
python read_cover.py --example A
python read_cover.py --example B
```

If no source is provided, `read_cover.py` defaults to example B:

```powershell
python read_cover.py
```

Typical text output looks like this:

```text
  CG  composite covers {C, F, G}
  AE  composite covers {A, D, E}
  BH  composite covers {B, F, H}
  DQ  gray      covers {D, Q}
```

Output line types:

- `composite`: selected segment covers three or more points.
- `gray`: selected ordinary two-point fallback segment.

You can also call `line_cover.py` directly when you already know you are using
CSV input or the built-in example data:

```powershell
python line_cover.py runpnts_norm.csv
python line_cover.py
```

## Drawing Results

Save a rendered diagram:

```powershell
python read_cover.py runpnts_norm.csv --output accumulated_io\runpnts_cover.png
```

Show an interactive Matplotlib window:

```powershell
python read_cover.py --example B --draw
```

Save and show at the same time:

```powershell
python read_cover.py runpnts_norm.csv --output accumulated_io\runpnts_cover.png --draw
```

Drawing options:

- `--radius-scale`: multiplies coordinates and tolerance radii for display.
  Default is `100.0`.
- `--tolerance-display-scale`: additionally enlarges only the drawn tolerance
  circles. This is display-only and does not change solver behavior.
- `--no-highlight-selected-two-point`: hides the selected-cover overlay for
  ordinary two-point fallback segments.

The drawing grammar in `draw_cover.py` is:

- thin gray lines: all point-to-point segments
- colored circles: point tolerance radii
- thin colored lines: candidates covering three or more points
- wide translucent overlays: selected cover segments

## Normalizing New CSV Data

Use `norm2draw.py` when you have a CSV with labels plus at least two numeric
columns and want to convert it to `Label,X,Y,Tol`.

Default behavior:

- first column becomes `Label`
- first numeric column becomes normalized `X`
- second numeric column becomes normalized `Y`
- `X` and `Y` are independently normalized into the `0..100` range
- `Tol` values are generated randomly

Example:

```powershell
python norm2draw.py hillpnts.csv hillpnts_norm.csv --seed 1
```

Specify columns explicitly:

```powershell
python norm2draw.py source.csv source_norm.csv --label-column id --x-column longitude --y-column latitude --seed 1
```

Useful options:

- `--decimals`: decimal places for normalized `X` and `Y`.
- `--tol-decimals`: decimal places for generated `Tol`.
- `--tol-percent`: intended maximum tolerance scale parameter.
- `--seed`: makes generated tolerances reproducible.

Review generated tolerances before treating a normalized file as meaningful
data. The current tolerance generator is a convenience for experiments, not a
domain model.

## Programmatic Use

Minimal solver use:

```python
from line_cover import approximate_minimum_line_cover, format_cover, load_points_csv

points, tolerances = load_points_csv("runpnts_norm.csv")
result = approximate_minimum_line_cover(points, tolerances)

print(format_cover(result))
```

Read through the normalized input boundary:

```python
from read_cover import read_cover_input, solve_cover_input
from line_cover import format_cover

cover_input = read_cover_input("runpnts_norm.csv")
result = solve_cover_input(cover_input)

print(format_cover(result))
```

Draw from Python:

```python
from draw_cover import draw_cover
from line_cover import build_segment_candidates
from read_cover import read_cover_input, solve_cover_input

cover_input = read_cover_input("runpnts_norm.csv")
result = solve_cover_input(cover_input)
candidates = build_segment_candidates(
    cover_input.points,
    cover_input.tolerances,
    keep_dominated=True,
)

draw_cover(
    cover_input.points,
    cover_input.tolerances,
    result,
    candidates=candidates,
    output_path="accumulated_io/runpnts_cover.png",
)
```

## Key Implementation Details

`line_cover.py` owns the mathematical model. Its central data types are:

- `SegmentCandidate`: one finite point-to-point segment and the labels it
  covers.
- `CoverResult`: selected candidates, covered/uncovered labels, the NetworkX
  graph, and the candidate list used by the solver.

Candidate generation happens in `build_segment_candidates()`. Dominated
candidates are pruned by default: if one candidate covers a strict subset of
another candidate, it cannot improve an unweighted minimum line count. Pass
`keep_dominated=True` when you need a complete diagnostic or drawing layer.

Coverage is determined by:

```python
point_to_segment_distance(points[P], points[A], points[B]) <= tolerances[P]
```

`read_cover.py` is the input boundary. It returns a `CoverInput` object with:

- `points`: `dict[str, tuple[float, float]]`
- `tolerances`: `dict[str, float]`
- `source_kind`: currently `csv` or `drawing`
- `source_name`: diagnostic/title text

Known drawing inputs are resolved by name only. Supported aliases include:

- `--example A`
- `--example B`
- `cover_example_A.jpg`
- `cover_example_B.jpg`

`draw_cover.py` is deliberately downstream of parsing and solving. It should
receive normalized data and a cover result; it should not decide where input
data came from.

## Testing

Run the test suite from `geometry\cover`:

```powershell
python -m pytest
```

The tests cover:

- finite point-to-segment distance behavior
- expected candidates for example A
- selected covers for examples A and B
- tolerance validation
- CSV loading
- input-source detection in `read_cover.py`
- PNG rendering through Matplotlib's noninteractive backend

## Maintainer Guidance

Preserve the input/solver/drawing separation. It is the part of the project
most likely to keep future experiments manageable.

When adding a new input source, normalize it to `CoverInput` first. Do not
special-case solver behavior based on file type.

When adding a new geometric covering rule, define these before changing code:

1. What geometric object is a candidate?
2. How are candidates enumerated from normalized input?
3. Which point labels does each candidate cover?
4. Are ordinary two-point fallback candidates allowed?
5. Can inputs be partially uncoverable?
6. What should the renderer show for the new candidate type?

NetworkX does not care about the geometry. It only needs finite candidates with
a `covered` label set. This means future rules such as 3+ point lines,
right-angle structures, circles, or 3D objects can likely share the same cover
selection layer after they produce candidate coverage sets.

If exact minimal covers become important, replace or supplement the current
NetworkX approximation with an exact set-cover solver for small instances or an
integer-programming formulation for larger ones.

For 3D work, keep the same conceptual pipeline:

```text
3D input -> normalized labels/(X,Y,Z)/tolerances -> 3D candidates -> cover solver -> 3D renderer
```

The existing comments recommend using the workspace's `polyhedra` tooling for
future 3D display rather than expanding the 2D Matplotlib renderer into a mixed
2D/3D module.

