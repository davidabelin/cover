# Covering Rules

This project currently solves a 2D point-to-point line-segment covering problem,
but the useful abstraction is broader than line segments. A maintainer should
think of the project in two layers:

- **Geometry layer:** decides what candidate objects exist and which point
  labels each candidate covers.
- **Cover layer:** chooses a small set of candidates whose covered-label union
  includes all required points.

The second layer is closest to the classic **set cover** problem. The universe
is the set of point labels. Each geometric candidate contributes one subset of
that universe. The solver tries to select as few subsets as possible.

Current file responsibilities:

- `read_cover.py` normalizes input into `points` and `tolerances`.
- `line_cover.py` builds segment candidates and solves the cover approximation.
- `draw_cover.py` renders normalized input data plus solver results.

Once data is normalized, input file type should not affect the covering rule.
CSV input, known drawing input, and future image-derived input should all feed
the same candidate-generation and solving logic.

## Current Rule

The current rule in `line_cover.py` is:

1. Every pair of points creates a finite segment candidate.
2. The candidate always covers its two endpoint labels.
3. The candidate also covers any other point whose tolerance circle intersects
   the finite segment.

In code terms, a point `P` is covered by segment `AB` when:

```python
point_to_segment_distance(points[P], points[A], points[B]) <= tolerances[P]
```

Because every pair of points creates a candidate and endpoints are always
covered, the current model has a built-in two-point fallback. Any input with at
least two points is usually coverable, even if some points are isolated from all
3+ point alignments.

The current candidate is represented by `SegmentCandidate`:

```python
@dataclass(frozen=True)
class SegmentCandidate:
    a: str
    b: str
    covered: frozenset[str]
    length: float
```

This is intentionally simple, but it is also segment-specific. If the project
adds several different covering rules, a more general candidate type may become
useful.

## NetworkX Does Not Care About Geometry

NetworkX only needs a finite graph or set system. It does not care whether a
candidate came from a segment, a right angle, a circle, a 3D plane, or some
future rule.

The general conversion is:

```python
import networkx as nx


def build_set_cover_graph(points, candidates):
    graph = nx.Graph()
    graph.add_node("__root__", kind="root", weight=1e-12)

    for label in points:
        graph.add_node(f"point:{label}", kind="point", weight=1_000_000.0)

    for index, candidate in enumerate(candidates):
        node = f"candidate:{index}"
        graph.add_node(
            node,
            kind="candidate",
            candidate=candidate,
            weight=1.0,
        )
        graph.add_edge("__root__", node)

        for label in candidate.covered:
            graph.add_edge(node, f"point:{label}")

    return graph
```

That is essentially what `build_cover_graph` in `line_cover.py` does today,
with segment-specific naming.

The important contract is:

```python
candidate.covered == frozenset({"A", "B", "C"})
```

Once that exists, the cover solver can be largely rule-agnostic.

## Rule Variant: 3+ Lines Only

A stricter rule could say that ordinary two-point fallback segments do not
count. A candidate is valid only if it covers at least three points.

The candidate-generation change is small:

```python
def build_three_point_line_candidates(points, tolerances):
    candidates = []

    for a, b in combinations(sorted(points), 2):
        covered = {
            label
            for label, point in points.items()
            if point_to_segment_distance(point, points[a], points[b]) <= tolerances[label]
        }
        covered.update((a, b))

        if len(covered) >= 3:
            candidates.append(
                SegmentCandidate(
                    a=a,
                    b=b,
                    covered=frozenset(covered),
                    length=hypot(points[b][0] - points[a][0], points[b][1] - points[a][1]),
                )
            )

    return tuple(candidates)
```

Under this rule, coverability is no longer guaranteed. Example B would likely
leave isolated `Q` uncovered unless some 3+ candidate also covers it. Example C
may also expose uncovered points if its selected cover currently depends on
2-point fallback segments.

The solver does not need a special case for this. It already reports
`uncovered_points` in `CoverResult`.

## Rule Variant: Right-Angle Vertex

Another rule could define coverage through right angles. For example, a point
`B` is covered if it is the vertex of a right angle formed with two other points
`A` and `C`.

A right-angle predicate can be written with a dot product:

```python
from math import hypot


def is_right_angle(a, b, c, tolerance):
    bax = a[0] - b[0]
    bay = a[1] - b[1]
    bcx = c[0] - b[0]
    bcy = c[1] - b[1]

    ba_length = hypot(bax, bay)
    bc_length = hypot(bcx, bcy)
    if ba_length == 0 or bc_length == 0:
        return False

    # Normalize so tolerance is angular-ish rather than coordinate-scale-ish.
    normalized_dot = (bax * bcx + bay * bcy) / (ba_length * bc_length)
    return abs(normalized_dot) <= tolerance
```

Then a candidate generator might be:

```python
from dataclasses import dataclass
from itertools import permutations


@dataclass(frozen=True)
class RightAngleCandidate:
    a: str
    vertex: str
    c: str
    covered: frozenset[str]

    @property
    def label(self):
        return f"{self.a}{self.vertex}{self.c}"


def build_right_angle_candidates(points, angle_tolerance=1e-6):
    candidates = []

    for a, b, c in permutations(sorted(points), 3):
        if is_right_angle(points[a], points[b], points[c], angle_tolerance):
            candidates.append(
                RightAngleCandidate(
                    a=a,
                    vertex=b,
                    c=c,
                    covered=frozenset({b}),
                )
            )

    return tuple(candidates)
```

The design question is not whether NetworkX can handle this. It can. The design
question is what the candidate should cover.

Possible interpretations:

- A right-angle candidate covers only the vertex.
- A right-angle candidate covers all three participating points.
- A right-angle candidate covers the vertex plus points near either leg.
- A right-angle candidate covers points that participate in the same inferred
  orthogonal structure.

Each interpretation produces a different set-cover instance.

## Toward Rule-Agnostic Candidates

If the project keeps adding rule types, `SegmentCandidate` may become too
specific. A future candidate shape could look like this:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CoverCandidate:
    id: str
    kind: str
    anchors: tuple[str, ...]
    covered: frozenset[str]
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

Examples:

```python
CoverCandidate(
    id="segment:A-G",
    kind="segment",
    anchors=("A", "G"),
    covered=frozenset({"A", "B", "G"}),
)

CoverCandidate(
    id="right-angle:A-B-C",
    kind="right_angle",
    anchors=("A", "B", "C"),
    covered=frozenset({"B"}),
)
```

With a rule-agnostic candidate, the pipeline becomes:

```text
input source -> normalized points/tolerances
normalized data -> one or more candidate generators
candidates -> NetworkX/set-cover solver
result -> renderer aware of candidate kinds
```

`line_cover.py` could then become the segment-rule generator rather than the
only solver module.

## Weighted Variants

The current objective is mostly "fewest selected segments." Small weight
adjustments prefer composite and shorter candidates only as tie-breakers.

Other rules may want stronger weights:

```python
def candidate_weight(candidate):
    if candidate.kind == "right_angle":
        return 1.2
    if candidate.kind == "segment" and len(candidate.covered) >= 3:
        return 1.0
    return 1.5
```

NetworkX's weighted dominating-set approximation can use these weights, but
maintainers should remember that this is still an approximation. If exact
minimal covers become important, this project may eventually need an exact
set-cover formulation through integer programming or exhaustive search for
small instances.

## 3D Extension

A 3D version should keep the same split:

- Input layer normalizes labels to `(X, Y, Z)` and tolerance radii.
- Geometry layer generates 3D candidates and covered label sets.
- Cover layer remains NetworkX/set-cover-like.
- Display layer uses 3D tooling.

The distance predicate for finite 3D segments is a direct generalization of the
current 2D `point_to_segment_distance`. NetworkX should still work because its
graph is built from labels and candidate coverage sets, not from coordinates.

For display, prefer using the `polyhedra` package already present in the
workspace dependencies. A 3D renderer should not be bolted onto the 2D
Matplotlib renderer unless it can stay cleanly separated.

## Maintainer Rule Of Thumb

When adding a covering rule, answer these questions first:

1. What geometric objects count as candidates?
2. How are candidates enumerated from normalized input data?
3. Which point labels does each candidate cover?
4. Are 2-point or otherwise trivial candidates allowed?
5. Is a full cover guaranteed, or should uncovered points be expected?
6. Does the renderer need a new visual convention for this candidate kind?

If the answer to question 3 is a finite `covered` set for every candidate,
NetworkX can probably handle the cover-selection part.
