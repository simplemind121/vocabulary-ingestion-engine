"""Cutting a page's pictures out of the scan, from the rough boxes a page tree gives them."""

from __future__ import annotations

from pathlib import Path


def picture_pieces(page) -> list[list[float]]:
    """Picture pieces on the page image: coloured, dark or edgy areas that are not words or page furniture.

    Words are blanked out using the scan's own word boxes, and so is the blue furniture (a unit's
    title band, the margin bar, section letters, exercise numbers). What is left, with thin frames
    and rules eroded away and nearby marks joined, is a list of pieces (boxes as page fractions).
    """
    import numpy as np

    pix = page.get_pixmap(alpha=False)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).astype(float) / 255
    height, width = rgb.shape[:2]
    grey = rgb.mean(axis=2)
    top, bottom = rgb.max(axis=2), rgb.min(axis=2)
    saturation = (top - bottom) / np.maximum(top, 1e-3)
    edges = np.zeros_like(grey)
    edges[1:-1, 1:-1] = np.abs(grey[2:, 1:-1] - grey[:-2, 1:-1]) + np.abs(grey[1:-1, 2:] - grey[1:-1, :-2])
    ink = (edges > 0.18) | ((saturation > 0.22) & (top < 0.985)) | (grey < 0.5)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    ys, xs = np.mgrid[0:height, 0:width]
    furniture = (ys < 0.125 * height) | (xs < 0.14 * width) | ((xs > 0.86 * width) & (ys < 0.09 * height))
    blue = (b > r + 0.16) & (b > g + 0.04) & furniture
    bar = blue & (xs < 0.14 * width)
    for _ in range(3):  # and the edge where the margin bar meets the page
        bar[1:] |= bar[:-1]
        bar[:-1] |= bar[1:]
        bar[:, 1:] |= bar[:, :-1]
        bar[:, :-1] |= bar[:, 1:]
    ink &= ~(blue | bar)
    for x1, y1, x2, y2, *_ in page.get_text("words"):
        ink[max(int(y1) - 1, 0) : int(y2) + 2, max(int(x1) - 1, 0) : int(x2) + 2] = False
    cell = 6
    h, w = height // cell, width // cell
    grid = ink[: h * cell, : w * cell].reshape(h, cell, w, cell).mean(axis=(1, 3)) > 0.05

    def shifted(mask, combine):
        out = mask.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out = combine(out, np.roll(np.roll(mask, dy, axis=0), dx, axis=1))
        return out

    # Thin frames and rules vanish when eroded; pictures survive. Then join nearby marks.
    grown = shifted(shifted(shifted(grid, np.logical_and), np.logical_or), np.logical_or)
    seen = np.zeros_like(grown)
    found = []
    for y in range(h):
        for x in range(w):
            if not grown[y, x] or seen[y, x]:
                continue
            stack, cells = [(y, x)], []
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if 0 <= ny < h and 0 <= nx < w and grown[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            cys, cxs = [c[0] for c in cells], [c[1] for c in cells]
            # Undo the cell the joining step added on each side.
            found.append([(min(cxs) + 1) / w, (min(cys) + 1) / h, max(cxs) / w, max(cys) / h])
    return found


def area(a: list) -> float:
    return max(0, a[2] - a[0]) * max(0, a[3] - a[1])


def overlap(a: list, b: list) -> float:
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def snap(box: list, pieces: list, others: list, margin: float = 0.04) -> list:
    """The picture around a rough box: every piece mostly inside it, or filling much of it,
    and not more another figure's; kept within the box grown by ``margin`` and out of the other boxes."""
    picked = []
    for piece in pieces:
        mine = overlap(piece, box)
        if area(piece) < 0.0004 or mine == 0 or any(overlap(piece, o) > mine for o in others):
            continue
        if mine >= 0.4 * area(piece) or mine >= 0.25 * area(box):
            picked.append(piece)
    if not picked:
        return box
    limit = [box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin]
    for o in others:  # do not grow into a neighbouring figure
        if overlap(limit, o) > 0:
            if o[0] >= box[2] - 0.01:
                limit[2] = min(limit[2], max(box[2], o[0]))
            if o[2] <= box[0] + 0.01:
                limit[0] = max(limit[0], min(box[0], o[2]))
            if o[1] >= box[3] - 0.01:
                limit[3] = min(limit[3], max(box[3], o[1]))
            if o[3] <= box[1] + 0.01:
                limit[1] = max(limit[1], min(box[1], o[3]))
    return [
        max(min(p[0] for p in picked), limit[0], 0),
        max(min(p[1] for p in picked), limit[1], 0),
        min(max(p[2] for p in picked), limit[2], 1),
        min(max(p[3] for p in picked), limit[3], 1),
    ]


def figure_blocks(blocks: list) -> list[dict]:
    """The figures of a page tree in reading order (sections, panels, exercises and columns opened)."""
    found = []
    for block in blocks:
        kind = block.get("type")
        if kind == "figure":
            found.append(block)
        elif kind in ("section", "box", "exercise"):
            found.extend(figure_blocks(block.get("blocks", [])))
        elif kind == "columns":
            for column in block.get("columns", []):
                found.extend(figure_blocks(column))
    return found


def _rough_boxes(node) -> list:
    if isinstance(node, dict):
        return ([node["box"]] if node.get("type") == "figure" else []) + [b for v in node.values() for b in _rough_boxes(v)]
    if isinstance(node, list):
        return [b for v in node for b in _rough_boxes(v)]
    return []


def cut_figures(document, number: int, blocks: list, out_dir: Path, *, content_width: float = 0.84) -> list[dict]:
    """Cut each figure of page ``number`` to ``out_dir`` as ``pNNN-i.jpg``.

    Returns ``{"src", "width"}`` per figure in reading order; ``width`` is the
    picture's share of the printed text width, in percent.
    """
    import fitz

    figures = figure_blocks(blocks)
    if not figures:
        return []
    page = document[number - 1]
    boxes = _rough_boxes(blocks)
    pieces = None
    out = []
    for index, block in enumerate(figures, 1):
        if block.get("exact"):
            x1, y1, x2, y2 = block["box"]
        else:
            if pieces is None:
                pieces = picture_pieces(page)
            x1, y1, x2, y2 = snap(block["box"], pieces, [b for b in boxes if b is not block["box"]])
        w, h = page.rect.width, page.rect.height
        clip = fitz.Rect(max(x1 - 0.005, 0) * w, max(y1 - 0.005, 0) * h, min(x2 + 0.005, 1) * w, min(y2 + 0.005, 1) * h)
        name = f"p{number:03d}-{index}.jpg"
        page.get_pixmap(clip=clip, matrix=fitz.Matrix(2.2, 2.2), alpha=False).save(str(out_dir / name), jpg_quality=82)
        out.append({"src": name, "width": min(round(100 * (x2 - x1) / content_width), 100)})
    return out
