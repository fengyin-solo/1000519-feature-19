"""地图几何工具：判断调查点是否落在只读访问面（多边形）内。

访问面在工作台里用一组按顺序排列的顶点表示，坐标系与灾害点图一致（0-1000 的
示意平面）。这里只依赖标准库实现射线法，避免为一个判定引入 GIS 重依赖。
"""
from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]
Polygon = Sequence[Sequence[float]]


def as_point(coords: object) -> Point | None:
    """把库存里的坐标归一化成 (x, y)；缺坐标或无法解析时返回 None。"""
    try:
        return float(coords[0]), float(coords[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def point_in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    """射线法（even-odd）判定点是否在多边形内；落在边界上按在内处理。

    polygon 至少要能围成一个三角形；顶点允许首尾不重合（代码自动闭合）。
    """
    if polygon is None or len(polygon) < 3:
        return False

    inside = False
    count = len(polygon)
    for i in range(count):
        ax, ay = float(polygon[i][0]), float(polygon[i][1])
        bx, by = float(polygon[(i + 1) % count][0]), float(polygon[(i + 1) % count][1])

        # 点落在某条边上，直接算在面内，避免边界调查点被误判成越权。
        cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if cross == 0 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True

        if (ay > y) != (by > y):
            intersect_x = ax + (bx - ax) * (y - ay) / (by - ay)
            if x < intersect_x:
                inside = not inside
    return inside


def polygon_area(polygon: Polygon) -> float:
    """鞋带公式求面积，登记访问面时用来挡住退化（围不成区域）的多边形。"""
    if polygon is None or len(polygon) < 3:
        return 0.0
    total = 0.0
    count = len(polygon)
    for i in range(count):
        ax, ay = float(polygon[i][0]), float(polygon[i][1])
        bx, by = float(polygon[(i + 1) % count][0]), float(polygon[(i + 1) % count][1])
        total += ax * by - bx * ay
    return abs(total) / 2.0
