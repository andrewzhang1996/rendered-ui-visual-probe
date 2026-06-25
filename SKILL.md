---
name: rendered-ui-visual-probe
description: Rendered UI screenshot diagnostics using Python Pillow. Use when Codex needs measurable frontend visual evidence for screenshots or Storybook/browser captures, including colors and tokens, borders and focus rings, spacing and padding, alignment and centering, icon/object visibility, clipping and overlap, corner radius, shadows, opacity, contrast, before/after visual diffs, hotspot localization, and annotated evidence.
---

# Rendered UI Visual Probe

## Purpose

Use this skill when DOM/CSS inspection is not enough to prove what actually rendered. Capture or receive screenshots, then use Pillow-based probes to produce measurable evidence: colors, line thickness, rendered spacing, object bounds, visual centering, clipping, overlap, radius, shadows, opacity, diff hotspots, contrast ratios, and annotated crops.

## Workflow

1. Capture stable screenshots.
   - Prefer Playwright or Chrome DevTools screenshots at a known viewport, device scale factor, locale, theme, and browser zoom.
   - For visual states, capture paired images such as before/after, default/hover, collapsed/expanded, focused/unfocused, or desktop/mobile.
   - Keep dynamic content, animations, caret blinking, timestamps, and loading indicators out of the region of interest when possible.
2. Define the region of interest.
   - Use DOM bounding boxes from browser tooling when available.
   - Crop tightly around the suspected issue, then leave 2-6 px of context for border, focus-line, clipping, and shadow checks.
   - Convert CSS-pixel coordinates to image-pixel coordinates when the screenshot uses DPR > 1.
3. Run `scripts/visual_probe.py`.
   - Use `sample`, `region`, `contrast`, and token matching for color evidence.
   - Use `line`, `radius`, `shadow`, and `opacity` for surface styling evidence.
   - Use `measure`, `spacing`, `components`, `clipping`, and `overlap` for rendered geometry.
   - Use `diff` and `hotspots` for before/after or state-change evidence.
   - Use `annotate` to create marked screenshots for docs, Jira, PRs, or debugging notes.
4. Interpret with tolerance.
   - Do not treat every RGB delta as a bug. Anti-aliasing, font smoothing, subpixel layout, transparency, and screenshots at DPR > 1 can create legitimate variation.
   - Report measured values plus the tolerance used.
   - Prefer local ROI checks over whole-page assertions; browser rendering differs across OS, fonts, DPR, and anti-aliasing.
5. Save evidence when useful.
   - Store cropped images, diff masks, hotspot results, or annotated screenshots near the task artifact when the user asked for a research/debug document.
   - In final explanations, cite coordinates, region size, measured color, thickness, spacing, object bbox, mismatch count, and the exact screenshot file.

## Script Usage

Run from the skill directory or pass absolute paths:

```bash
python3 scripts/visual_probe.py sample --image screenshot.png --point 120,44
python3 scripts/visual_probe.py region --image screenshot.png --region 100,40,220,32 --token header=#f7f8fa
python3 scripts/visual_probe.py line --image screenshot.png --region 90,70,300,8 --direction horizontal --target #1677ff
python3 scripts/visual_probe.py measure --image screenshot.png --region 300,32,80,24 --background #ffffff
python3 scripts/visual_probe.py spacing --image screenshot.png --region 300,32,120,24 --background #ffffff
python3 scripts/visual_probe.py components --image screenshot.png --region 300,32,80,24 --background #ffffff
python3 scripts/visual_probe.py clipping --image screenshot.png --region 300,32,80,24 --background #ffffff
python3 scripts/visual_probe.py overlap --image screenshot.png --region-a 100,40,80,24 --region-b 160,40,80,24 --background #ffffff
python3 scripts/visual_probe.py radius --image screenshot.png --region 20,20,120,40 --surface #ffffff
python3 scripts/visual_probe.py shadow --image screenshot.png --outer-region 12,12,160,80 --surface-region 20,20,120,40 --background #ffffff
python3 scripts/visual_probe.py opacity --observed #808080 --foreground #000000 --background #ffffff
python3 scripts/visual_probe.py contrast --foreground #1f2937 --background #ffffff
python3 scripts/visual_probe.py diff --expected before.png --actual after.png --region 80,30,400,80 --diff-output /tmp/header-diff.png
python3 scripts/visual_probe.py hotspots --expected before.png --actual after.png --region 80,30,400,80
python3 scripts/visual_probe.py annotate --image screenshot.png --output /tmp/evidence.png --rect 100,40,220,32 --line 100,72,320,72 --point 120,44
```

The script outputs JSON so results can be copied into debugging notes, tests, or review comments.

## Frontend Debugging Patterns

- **Border/focus-line bugs**: use `line` on a thin ROI around the suspected edge. Confirm row/column start, run length, thickness, and RGB.
- **Spacing/padding bugs**: use `measure` for foreground insets and `spacing` for gaps between detected components.
- **Alignment/centering bugs**: use `measure` and compare `center_offset` and `symmetry_delta` against the design contract.
- **Icon visibility**: use `components` inside the expected icon slot. A present icon should produce a non-background component with a plausible bounding box.
- **Clipping/overflow bugs**: use `clipping` on a crop around the expected object or focus ring; any foreground pixels touching crop edges are evidence to inspect.
- **Overlap bugs**: use `overlap` for two known regions, then verify with DOM rects because same-color merged objects cannot always be separated from pixels alone.
- **Radius/shadow/opacity bugs**: use `radius`, `shadow`, and `opacity` for rendered surface evidence; treat estimates as approximate for anti-aliased or translucent pixels.
- **Hover/active/state bugs**: use paired screenshots with `diff` and `hotspots`, then use `region`, `measure`, or `components` on the changed clusters.
- **Token drift**: use `region --token name=#hex` values from the design token source. Report nearest token and color distance.
- **Text clipping/overlap**: combine DOM rects with `components`, `clipping`, and `overlap`. Screenshot-only text detection is heuristic.
- **Contrast checks**: use `contrast` for a rendered approximation, but verify CSS/token contrast separately if anti-aliased pixels are involved.

## Reference

Read `references/frontend-visual-heuristics.md` when the task involves choosing a diagnostic strategy, explaining evidence quality, or avoiding false positives in screenshot analysis.
