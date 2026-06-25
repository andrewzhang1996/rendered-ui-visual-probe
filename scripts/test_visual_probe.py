#!/usr/bin/env python3
"""Tests for visual_probe.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import visual_probe


SCRIPT = Path(__file__).with_name("visual_probe.py")


class VisualProbeTest(unittest.TestCase):
    def make_image(self, size=(20, 20), color=(255, 255, 255, 255)) -> Image.Image:
        return Image.new("RGBA", size, color)

    def test_sample_pixels_reports_exact_rgba_and_hex(self) -> None:
        image = self.make_image()
        image.putpixel((3, 4), (16, 32, 48, 255))

        result = visual_probe.sample_pixels(image, [(3, 4)])

        self.assertEqual(result[0]["point"], [3, 4])
        self.assertEqual(result[0]["rgba"], [16, 32, 48, 255])
        self.assertEqual(result[0]["hex"], "#102030")

    def test_region_stats_reports_dominant_color_and_nearest_token(self) -> None:
        image = self.make_image(size=(10, 10), color=(250, 250, 250, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 7, 7), fill=(24, 144, 255, 255))

        result = visual_probe.region_stats(
            image,
            visual_probe.Rect(2, 2, 6, 6),
            {"brand-blue": (24, 144, 255), "neutral": (250, 250, 250)},
        )

        self.assertEqual(result["dominant"]["hex"], "#1890ff")
        self.assertEqual(result["dominant"]["percent"], 100.0)
        self.assertEqual(result["nearest_token"]["name"], "brand-blue")
        self.assertEqual(result["nearest_token"]["distance"], 0.0)

    def test_detect_horizontal_line_thickness_by_target_color(self) -> None:
        image = self.make_image(size=(30, 12), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 5, 29, 6), fill=(22, 119, 255, 255))

        result = visual_probe.detect_line_runs(
            image,
            visual_probe.Rect(0, 3, 30, 6),
            direction="horizontal",
            target=(22, 119, 255),
            threshold=0,
            min_ratio=1.0,
        )

        self.assertEqual(result["max_thickness"], 2)
        self.assertEqual(result["runs"][0]["start"], 5)
        self.assertEqual(result["runs"][0]["end"], 6)
        self.assertEqual(result["runs"][0]["dominant_hex"], "#1677ff")

    def test_detect_vertical_line_thickness_by_background_difference(self) -> None:
        image = self.make_image(size=(12, 30), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 0, 6, 29), fill=(0, 0, 0, 255))

        result = visual_probe.detect_line_runs(
            image,
            visual_probe.Rect(2, 0, 8, 30),
            direction="vertical",
            background=(255, 255, 255),
            threshold=0,
            min_ratio=1.0,
        )

        self.assertEqual(result["max_thickness"], 3)
        self.assertEqual(result["runs"][0]["start"], 4)
        self.assertEqual(result["runs"][0]["end"], 6)

    def test_diff_images_reports_bbox_and_writes_diff_mask(self) -> None:
        expected = self.make_image(size=(10, 10), color=(255, 255, 255, 255))
        actual = self.make_image(size=(10, 10), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(actual)
        draw.rectangle((3, 4, 5, 6), fill=(0, 0, 0, 255))

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "diff.png"
            result = visual_probe.diff_images(expected, actual, threshold=1, diff_output=output)

            self.assertEqual(result["mismatch_count"], 9)
            self.assertEqual(result["bbox"], [3, 4, 3, 3])
            self.assertTrue(output.exists())

    def test_contrast_ratio_uses_wcag_luminance_formula(self) -> None:
        ratio = visual_probe.contrast_ratio((0, 0, 0), (255, 255, 255))

        self.assertAlmostEqual(ratio, 21.0, places=3)

    def test_find_components_reports_non_background_icon_like_regions(self) -> None:
        image = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 5, 7, 8), fill=(30, 30, 30, 255))
        draw.rectangle((14, 15, 15, 16), fill=(30, 30, 30, 255))

        result = visual_probe.find_components(
            image,
            visual_probe.Rect(0, 0, 20, 20),
            background=(255, 255, 255),
            threshold=0,
            min_pixels=2,
        )

        self.assertEqual(result["component_count"], 2)
        self.assertEqual(result["components"][0]["bbox"], [4, 5, 4, 4])
        self.assertEqual(result["components"][0]["pixel_count"], 16)

    def test_measure_foreground_geometry_reports_insets_and_centering(self) -> None:
        image = self.make_image(size=(30, 20), color=(255, 255, 255, 255))
        ImageDraw.Draw(image).rectangle((8, 5, 21, 14), fill=(0, 0, 0, 255))

        result = visual_probe.measure_foreground_geometry(
            image,
            visual_probe.Rect(0, 0, 30, 20),
            background=(255, 255, 255),
            threshold=0,
        )

        self.assertEqual(result["foreground_bbox"], [8, 5, 14, 10])
        self.assertEqual(result["insets"], {"left": 8, "top": 5, "right": 8, "bottom": 5})
        self.assertEqual(result["center_offset"], {"x": 0.0, "y": 0.0})
        self.assertEqual(result["symmetry_delta"], {"horizontal": 0, "vertical": 0})

    def test_measure_spacing_reports_component_gaps(self) -> None:
        image = self.make_image(size=(40, 12), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 3, 9, 8), fill=(0, 0, 0, 255))
        draw.rectangle((16, 3, 21, 8), fill=(0, 0, 0, 255))
        draw.rectangle((30, 3, 35, 8), fill=(0, 0, 0, 255))

        result = visual_probe.measure_spacing(
            image,
            visual_probe.Rect(0, 0, 40, 12),
            background=(255, 255, 255),
            threshold=0,
            min_pixels=2,
        )

        self.assertEqual(result["horizontal_gaps"], [6, 8])
        self.assertEqual(result["left_inset"], 4)
        self.assertEqual(result["right_inset"], 4)

    def test_detect_clipping_reports_foreground_touching_edges(self) -> None:
        image = self.make_image(size=(12, 12), color=(255, 255, 255, 255))
        ImageDraw.Draw(image).rectangle((0, 3, 4, 8), fill=(0, 0, 0, 255))

        result = visual_probe.detect_clipping(
            image,
            visual_probe.Rect(0, 0, 12, 12),
            background=(255, 255, 255),
            threshold=0,
        )

        self.assertTrue(result["clipped"])
        self.assertEqual(result["edges"]["left"], 6)
        self.assertEqual(result["edges"]["right"], 0)

    def test_detect_overlap_reports_intersection_between_visual_regions(self) -> None:
        image = self.make_image(size=(30, 20), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((4, 4, 13, 13), fill=(0, 0, 0, 255))
        draw.rectangle((10, 8, 20, 16), fill=(0, 0, 0, 255))

        result = visual_probe.detect_overlap(
            image,
            visual_probe.Rect(0, 0, 15, 18),
            visual_probe.Rect(8, 6, 15, 12),
            background=(255, 255, 255),
            threshold=0,
        )

        self.assertTrue(result["overlap"])
        self.assertEqual(result["intersection"], [8, 6, 7, 11])
        self.assertGreater(result["overlap_pixel_count"], 0)

    def test_estimate_corner_radius_reports_square_and_rounded_offsets(self) -> None:
        square = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        ImageDraw.Draw(square).rectangle((2, 2, 17, 17), fill=(0, 0, 0, 255))
        rounded = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        ImageDraw.Draw(rounded).rounded_rectangle((2, 2, 17, 17), radius=5, fill=(0, 0, 0, 255))

        square_result = visual_probe.estimate_corner_radius(
            square,
            visual_probe.Rect(2, 2, 16, 16),
            surface=(0, 0, 0),
            threshold=0,
        )
        rounded_result = visual_probe.estimate_corner_radius(
            rounded,
            visual_probe.Rect(2, 2, 16, 16),
            surface=(0, 0, 0),
            threshold=0,
        )

        self.assertEqual(square_result["estimated_radius"], 0)
        self.assertGreaterEqual(rounded_result["estimated_radius"], 3)

    def test_detect_shadow_reports_non_background_pixels_outside_surface(self) -> None:
        image = self.make_image(size=(30, 30), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 19, 19), fill=(245, 245, 245, 255))
        draw.rectangle((6, 6, 17, 17), fill=(0, 0, 0, 255))

        result = visual_probe.detect_shadow(
            image,
            visual_probe.Rect(4, 4, 20, 20),
            visual_probe.Rect(6, 6, 12, 12),
            background=(255, 255, 255),
            threshold=3,
        )

        self.assertGreater(result["shadow_pixel_count"], 0)
        self.assertEqual(result["shadow_bbox"], [8, 8, 12, 12])

    def test_estimate_opacity_reports_alpha_from_blended_color(self) -> None:
        result = visual_probe.estimate_opacity((128, 128, 128), (0, 0, 0), (255, 255, 255))

        self.assertAlmostEqual(result["estimated_opacity"], 0.498, places=3)

    def test_diff_hotspots_groups_changed_regions(self) -> None:
        expected = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        actual = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        draw = ImageDraw.Draw(actual)
        draw.rectangle((2, 2, 4, 4), fill=(0, 0, 0, 255))
        draw.rectangle((14, 14, 16, 16), fill=(0, 0, 0, 255))

        result = visual_probe.diff_hotspots(expected, actual, threshold=1, min_pixels=1)

        self.assertEqual(result["hotspot_count"], 2)
        self.assertEqual(result["hotspots"][0]["bbox"], [2, 2, 3, 3])

    def test_annotate_image_writes_measurement_overlay(self) -> None:
        image = self.make_image(size=(20, 20), color=(255, 255, 255, 255))
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.png"
            output_path = Path(tmpdir) / "annotated.png"
            image.save(image_path)

            result = visual_probe.annotate_image(
                image,
                output_path,
                rects=[visual_probe.Rect(2, 2, 10, 10)],
                lines=[(0, 0, 19, 19)],
                points=[(5, 5)],
            )

            self.assertEqual(result["output"], str(output_path))
            self.assertTrue(output_path.exists())

    def test_cli_sample_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "sample.png"
            image = self.make_image(size=(4, 4), color=(1, 2, 3, 255))
            image.save(image_path)

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "sample", "--image", str(image_path), "--point", "1,1"],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["samples"][0]["hex"], "#010203")

    def test_cli_region_outputs_token_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "region.png"
            image = self.make_image(size=(4, 4), color=(24, 144, 255, 255))
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "region",
                    "--image",
                    str(image_path),
                    "--region",
                    "0,0,4,4",
                    "--token",
                    "brand=#1890ff",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["nearest_token"]["name"], "brand")

    def test_cli_line_outputs_detected_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "line.png"
            image = self.make_image(size=(8, 8), color=(255, 255, 255, 255))
            ImageDraw.Draw(image).line((0, 4, 7, 4), fill=(0, 0, 0, 255), width=1)
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "line",
                    "--image",
                    str(image_path),
                    "--region",
                    "0,3,8,3",
                    "--direction",
                    "horizontal",
                    "--target",
                    "#000000",
                    "--threshold",
                    "0",
                    "--min-ratio",
                    "1",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["max_thickness"], 1)

    def test_cli_diff_outputs_mismatch_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected_path = Path(tmpdir) / "expected.png"
            actual_path = Path(tmpdir) / "actual.png"
            expected = self.make_image(size=(5, 5), color=(255, 255, 255, 255))
            actual = self.make_image(size=(5, 5), color=(255, 255, 255, 255))
            actual.putpixel((2, 2), (0, 0, 0, 255))
            expected.save(expected_path)
            actual.save(actual_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "diff",
                    "--expected",
                    str(expected_path),
                    "--actual",
                    str(actual_path),
                    "--threshold",
                    "1",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["mismatch_count"], 1)

    def test_cli_components_outputs_component_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "components.png"
            image = self.make_image(size=(8, 8), color=(255, 255, 255, 255))
            ImageDraw.Draw(image).rectangle((2, 2, 3, 3), fill=(0, 0, 0, 255))
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "components",
                    "--image",
                    str(image_path),
                    "--region",
                    "0,0,8,8",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                    "--min-pixels",
                    "1",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["component_count"], 1)

    def test_cli_contrast_outputs_wcag_flags(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "contrast",
                "--foreground",
                "#000000",
                "--background",
                "#ffffff",
            ],
            check=True,
            text=True,
            capture_output=True,
        )

        parsed = json.loads(completed.stdout)
        self.assertEqual(parsed["contrast_ratio"], 21.0)
        self.assertTrue(parsed["wcag_aa_normal_text"])

    def test_cli_measure_outputs_foreground_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "measure.png"
            image = self.make_image(size=(12, 12), color=(255, 255, 255, 255))
            ImageDraw.Draw(image).rectangle((3, 4, 8, 7), fill=(0, 0, 0, 255))
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "measure",
                    "--image",
                    str(image_path),
                    "--region",
                    "0,0,12,12",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["foreground_bbox"], [3, 4, 6, 4])

    def test_cli_spacing_outputs_horizontal_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "spacing.png"
            image = self.make_image(size=(20, 8), color=(255, 255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((2, 2, 5, 5), fill=(0, 0, 0, 255))
            draw.rectangle((10, 2, 13, 5), fill=(0, 0, 0, 255))
            image.save(image_path)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "spacing",
                    "--image",
                    str(image_path),
                    "--region",
                    "0,0,20,8",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            parsed = json.loads(completed.stdout)
            self.assertEqual(parsed["horizontal_gaps"], [4])

    def test_cli_clipping_overlap_radius_shadow_opacity_hotspots_annotate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base.png"
            actual_path = Path(tmpdir) / "actual.png"
            annotated_path = Path(tmpdir) / "annotated.png"
            image = self.make_image(size=(24, 24), color=(255, 255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((4, 4, 13, 13), radius=3, fill=(0, 0, 0, 255))
            draw.rectangle((12, 10, 20, 18), fill=(0, 0, 0, 255))
            image.save(base_path)
            actual = image.copy()
            ImageDraw.Draw(actual).rectangle((18, 2, 20, 4), fill=(0, 0, 0, 255))
            actual.save(actual_path)

            commands = [
                [
                    "clipping",
                    "--image",
                    str(base_path),
                    "--region",
                    "0,0,8,8",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                ],
                [
                    "overlap",
                    "--image",
                    str(base_path),
                    "--region-a",
                    "0,0,16,16",
                    "--region-b",
                    "10,8,12,12",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                ],
                [
                    "radius",
                    "--image",
                    str(base_path),
                    "--region",
                    "4,4,10,10",
                    "--surface",
                    "#000000",
                    "--threshold",
                    "0",
                ],
                [
                    "shadow",
                    "--image",
                    str(base_path),
                    "--outer-region",
                    "0,0,24,24",
                    "--surface-region",
                    "4,4,10,10",
                    "--background",
                    "#ffffff",
                    "--threshold",
                    "0",
                ],
                [
                    "opacity",
                    "--observed",
                    "#808080",
                    "--foreground",
                    "#000000",
                    "--background",
                    "#ffffff",
                ],
                [
                    "hotspots",
                    "--expected",
                    str(base_path),
                    "--actual",
                    str(actual_path),
                    "--threshold",
                    "1",
                ],
                [
                    "annotate",
                    "--image",
                    str(base_path),
                    "--output",
                    str(annotated_path),
                    "--rect",
                    "1,1,10,10",
                    "--line",
                    "0,0,23,23",
                    "--point",
                    "5,5",
                ],
            ]

            outputs = []
            for command in commands:
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT), *command],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                outputs.append(json.loads(completed.stdout))

            self.assertIn("clipped", outputs[0])
            self.assertIn("overlap", outputs[1])
            self.assertIn("estimated_radius", outputs[2])
            self.assertIn("shadow_pixel_count", outputs[3])
            self.assertIn("estimated_opacity", outputs[4])
            self.assertIn("hotspots", outputs[5])
            self.assertTrue(annotated_path.exists())


if __name__ == "__main__":
    unittest.main()
