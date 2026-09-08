"""Split an artist's SVG into single entries — one word, or one line, each.

Handwriting arrives from the artist as whole sentences: one `<path>` per stroke
of the brush, all of it in one file, with no structure saying where a word ends.
For the scene protocol each entry wants to be separately addressable, so this
finds the words and writes them out one by one.

    tools/split_svg.py assets/svg-source/schrift1.svg --out assets/entries

It does three things a naive split cannot:

* **Keeps the curves.** Contours are cut out of the source `d` as text, so the
  artist's béziers survive untouched. Flattening happens only to measure.
* **Drops the dust.** Tracing leaves specks a unit or two across. The dot on an
  `i` is twenty times that, so a size threshold separates them cleanly.
* **Keeps the counters.** White shapes are the holes inside letters. Each is
  attached to the black contour that contains it, so a word carries its own
  holes rather than losing them to the next entry.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mementum_node.core.geometry import flatten_path  # noqa: E402

#: Contours smaller than this in both dimensions are tracing dust, not marks.
DUST = 8.0

#: A gap wider than this fraction of the line's height starts a new word.
WORD_GAP = 0.15

Box = tuple[float, float, float, float]


def _bbox(d: str) -> Box | None:
    points = [point for subpath in flatten_path(d) for point in subpath]
    if len(points) < 3:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def read_contours(svg: str) -> list[dict]:
    """Every closed contour in the file, with its own path data and box."""
    out: list[dict] = []
    for attrs, d in re.findall(r"<path([^>]*?)\sd=\"([^\"]*)\"", svg, re.S):
        white = "FFFFFF" in attrs.upper()
        flat = d.replace("\n", " ").replace("\t", " ")
        for piece in re.split(r"(?=M)", flat):
            piece = piece.strip()
            if not piece.startswith("M"):
                continue
            box = _bbox(piece)
            if box is None:
                continue
            out.append({"d": piece, "white": white, "box": box})
    return out


def _overlaps_y(a: Box, b: Box) -> bool:
    return not (a[3] < b[1] or b[3] < a[1])


def _contains(outer: Box, inner: Box) -> bool:
    return (
        outer[0] <= inner[0] and outer[1] <= inner[1]
        and outer[2] >= inner[2] and outer[3] >= inner[3]
    )


def _union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


def group_lines(marks: list[dict]) -> list[list[dict]]:
    """Contours into lines of writing, by vertical overlap with the line so far."""
    lines: list[list[dict]] = []
    for mark in sorted(marks, key=lambda m: m["box"][1]):
        for line in lines:
            if _overlaps_y(_union([m["box"] for m in line]), mark["box"]):
                line.append(mark)
                break
        else:
            lines.append([mark])
    return [sorted(line, key=lambda m: m["box"][0]) for line in lines]


def group_words(line: list[dict], gap_factor: float = WORD_GAP) -> list[list[dict]]:
    """A line into words, by horizontal gaps relative to the line's height.

    Cursive letters within a word touch or overlap; the space between words is
    the only reliably large gap, so the threshold scales with how big the
    writing is rather than being an absolute number of units."""
    box = _union([m["box"] for m in line])
    threshold = (box[3] - box[1]) * gap_factor

    words: list[list[dict]] = [[line[0]]]
    reach = line[0]["box"][2]
    for mark in line[1:]:
        if mark["box"][0] - reach > threshold:
            words.append([mark])
        else:
            words[-1].append(mark)
        reach = max(reach, mark["box"][2])
    return words


def split(svg: str, dust: float = DUST, gap_factor: float = WORD_GAP,
          by: str = "word") -> list[dict]:
    """Entries, in reading order, each with its marks and its counters."""
    contours = read_contours(svg)
    marks = [
        c for c in contours
        if not c["white"]
        and (c["box"][2] - c["box"][0] > dust or c["box"][3] - c["box"][1] > dust)
    ]
    counters = [c for c in contours if c["white"]]

    entries: list[dict] = []
    for line_index, line in enumerate(group_lines(marks)):
        groups = [line] if by == "line" else group_words(line, gap_factor)
        for word_index, group in enumerate(groups):
            box = _union([m["box"] for m in group])
            holes = [
                c for c in counters
                if any(_contains(m["box"], c["box"]) for m in group)
            ]
            entries.append({
                "line": line_index,
                "index": word_index,
                "box": [round(v, 3) for v in box],
                "marks": [m["d"] for m in group],
                "holes": [h["d"] for h in holes],
            })
    return entries


def write_svg(entry: dict, path: str, pad: float = 12.0) -> None:
    """One entry as its own SVG, in the artist's original coordinates."""
    x0, y0, x1, y1 = entry["box"]
    width, height = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    body = "\n".join(
        f'  <path fill-rule="evenodd" clip-rule="evenodd" d="{d}"/>' for d in entry["marks"]
    )
    holes = "\n".join(
        f'  <path fill-rule="evenodd" clip-rule="evenodd" fill="#FFFFFF" d="{d}"/>'
        for d in entry["holes"]
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'viewBox="{x0 - pad:.2f} {y0 - pad:.2f} {width:.2f} {height:.2f}">\n'
            f"{body}\n{holes}\n</svg>\n"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="split an artist SVG into entries")
    parser.add_argument("source")
    parser.add_argument("--out", default="assets/entries")
    parser.add_argument("--by", choices=("word", "line"), default="word")
    parser.add_argument("--dust", type=float, default=DUST)
    parser.add_argument("--gap", type=float, default=WORD_GAP)
    args = parser.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        entries = split(fh.read(), args.dust, args.gap, args.by)

    stem = os.path.splitext(os.path.basename(args.source))[0]
    out_dir = os.path.join(args.out, stem)
    os.makedirs(out_dir, exist_ok=True)

    manifest = []
    for n, entry in enumerate(entries):
        name = f"{stem}_{n:02d}_l{entry['line']}w{entry['index']}.svg"
        write_svg(entry, os.path.join(out_dir, name))
        manifest.append({
            "file": name, "line": entry["line"], "index": entry["index"],
            "box": entry["box"], "marks": len(entry["marks"]), "holes": len(entry["holes"]),
        })
        box = entry["box"]
        print(f"  {name:36s} {box[2]-box[0]:7.1f} x {box[3]-box[1]:6.1f}  "
              f"{len(entry['marks'])} marks, {len(entry['holes'])} holes")

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": os.path.basename(args.source), "entries": manifest}, fh, indent=2)
    print(f"  -> {len(entries)} entries in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
