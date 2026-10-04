"""Public event geometry and availability only; no guests or operational orders."""
from math import ceil
from apps.core.public_site import has_public_layout


def table_groups(configurations, available_ids):
    groups = {}
    for config in configurations:
        table = config.table
        key = f'{table.area_id}-{table.level or "general"}'
        group = groups.setdefault(key, {'key': key, 'name': ' · '.join(filter(None, [
            table.area.name, table.get_level_display() if table.level else ''])), 'tables': []})
        group['tables'].append({'config': config, 'available': config.pk in available_ids,
            'x': float(table.layout_x), 'y': float(table.layout_y),
            'width': float(table.layout_width), 'height': float(table.layout_height),
            'shape': table.layout_shape.lower()})
    for group in groups.values():
        group['diagram'] = has_public_layout(group['tables'])
        group['minimum_width'] = ceil(max(max(11000 / row['width'], 10000 / row['height']) for row in group['tables'])) if group['diagram'] else 0
    return list(groups.values())
