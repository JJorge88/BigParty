"""Layout suggestions; only configuration changes, never occupancy changes."""
from decimal import Decimal
from math import ceil, sqrt


def overlaps(tables):
    rows = list(tables)
    return [(a, b) for i, a in enumerate(rows) for b in rows[i + 1:]
            if a.layout_x < b.layout_x + b.layout_width and a.layout_x + a.layout_width > b.layout_x
            and a.layout_y < b.layout_y + b.layout_height and a.layout_y + a.layout_height > b.layout_y]


def suggestion(tables):
    rows = list(tables)
    columns = max(1, ceil(sqrt(len(rows))))
    height = Decimal(90) / max(1, ceil(len(rows) / columns))
    width = Decimal(90) / columns
    return [(row, {'layout_x': (Decimal(5) + (i % columns) * width).quantize(Decimal('.01')),
                   'layout_y': (Decimal(5) + (i // columns) * height).quantize(Decimal('.01')),
                   'layout_width': (width * Decimal('.8')).quantize(Decimal('.01')),
                   'layout_height': (height * Decimal('.7')).quantize(Decimal('.01'))}) for i, row in enumerate(rows)]
