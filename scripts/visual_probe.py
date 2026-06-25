#!/usr/bin/env python3
"""Rendered UI screenshot probes for frontend visual debugging."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageStat


RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def as_box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.right, self.bottom)


def parse_rect(raw: str) -> Rect:
    values = [int(part.strip()) for part in raw.split(",")]
    if len(values) != 4:
        raise ValueError("region must be x,y,width,height")
    rect = Rect(*values)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("region width and height must be positive")
    return rect


def parse_point(raw: str) -> tuple[int, int]:
    values = [int(part.strip()) for part in raw.split(",")]
    if len(values) != 2:
        raise ValueError("point must be x,y")
    return (values[0], values[1])


def parse_color(raw: str) -> RGB:
    rgb = ImageColor.getrgb(raw.strip())
    if len(rgb) == 4:
        return (rgb[0], rgb[1], rgb[2])
    return rgb


def parse_token(raw: str) -> tuple[str, RGB]:
    if "=" not in raw:
        raise ValueError("token must be name=#rrggbb")
    name, color = raw.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError("token name cannot be empty")
    return name, parse_color(color)


def parse_line(raw: str) -> tuple[int, int, int, int]:
    values = [int(part.strip()) for part in raw.split(",")]
    if len(values) != 4:
        raise ValueError("line must be x1,y1,x2,y2")
    return (values[0], values[1], values[2], values[3])


def open_image(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def crop_region(image: Image.Image, rect: Rect | None) -> Image.Image:
    if rect is None:
        return image
    if rect.x < 0 or rect.y < 0 or rect.right > image.width or rect.bottom > image.height:
        raise ValueError(f"region {rect.as_tuple()} is outside image size {(image.width, image.height)}")
    return image.crop(rect.as_box())


def rgb(pixel: Sequence[int]) -> RGB:
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]))


def rgba(pixel: Sequence[int]) -> RGBA:
    alpha = int(pixel[3]) if len(pixel) > 3 else 255
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]), alpha)


def color_hex(color: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(color[0]), int(color[1]), int(color[2]))


def color_distance(a: Sequence[int], b: Sequence[int]) -> float:
    return math.sqrt(sum((int(a[index]) - int(b[index])) ** 2 for index in range(3)))


def pixel_matches(pixel: Sequence[int], target: RGB, threshold: float) -> bool:
    return color_distance(rgb(pixel), target) <= threshold


def sample_pixels(image: Image.Image, points: Iterable[tuple[int, int]]) -> list[dict[str, object]]:
    pixels = image.load()
    samples: list[dict[str, object]] = []
    for x, y in points:
        if x < 0 or y < 0 or x >= image.width or y >= image.height:
            raise ValueError(f"point {(x, y)} is outside image size {(image.width, image.height)}")
        value = rgba(pixels[x, y])
        samples.append({"point": [x, y], "rgba": list(value), "hex": color_hex(value)})
    return samples


def nearest_token(color: RGB, tokens: dict[str, RGB]) -> dict[str, object] | None:
    if not tokens:
        return None
    name, token = min(tokens.items(), key=lambda item: color_distance(color, item[1]))
    return {"name": name, "hex": color_hex(token), "distance": round(color_distance(color, token), 3)}


def region_stats(image: Image.Image, rect: Rect | None = None, tokens: dict[str, RGB] | None = None) -> dict[str, object]:
    roi = crop_region(image, rect)
    stat = ImageStat.Stat(roi)
    colors = [rgba(pixel) for pixel in roi.getdata()]
    rgb_colors = [rgb(pixel) for pixel in colors]
    counts = Counter(rgb_colors)
    dominant_color, dominant_count = counts.most_common(1)[0]
    channels = list(zip(*rgb_colors))
    mean = [round(value, 3) for value in stat.mean[:3]]
    result: dict[str, object] = {
        "region": list(rect.as_tuple()) if rect else [0, 0, image.width, image.height],
        "size": [roi.width, roi.height],
        "pixel_count": roi.width * roi.height,
        "mean_rgb": mean,
        "median_rgb": [int(median(channel)) for channel in channels],
        "min_rgb": [min(channel) for channel in channels],
        "max_rgb": [max(channel) for channel in channels],
        "dominant": {
            "rgb": list(dominant_color),
            "hex": color_hex(dominant_color),
            "count": dominant_count,
            "percent": round(dominant_count / len(rgb_colors) * 100, 3),
        },
    }
    token_match = nearest_token(dominant_color, tokens or {})
    if token_match:
        result["nearest_token"] = token_match
    return result


def _match_mask(
    image: Image.Image,
    *,
    target: RGB | None,
    background: RGB | None,
    threshold: float,
) -> list[list[bool]]:
    pixels = image.load()
    mask: list[list[bool]] = []
    for y in range(image.height):
        row: list[bool] = []
        for x in range(image.width):
            pixel = rgb(pixels[x, y])
            if target is not None:
                row.append(pixel_matches(pixel, target, threshold))
            elif background is not None:
                row.append(not pixel_matches(pixel, background, threshold))
            else:
                raise ValueError("target or background color is required")
        mask.append(row)
    return mask


def _runs(index_matches: list[tuple[int, int, RGB]]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    current: list[tuple[int, int, RGB]] = []
    previous_index: int | None = None
    for item in index_matches:
        index, matched, dominant = item
        if matched == 0:
            continue
        if previous_index is None or index == previous_index + 1:
            current.append(item)
        else:
            runs.append(_summarize_run(current))
            current = [item]
        previous_index = index
    if current:
        runs.append(_summarize_run(current))
    return runs


def _summarize_run(items: list[tuple[int, int, RGB]]) -> dict[str, object]:
    start = items[0][0]
    end = items[-1][0]
    matched = sum(item[1] for item in items)
    dominant = Counter(item[2] for item in items).most_common(1)[0][0]
    return {
        "start": start,
        "end": end,
        "thickness": end - start + 1,
        "matched_pixels": matched,
        "dominant_hex": color_hex(dominant),
    }


def detect_line_runs(
    image: Image.Image,
    rect: Rect,
    *,
    direction: str,
    target: RGB | None = None,
    background: RGB | None = None,
    threshold: float = 3,
    min_ratio: float = 0.6,
) -> dict[str, object]:
    roi = crop_region(image, rect)
    mask = _match_mask(roi, target=target, background=background, threshold=threshold)
    pixels = roi.load()
    index_matches: list[tuple[int, int, RGB]] = []
    if direction == "horizontal":
        for y, row in enumerate(mask):
            matched = sum(row)
            ratio = matched / roi.width
            if ratio >= min_ratio:
                colors = [rgb(pixels[x, y]) for x, is_match in enumerate(row) if is_match]
                dominant = Counter(colors).most_common(1)[0][0]
                index_matches.append((rect.y + y, matched, dominant))
    elif direction == "vertical":
        for x in range(roi.width):
            column = [mask[y][x] for y in range(roi.height)]
            matched = sum(column)
            ratio = matched / roi.height
            if ratio >= min_ratio:
                colors = [rgb(pixels[x, y]) for y, is_match in enumerate(column) if is_match]
                dominant = Counter(colors).most_common(1)[0][0]
                index_matches.append((rect.x + x, matched, dominant))
    else:
        raise ValueError("direction must be horizontal or vertical")

    runs = _runs(index_matches)
    return {
        "region": list(rect.as_tuple()),
        "direction": direction,
        "threshold": threshold,
        "min_ratio": min_ratio,
        "runs": runs,
        "max_thickness": max((run["thickness"] for run in runs), default=0),
    }


def diff_images(
    expected: Image.Image,
    actual: Image.Image,
    *,
    rect: Rect | None = None,
    threshold: float = 3,
    diff_output: str | Path | None = None,
) -> dict[str, object]:
    if expected.size != actual.size:
        raise ValueError(f"image sizes differ: expected={expected.size}, actual={actual.size}")
    exp = crop_region(expected, rect)
    act = crop_region(actual, rect)
    diff = ImageChops.difference(exp, act)
    exp_pixels = exp.load()
    act_pixels = act.load()
    mismatch_points: list[tuple[int, int]] = []
    max_distance = 0.0
    total_distance = 0.0
    for y in range(exp.height):
        for x in range(exp.width):
            distance = color_distance(exp_pixels[x, y], act_pixels[x, y])
            if distance > threshold:
                mismatch_points.append((x, y))
                max_distance = max(max_distance, distance)
                total_distance += distance

    bbox = None
    if mismatch_points:
        xs = [point[0] for point in mismatch_points]
        ys = [point[1] for point in mismatch_points]
        origin_x = rect.x if rect else 0
        origin_y = rect.y if rect else 0
        bbox = [origin_x + min(xs), origin_y + min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]

    if diff_output:
        visual = Image.new("RGBA", exp.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(visual)
        for x, y in mismatch_points:
            draw.point((x, y), fill=(255, 0, 0, 255))
        if not mismatch_points:
            visual = diff
        visual.save(diff_output)

    total_pixels = exp.width * exp.height
    mismatch_count = len(mismatch_points)
    return {
        "region": list(rect.as_tuple()) if rect else [0, 0, expected.width, expected.height],
        "threshold": threshold,
        "mismatch_count": mismatch_count,
        "mismatch_percent": round(mismatch_count / total_pixels * 100, 4),
        "bbox": bbox,
        "max_distance": round(max_distance, 3),
        "mean_mismatch_distance": round(total_distance / mismatch_count, 3) if mismatch_count else 0,
        "diff_output": str(diff_output) if diff_output else None,
    }


def relative_luminance(color: RGB) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.03928:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: RGB, background: RGB) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter = max(first, second)
    darker = min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def find_components(
    image: Image.Image,
    rect: Rect,
    *,
    background: RGB,
    threshold: float = 8,
    min_pixels: int = 1,
) -> dict[str, object]:
    roi = crop_region(image, rect)
    mask = _match_mask(roi, target=None, background=background, threshold=threshold)
    seen = [[False for _ in range(roi.width)] for _ in range(roi.height)]
    components: list[dict[str, object]] = []
    for start_y in range(roi.height):
        for start_x in range(roi.width):
            if seen[start_y][start_x] or not mask[start_y][start_x]:
                continue
            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            seen[start_y][start_x] = True
            points: list[tuple[int, int]] = []
            while queue:
                x, y = queue.popleft()
                points.append((x, y))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= roi.width or ny >= roi.height:
                        continue
                    if seen[ny][nx] or not mask[ny][nx]:
                        continue
                    seen[ny][nx] = True
                    queue.append((nx, ny))
            if len(points) < min_pixels:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bbox = [rect.x + min(xs), rect.y + min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]
            components.append({"bbox": bbox, "pixel_count": len(points)})

    components.sort(key=lambda item: item["pixel_count"], reverse=True)
    return {
        "region": list(rect.as_tuple()),
        "background": color_hex(background),
        "threshold": threshold,
        "component_count": len(components),
        "components": components,
    }


def foreground_bbox(
    image: Image.Image,
    rect: Rect,
    *,
    background: RGB,
    threshold: float = 8,
) -> list[int] | None:
    roi = crop_region(image, rect)
    mask = _match_mask(roi, target=None, background=background, threshold=threshold)
    points = [(x, y) for y, row in enumerate(mask) for x, is_match in enumerate(row) if is_match]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [rect.x + min(xs), rect.y + min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]


def _bbox_center(bbox: Sequence[int]) -> tuple[float, float]:
    return (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)


def _rect_center(rect: Rect) -> tuple[float, float]:
    return (rect.x + rect.width / 2, rect.y + rect.height / 2)


def measure_foreground_geometry(
    image: Image.Image,
    rect: Rect,
    *,
    background: RGB,
    threshold: float = 8,
) -> dict[str, object]:
    bbox = foreground_bbox(image, rect, background=background, threshold=threshold)
    result: dict[str, object] = {
        "region": list(rect.as_tuple()),
        "background": color_hex(background),
        "threshold": threshold,
        "foreground_bbox": bbox,
    }
    if bbox is None:
        result.update(
            {
                "foreground_size": None,
                "insets": None,
                "center_offset": None,
                "symmetry_delta": None,
            }
        )
        return result

    insets = {
        "left": bbox[0] - rect.x,
        "top": bbox[1] - rect.y,
        "right": rect.right - (bbox[0] + bbox[2]),
        "bottom": rect.bottom - (bbox[1] + bbox[3]),
    }
    bbox_center = _bbox_center(bbox)
    rect_center = _rect_center(rect)
    result.update(
        {
            "foreground_size": {"width": bbox[2], "height": bbox[3]},
            "insets": insets,
            "center_offset": {
                "x": round(bbox_center[0] - rect_center[0], 3),
                "y": round(bbox_center[1] - rect_center[1], 3),
            },
            "symmetry_delta": {
                "horizontal": insets["left"] - insets["right"],
                "vertical": insets["top"] - insets["bottom"],
            },
        }
    )
    return result


def measure_spacing(
    image: Image.Image,
    rect: Rect,
    *,
    background: RGB,
    threshold: float = 8,
    min_pixels: int = 1,
) -> dict[str, object]:
    components_result = find_components(
        image,
        rect,
        background=background,
        threshold=threshold,
        min_pixels=min_pixels,
    )
    components = components_result["components"]
    horizontal = sorted(components, key=lambda item: (item["bbox"][0], item["bbox"][1]))
    vertical = sorted(components, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    horizontal_gaps = [
        next_item["bbox"][0] - (item["bbox"][0] + item["bbox"][2])
        for item, next_item in zip(horizontal, horizontal[1:])
    ]
    vertical_gaps = [
        next_item["bbox"][1] - (item["bbox"][1] + item["bbox"][3])
        for item, next_item in zip(vertical, vertical[1:])
    ]
    bbox = foreground_bbox(image, rect, background=background, threshold=threshold)
    insets = None
    if bbox is not None:
        insets = {
            "left": bbox[0] - rect.x,
            "top": bbox[1] - rect.y,
            "right": rect.right - (bbox[0] + bbox[2]),
            "bottom": rect.bottom - (bbox[1] + bbox[3]),
        }
    return {
        "region": list(rect.as_tuple()),
        "component_count": len(components),
        "components": components,
        "horizontal_gaps": horizontal_gaps,
        "vertical_gaps": vertical_gaps,
        "left_inset": insets["left"] if insets else None,
        "right_inset": insets["right"] if insets else None,
        "top_inset": insets["top"] if insets else None,
        "bottom_inset": insets["bottom"] if insets else None,
    }


def detect_clipping(
    image: Image.Image,
    rect: Rect,
    *,
    background: RGB,
    threshold: float = 8,
) -> dict[str, object]:
    roi = crop_region(image, rect)
    mask = _match_mask(roi, target=None, background=background, threshold=threshold)
    edges = {
        "left": sum(mask[y][0] for y in range(roi.height)),
        "right": sum(mask[y][roi.width - 1] for y in range(roi.height)),
        "top": sum(mask[0][x] for x in range(roi.width)),
        "bottom": sum(mask[roi.height - 1][x] for x in range(roi.width)),
    }
    return {
        "region": list(rect.as_tuple()),
        "edges": edges,
        "clipped": any(count > 0 for count in edges.values()),
    }


def _intersect_rect(first: Sequence[int], second: Sequence[int]) -> list[int] | None:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def detect_overlap(
    image: Image.Image,
    region_a: Rect,
    region_b: Rect,
    *,
    background: RGB,
    threshold: float = 8,
) -> dict[str, object]:
    intersection = _intersect_rect(region_a.as_tuple(), region_b.as_tuple())
    if intersection is None:
        return {
            "region_a": list(region_a.as_tuple()),
            "region_b": list(region_b.as_tuple()),
            "overlap": False,
            "intersection": None,
            "overlap_pixel_count": 0,
        }
    overlap_rect = Rect(*intersection)
    roi = crop_region(image, overlap_rect)
    mask = _match_mask(roi, target=None, background=background, threshold=threshold)
    points = [(x, y) for y, row in enumerate(mask) for x, is_match in enumerate(row) if is_match]
    if not points:
        visual_intersection = None
    else:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        visual_intersection = [
            overlap_rect.x + min(xs),
            overlap_rect.y + min(ys),
            max(xs) - min(xs) + 1,
            max(ys) - min(ys) + 1,
        ]
    return {
        "region_a": list(region_a.as_tuple()),
        "region_b": list(region_b.as_tuple()),
        "overlap": visual_intersection is not None,
        "intersection": visual_intersection,
        "overlap_pixel_count": len(points),
    }


def estimate_corner_radius(
    image: Image.Image,
    rect: Rect,
    *,
    surface: RGB,
    threshold: float = 8,
) -> dict[str, object]:
    roi = crop_region(image, rect)
    mask = _match_mask(roi, target=surface, background=None, threshold=threshold)

    def first_match_in_row(y: int, reverse: bool = False) -> int | None:
        indexes = range(roi.width - 1, -1, -1) if reverse else range(roi.width)
        for x in indexes:
            if mask[y][x]:
                return roi.width - 1 - x if reverse else x
        return None

    def first_match_in_column(x: int, reverse: bool = False) -> int | None:
        indexes = range(roi.height - 1, -1, -1) if reverse else range(roi.height)
        for y in indexes:
            if mask[y][x]:
                return roi.height - 1 - y if reverse else y
        return None

    offsets = {
        "top_left": max(first_match_in_row(0) or 0, first_match_in_column(0) or 0),
        "top_right": max(first_match_in_row(0, reverse=True) or 0, first_match_in_column(roi.width - 1) or 0),
        "bottom_left": max(first_match_in_row(roi.height - 1) or 0, first_match_in_column(0, reverse=True) or 0),
        "bottom_right": max(
            first_match_in_row(roi.height - 1, reverse=True) or 0,
            first_match_in_column(roi.width - 1, reverse=True) or 0,
        ),
    }
    return {
        "region": list(rect.as_tuple()),
        "surface": color_hex(surface),
        "corner_offsets": offsets,
        "estimated_radius": max(offsets.values()),
    }


def detect_shadow(
    image: Image.Image,
    outer_region: Rect,
    surface_region: Rect,
    *,
    background: RGB,
    threshold: float = 8,
) -> dict[str, object]:
    roi = crop_region(image, outer_region)
    mask = _match_mask(roi, target=None, background=background, threshold=threshold)
    points: list[tuple[int, int]] = []
    for y, row in enumerate(mask):
        for x, is_match in enumerate(row):
            global_x = outer_region.x + x
            global_y = outer_region.y + y
            inside_surface = (
                surface_region.x <= global_x < surface_region.right
                and surface_region.y <= global_y < surface_region.bottom
            )
            if is_match and not inside_surface:
                points.append((global_x, global_y))
    bbox = None
    if points:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        bbox = [min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]
    return {
        "outer_region": list(outer_region.as_tuple()),
        "surface_region": list(surface_region.as_tuple()),
        "shadow_pixel_count": len(points),
        "shadow_bbox": bbox,
    }


def estimate_opacity(observed: RGB, foreground: RGB, background: RGB) -> dict[str, object]:
    estimates: list[float] = []
    for index in range(3):
        denominator = foreground[index] - background[index]
        if denominator == 0:
            continue
        alpha = (observed[index] - background[index]) / denominator
        estimates.append(max(0.0, min(1.0, alpha)))
    opacity = sum(estimates) / len(estimates) if estimates else 0.0
    return {
        "observed": color_hex(observed),
        "foreground": color_hex(foreground),
        "background": color_hex(background),
        "estimated_opacity": round(opacity, 3),
    }


def _components_from_points(points: list[tuple[int, int]], *, min_pixels: int = 1) -> list[dict[str, object]]:
    point_set = set(points)
    seen: set[tuple[int, int]] = set()
    components: list[dict[str, object]] = []
    for start in sorted(point_set, key=lambda point: (point[1], point[0])):
        if start in seen:
            continue
        queue: deque[tuple[int, int]] = deque([start])
        seen.add(start)
        component: list[tuple[int, int]] = []
        while queue:
            x, y = queue.popleft()
            component.append((x, y))
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in point_set and neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        if len(component) < min_pixels:
            continue
        xs = [point[0] for point in component]
        ys = [point[1] for point in component]
        components.append({"bbox": [min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1], "pixel_count": len(component)})
    components.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return components


def diff_hotspots(
    expected: Image.Image,
    actual: Image.Image,
    *,
    rect: Rect | None = None,
    threshold: float = 3,
    min_pixels: int = 1,
) -> dict[str, object]:
    if expected.size != actual.size:
        raise ValueError(f"image sizes differ: expected={expected.size}, actual={actual.size}")
    exp = crop_region(expected, rect)
    act = crop_region(actual, rect)
    exp_pixels = exp.load()
    act_pixels = act.load()
    origin_x = rect.x if rect else 0
    origin_y = rect.y if rect else 0
    points: list[tuple[int, int]] = []
    for y in range(exp.height):
        for x in range(exp.width):
            if color_distance(exp_pixels[x, y], act_pixels[x, y]) > threshold:
                points.append((origin_x + x, origin_y + y))
    hotspots = _components_from_points(points, min_pixels=min_pixels)
    return {
        "region": list(rect.as_tuple()) if rect else [0, 0, expected.width, expected.height],
        "threshold": threshold,
        "hotspot_count": len(hotspots),
        "hotspots": hotspots,
    }


def annotate_image(
    image: Image.Image,
    output: str | Path,
    *,
    rects: Sequence[Rect] = (),
    lines: Sequence[tuple[int, int, int, int]] = (),
    points: Sequence[tuple[int, int]] = (),
) -> dict[str, object]:
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for rect in rects:
        draw.rectangle((rect.x, rect.y, rect.right - 1, rect.bottom - 1), outline=(255, 0, 0, 255), width=1)
    for line in lines:
        draw.line(line, fill=(0, 128, 255, 255), width=1)
    for x, y in points:
        draw.line((x - 3, y, x + 3, y), fill=(255, 0, 255, 255), width=1)
        draw.line((x, y - 3, x, y + 3), fill=(255, 0, 255, 255), width=1)
    annotated.save(output)
    return {
        "output": str(output),
        "rect_count": len(rects),
        "line_count": len(lines),
        "point_count": len(points),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="sample one or more exact pixels")
    sample.add_argument("--image", required=True)
    sample.add_argument("--point", action="append", required=True, type=parse_point)

    region = subparsers.add_parser("region", help="summarize a rectangular region")
    region.add_argument("--image", required=True)
    region.add_argument("--region", required=True, type=parse_rect)
    region.add_argument("--token", action="append", default=[], type=parse_token)

    line = subparsers.add_parser("line", help="detect horizontal or vertical line runs")
    line.add_argument("--image", required=True)
    line.add_argument("--region", required=True, type=parse_rect)
    line.add_argument("--direction", choices=["horizontal", "vertical"], required=True)
    line.add_argument("--target", type=parse_color)
    line.add_argument("--background", type=parse_color)
    line.add_argument("--threshold", type=float, default=3)
    line.add_argument("--min-ratio", type=float, default=0.6)

    diff = subparsers.add_parser("diff", help="compare screenshots or crops")
    diff.add_argument("--expected", required=True)
    diff.add_argument("--actual", required=True)
    diff.add_argument("--region", type=parse_rect)
    diff.add_argument("--threshold", type=float, default=3)
    diff.add_argument("--diff-output")

    components = subparsers.add_parser("components", help="find non-background connected components")
    components.add_argument("--image", required=True)
    components.add_argument("--region", required=True, type=parse_rect)
    components.add_argument("--background", required=True, type=parse_color)
    components.add_argument("--threshold", type=float, default=8)
    components.add_argument("--min-pixels", type=int, default=1)

    contrast = subparsers.add_parser("contrast", help="calculate WCAG contrast ratio from two colors")
    contrast.add_argument("--foreground", required=True, type=parse_color)
    contrast.add_argument("--background", required=True, type=parse_color)

    measure = subparsers.add_parser("measure", help="measure foreground bbox, insets, centering, and symmetry")
    measure.add_argument("--image", required=True)
    measure.add_argument("--region", required=True, type=parse_rect)
    measure.add_argument("--background", required=True, type=parse_color)
    measure.add_argument("--threshold", type=float, default=8)

    spacing = subparsers.add_parser("spacing", help="measure component gaps and rendered insets")
    spacing.add_argument("--image", required=True)
    spacing.add_argument("--region", required=True, type=parse_rect)
    spacing.add_argument("--background", required=True, type=parse_color)
    spacing.add_argument("--threshold", type=float, default=8)
    spacing.add_argument("--min-pixels", type=int, default=1)

    clipping = subparsers.add_parser("clipping", help="detect foreground pixels touching crop edges")
    clipping.add_argument("--image", required=True)
    clipping.add_argument("--region", required=True, type=parse_rect)
    clipping.add_argument("--background", required=True, type=parse_color)
    clipping.add_argument("--threshold", type=float, default=8)

    overlap = subparsers.add_parser("overlap", help="detect visible non-background pixels inside two regions' intersection")
    overlap.add_argument("--image", required=True)
    overlap.add_argument("--region-a", required=True, type=parse_rect)
    overlap.add_argument("--region-b", required=True, type=parse_rect)
    overlap.add_argument("--background", required=True, type=parse_color)
    overlap.add_argument("--threshold", type=float, default=8)

    radius = subparsers.add_parser("radius", help="estimate corner radius from surface corner offsets")
    radius.add_argument("--image", required=True)
    radius.add_argument("--region", required=True, type=parse_rect)
    radius.add_argument("--surface", required=True, type=parse_color)
    radius.add_argument("--threshold", type=float, default=8)

    shadow = subparsers.add_parser("shadow", help="detect non-background shadow pixels outside a surface")
    shadow.add_argument("--image", required=True)
    shadow.add_argument("--outer-region", required=True, type=parse_rect)
    shadow.add_argument("--surface-region", required=True, type=parse_rect)
    shadow.add_argument("--background", required=True, type=parse_color)
    shadow.add_argument("--threshold", type=float, default=8)

    opacity = subparsers.add_parser("opacity", help="estimate alpha from observed blended color")
    opacity.add_argument("--observed", required=True, type=parse_color)
    opacity.add_argument("--foreground", required=True, type=parse_color)
    opacity.add_argument("--background", required=True, type=parse_color)

    hotspots = subparsers.add_parser("hotspots", help="cluster screenshot diff pixels into visual hotspots")
    hotspots.add_argument("--expected", required=True)
    hotspots.add_argument("--actual", required=True)
    hotspots.add_argument("--region", type=parse_rect)
    hotspots.add_argument("--threshold", type=float, default=3)
    hotspots.add_argument("--min-pixels", type=int, default=1)

    annotate = subparsers.add_parser("annotate", help="write an annotated screenshot with rects, lines, and points")
    annotate.add_argument("--image", required=True)
    annotate.add_argument("--output", required=True)
    annotate.add_argument("--rect", action="append", default=[], type=parse_rect)
    annotate.add_argument("--line", action="append", default=[], type=parse_line)
    annotate.add_argument("--point", action="append", default=[], type=parse_point)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sample":
        result = {"samples": sample_pixels(open_image(args.image), args.point)}
    elif args.command == "region":
        result = region_stats(open_image(args.image), args.region, dict(args.token))
    elif args.command == "line":
        if args.target is None and args.background is None:
            raise SystemExit("line requires --target or --background")
        result = detect_line_runs(
            open_image(args.image),
            args.region,
            direction=args.direction,
            target=args.target,
            background=args.background,
            threshold=args.threshold,
            min_ratio=args.min_ratio,
        )
    elif args.command == "diff":
        result = diff_images(
            open_image(args.expected),
            open_image(args.actual),
            rect=args.region,
            threshold=args.threshold,
            diff_output=args.diff_output,
        )
    elif args.command == "components":
        result = find_components(
            open_image(args.image),
            args.region,
            background=args.background,
            threshold=args.threshold,
            min_pixels=args.min_pixels,
        )
    elif args.command == "contrast":
        ratio = contrast_ratio(args.foreground, args.background)
        result = {
            "foreground": color_hex(args.foreground),
            "background": color_hex(args.background),
            "contrast_ratio": round(ratio, 3),
            "wcag_aa_normal_text": ratio >= 4.5,
            "wcag_aa_large_text": ratio >= 3,
        }
    elif args.command == "measure":
        result = measure_foreground_geometry(
            open_image(args.image),
            args.region,
            background=args.background,
            threshold=args.threshold,
        )
    elif args.command == "spacing":
        result = measure_spacing(
            open_image(args.image),
            args.region,
            background=args.background,
            threshold=args.threshold,
            min_pixels=args.min_pixels,
        )
    elif args.command == "clipping":
        result = detect_clipping(
            open_image(args.image),
            args.region,
            background=args.background,
            threshold=args.threshold,
        )
    elif args.command == "overlap":
        result = detect_overlap(
            open_image(args.image),
            args.region_a,
            args.region_b,
            background=args.background,
            threshold=args.threshold,
        )
    elif args.command == "radius":
        result = estimate_corner_radius(
            open_image(args.image),
            args.region,
            surface=args.surface,
            threshold=args.threshold,
        )
    elif args.command == "shadow":
        result = detect_shadow(
            open_image(args.image),
            args.outer_region,
            args.surface_region,
            background=args.background,
            threshold=args.threshold,
        )
    elif args.command == "opacity":
        result = estimate_opacity(args.observed, args.foreground, args.background)
    elif args.command == "hotspots":
        result = diff_hotspots(
            open_image(args.expected),
            open_image(args.actual),
            rect=args.region,
            threshold=args.threshold,
            min_pixels=args.min_pixels,
        )
    elif args.command == "annotate":
        result = annotate_image(
            open_image(args.image),
            args.output,
            rects=args.rect,
            lines=args.line,
            points=args.point,
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
