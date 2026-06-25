# Frontend Visual Heuristics

## Region Selection

- Prefer small regions of interest over whole-page screenshots.
- Anchor regions to DOM bounding boxes when browser tooling can provide them.
- Add a few pixels of context around edges so line detection can distinguish a real border from neighboring content.
- For DPR > 1 screenshots, convert CSS-pixel coordinates to image pixels before probing.

## Tolerance Rules

- Exact color checks are appropriate for solid backgrounds, generated PNG fixtures, and unblended token surfaces.
- Use distance thresholds for anti-aliased text, SVG icons, translucent overlays, shadows, and browser focus rings.
- A Euclidean RGB distance of 0 is exact; 1-3 is usually visually identical; 4-12 is a small rendering/token drift; larger values need context.
- Use line run ratios instead of requiring every pixel in a row or column to match, because rounded corners and antialiasing can break continuity at the ends.

## Diagnostic Recipes

### Border Or Focus Ring

1. Crop a narrow horizontal or vertical band around the expected line.
2. Run `line` with the expected color if known.
3. If the color is unknown, run `region` first to identify dominant colors, then rerun `line`.
4. Report line start, end, thickness, match ratio, and color.

### Icon Presence

1. Crop the expected icon slot.
2. Run `components` with the known background color.
3. Confirm at least one component has plausible icon dimensions and is not clipped by the crop edge.
4. If hover controls are involved, compare non-hover and hover screenshots with `diff`.

### Spacing, Padding, And Alignment

1. Crop the container or control with a few pixels of margin.
2. Run `measure` to get the foreground bbox, insets, center offset, and symmetry delta.
3. Run `spacing` when multiple visible objects exist in the same crop, such as text plus icons or adjacent toolbar buttons.
4. Compare measured values against design tokens with a tolerance that accounts for DPR and anti-aliasing.

### Clipping And Overflow

1. Crop the object tightly using its DOM rect, plus a small outside margin when available.
2. Run `clipping` to detect foreground pixels touching crop edges.
3. A positive clipping result is not automatically a bug; check whether the object is intentionally flush to that edge.
4. For focus rings and shadows, include enough outside margin or clipping may be a false positive.

### Overlap And Occlusion

1. Get two DOM rects from browser tooling.
2. Run `overlap` with those two regions and the page background color.
3. Treat the result as evidence of visible pixels in the regions' intersection, not semantic proof of which component owns those pixels.
4. If same-color objects merge, use DOM data, state-specific screenshots, or color-separated crops to clarify ownership.

### Radius, Shadow, And Opacity

1. Run `radius` on a surface crop to distinguish square corners from visibly rounded corners.
2. Run `shadow` with an outer crop and the surface rect to locate non-background pixels outside the surface.
3. Run `opacity` when a disabled, overlay, or muted state appears to be a blended foreground over a known background.
4. Treat these as rendered estimates; CSS box-shadow, blur, and anti-aliasing do not always map to exact style declarations.

### Color Or Token Drift

1. Run `region` on an interior area that excludes borders, text, and shadows.
2. Pass candidate token values with `--token token-name=#hex`.
3. Report dominant color, nearest token, and color distance.

### Before/After Regression

1. Capture screenshots with the same viewport, zoom, DPR, locale, theme, and scroll position.
2. Mask or crop dynamic areas.
3. Run `diff` with a threshold that ignores anti-aliasing noise.
4. Run `hotspots` when a raw diff count is too broad; inspect changed clusters before concluding that a visible change is intended or accidental.

### Text Clipping Or Overlap

1. Get the text container rect from browser tooling.
2. Crop the container plus a small outside margin.
3. Use `components` to locate non-background pixels outside the expected content box.
4. Confirm with DOM rects, because screenshot-only text detection is heuristic.

## Evidence Quality

High-quality visual evidence includes:

- screenshot path and capture conditions
- ROI coordinates and dimensions
- measured colors or component boxes
- tolerance thresholds
- expected value or token source
- annotated image or diff mask when a text description is ambiguous

Avoid claiming pixel-perfect correctness from one machine when the issue is font rendering, browser zoom, OS text smoothing, or animated state timing.
