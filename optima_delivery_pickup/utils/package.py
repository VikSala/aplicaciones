"""Pure helpers for one-parcel dimension estimation.

V1 deliberately does not optimize by volume: the sum of the products' volumes
is almost invariant and does not tell us whether a carrier's maximum side
limits are respected.  Instead we estimate the parcel's *outer dimensions*.

Packing policy:

* Identical product x quantity: enumerate rectangular row/column/layer grids
  (including useful grids with a few empty cells) and every unit orientation.
  Choose the envelope that minimizes the longest side, then the second side,
  then the third side.  This gives a real rows/layers optimization for a
  homogeneous product line.
* Different products: first optimize every homogeneous product block using the
  rule above, then combine those rectangular blocks conservatively.  The
  mixed-cart estimator never assumes that unlike products can interlock or fill
  each other's voids.

The result is a safe single-parcel V1 estimate.  It is not a general 3D bin
packing solver, but it avoids the two bad extremes of using volume alone or
placing every unit in one long row.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import permutations
from math import ceil
from typing import Hashable, Iterable, Mapping


def normalize_dimensions(length: float, width: float, height: float) -> tuple[float, float, float]:
    """Return dimensions ordered from longest to shortest, all non-negative."""
    values = [
        max(float(length or 0.0), 0.0),
        max(float(width or 0.0), 0.0),
        max(float(height or 0.0), 0.0),
    ]
    values.sort(reverse=True)
    return values[0], values[1], values[2]


def _layout_key(dimensions: tuple[float, float, float]) -> tuple[float, float, float]:
    """Compare parcel envelopes by longest side, then second, then third."""
    return tuple(sorted((float(value) for value in dimensions), reverse=True))


def _unique_orientations(dimensions: tuple[float, float, float]):
    """Yield the unique axis orientations of one rectangular unit/block."""
    return sorted(set(permutations(dimensions, 3)))


def _grid_shapes(quantity: int):
    """Yield all relevant rectangular grid shapes for ``quantity`` units.

    Shapes are yielded as sorted cell counts ``a <= b <= c``.  For each pair
    ``a, b`` only the smallest ``c`` that can contain the quantity is useful;
    increasing ``c`` can only enlarge the parcel.  Shapes with spare cells are
    intentionally retained because e.g. 3 cubes fit more compactly in a 1x2x2
    envelope than in a 1x1x3 envelope.
    """
    quantity = int(quantity)
    if quantity <= 0:
        return

    a = 1
    while a * a * a <= quantity:
        b = a
        while True:
            c = int(ceil(quantity / float(a * b)))
            if c < b:
                break
            yield a, b, c
            b += 1
        a += 1


def optimize_identical_units(
    length_mm: float,
    width_mm: float,
    height_mm: float,
    quantity: int,
) -> dict[str, object]:
    """Find the most compact rectangular grid for identical units.

    "Most compact" is carrier-oriented rather than volume-oriented: minimize
    the longest outside side, then the second, then the third.  Empty cells are
    allowed when they produce a smaller bounding box for the actual quantity.
    """
    quantity = int(quantity)
    if quantity <= 0:
        return {
            "quantity": 0,
            "length_mm": 0.0,
            "width_mm": 0.0,
            "height_mm": 0.0,
            "grid": (0, 0, 0),
            "capacity": 0,
            "unit_orientation_mm": (0.0, 0.0, 0.0),
        }

    unit = normalize_dimensions(length_mm, width_mm, height_mm)
    if min(unit) <= 0:
        raise ValueError("All item dimensions must be strictly positive")

    best = None
    best_key = None
    for grid in _grid_shapes(quantity):
        capacity = grid[0] * grid[1] * grid[2]
        for orientation in _unique_orientations(unit):
            envelope = (
                grid[0] * orientation[0],
                grid[1] * orientation[1],
                grid[2] * orientation[2],
            )
            normalized_envelope = _layout_key(envelope)
            # Dimensions dominate the decision. Spare cells are only a tie
            # breaker because a slightly under-filled grid can genuinely have
            # much better carrier dimensions (3 cubes: 1x2x2 vs 1x1x3).
            key = normalized_envelope + (capacity - quantity,)
            if best_key is None or key < best_key:
                best_key = key
                best = {
                    "quantity": quantity,
                    "length_mm": normalized_envelope[0],
                    "width_mm": normalized_envelope[1],
                    "height_mm": normalized_envelope[2],
                    "grid": tuple(int(value) for value in grid),
                    "capacity": int(capacity),
                    "unit_orientation_mm": tuple(float(value) for value in orientation),
                }

    if best is None:
        raise ValueError("Unable to build a packing grid")
    return best


def _conservative_combine_blocks(blocks: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Combine unlike rectangular blocks without assuming interlocking.

    Every homogeneous block is first normalized longest-to-shortest.  Three
    guaranteed layouts are considered: concatenate blocks along the longest,
    middle or shortest common axis.  Each layout is physically realizable
    because blocks occupy disjoint slabs; the best carrier envelope is chosen.
    """
    normalized = [_layout_key(block) for block in blocks]
    if not normalized:
        return 0.0, 0.0, 0.0
    if len(normalized) == 1:
        return normalized[0]

    layouts = (
        (
            sum(block[0] for block in normalized),
            max(block[1] for block in normalized),
            max(block[2] for block in normalized),
        ),
        (
            max(block[0] for block in normalized),
            sum(block[1] for block in normalized),
            max(block[2] for block in normalized),
        ),
        (
            max(block[0] for block in normalized),
            max(block[1] for block in normalized),
            sum(block[2] for block in normalized),
        ),
    )
    return min((_layout_key(layout) for layout in layouts), key=lambda dims: dims)


def estimate_single_package(items: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Estimate one parcel from product dimensions and quantities.

    Each mapping needs ``length_mm``, ``width_mm``, ``height_mm`` and
    ``quantity``.  ``group_key`` is optional but should identify the product;
    quantities sharing the same product/dimensions are optimized together.

    Quantity is rounded *up* because a fractional sale quantity cannot reduce
    the physical dimensions of one unit. Weight is intentionally handled by
    Odoo, not by this helper.
    """
    grouped: dict[Hashable, dict[str, object]] = defaultdict(
        lambda: {"quantity": 0, "dimensions": (0.0, 0.0, 0.0)}
    )
    unit_count = 0

    for index, item in enumerate(items):
        qty = int(ceil(max(float(item.get("quantity", 0.0) or 0.0), 0.0)))
        if qty <= 0:
            continue

        dimensions = normalize_dimensions(
            float(item.get("length_mm", 0.0) or 0.0),
            float(item.get("width_mm", 0.0) or 0.0),
            float(item.get("height_mm", 0.0) or 0.0),
        )
        if min(dimensions) <= 0:
            raise ValueError("All item dimensions must be strictly positive")

        # Same product is grouped together. Dimensions are part of the key as
        # a defensive guard in case custom code changes a product's logistics
        # data between two order lines.
        raw_group_key = item.get("group_key")
        if raw_group_key is None:
            raw_group_key = ("dimensions", dimensions)
        try:
            hash(raw_group_key)
        except TypeError:
            raw_group_key = repr(raw_group_key)
        group_key = (raw_group_key, dimensions)

        grouped[group_key]["quantity"] = int(grouped[group_key]["quantity"]) + qty
        grouped[group_key]["dimensions"] = dimensions
        unit_count += qty

    if not unit_count:
        return {
            "unit_count": 0,
            "length_mm": 0.0,
            "width_mm": 0.0,
            "height_mm": 0.0,
            "strategy": "empty",
            "group_count": 0,
            "grid": (0, 0, 0),
            "capacity": 0,
        }

    optimized_blocks = []
    for group in grouped.values():
        dimensions = group["dimensions"]
        optimized = optimize_identical_units(
            dimensions[0],
            dimensions[1],
            dimensions[2],
            int(group["quantity"]),
        )
        optimized_blocks.append(optimized)

    if len(optimized_blocks) == 1:
        block = optimized_blocks[0]
        return {
            "unit_count": unit_count,
            "length_mm": block["length_mm"],
            "width_mm": block["width_mm"],
            "height_mm": block["height_mm"],
            "strategy": "identical_grid",
            "group_count": 1,
            "grid": block["grid"],
            "capacity": block["capacity"],
        }

    combined = _conservative_combine_blocks(
        [
            (float(block["length_mm"]), float(block["width_mm"]), float(block["height_mm"]))
            for block in optimized_blocks
        ]
    )
    return {
        "unit_count": unit_count,
        "length_mm": combined[0],
        "width_mm": combined[1],
        "height_mm": combined[2],
        "strategy": "mixed_conservative",
        "group_count": len(optimized_blocks),
        "grid": False,
        "capacity": unit_count,
    }
