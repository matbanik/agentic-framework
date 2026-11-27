"""Build the README feature map as a blank canvas plus av-kit annotation marks.

Usage: python build_feature_map.py <content.json> <out_dir>

Writes <out_dir>/feature-map-canvas.png (a blank white canvas) and
<out_dir>/feature-map.marks.json (the marks for the av-kit `annotate` action).
av-kit draws text in Segoe UI at font_size pixels, so this script measures
text with the same font to wrap it and to set the card sizes. It needs
Pillow and the Segoe UI font file (Windows).

To make docs/diagrams/feature-map.png again, after a change to the content:

1. Run this script.
2. av-kit `capture`, mode `import`, path = the canvas PNG. Note the shot id.
3. av-kit `annotate` with that id and the contents of the marks file.
4. av-kit `export`, format `png`. Copy the result to docs/diagrams/feature-map.png.

Each card has a red part (the pain) above a green part (the solution).
Each section is a grid of three columns. In the section that has
`"loop": true`, the second row runs from right to left, so the arrows
make a loop.
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageFont

FONT = "C:/Windows/Fonts/segoeui.ttf"
W = 1600
MARGIN = 40
COLS = 3
COL_GAP = 44
CARD_W = (W - 2 * MARGIN - (COLS - 1) * COL_GAP) // COLS
PAD = 16
BAR = 8
BADGE = 40
TITLE_SIZE, BODY_SIZE, PAIN_SIZE = 25, 20, 20
ROW_GAP = 18
LOOP_ROW_GAP = 60
BAND_H = 46

INK = "#1B2631"
MUTED = "#566573"
PAIN_FILL, PAIN_BAR, PAIN_INK = "#FDEDEC", "#C0392B", "#641E16"
SOL_FILL, SOL_BAR, SOL_INK = "#EAF7EF", "#1E8449", "#145A32"
BAND_FILL = "#1F2D3D"
FLOW = "#1E8449"

_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT, size)
    return _fonts[size]


def width(text, size):
    return font(size).getlength(text)


def line_h(size):
    return math.ceil(size * 1.33)


def wrap(text, size, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and width(trial, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def main():
    content = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    marks = []

    def fill(x, y, w, h, color):
        marks.append({"type": "highlight", "x": x, "y": y, "width": w, "height": h,
                      "color": color, "opacity": 1})

    def text(x, y, s, color, size):
        marks.append({"type": "text", "x": round(x), "y": round(y), "text": s,
                      "color": color, "font_size": size})

    def arrow(a, b, stroke=4, head="end"):
        marks.append({"type": "arrow", "from": a, "to": b, "color": FLOW,
                      "stroke_width": stroke, "head": head})

    y = 30
    text(MARGIN, y, content["title"], INK, 38)
    y += line_h(38) + 4
    text(MARGIN, y, content["subtitle"], MUTED, 22)
    # Legend, at the right of the subtitle line.
    lx = W - MARGIN
    for label, color in (("the solution", SOL_BAR), ("the pain", PAIN_BAR)):
        lx -= round(width(label, 20))
        text(lx, y + 2, label, color, 20)
        lx -= 28
        fill(lx, y + 8, 18, 18, color)
        lx -= 26
    y += line_h(22) + 20

    text_w = CARD_W - BAR - 2 * PAD
    for section in content["sections"]:
        fill(MARGIN, y, W - 2 * MARGIN, BAND_H, BAND_FILL)
        text(MARGIN + PAD, y + 8, section["name"], "#FFFFFF", 22)
        note = section.get("note")
        if note:
            text(W - MARGIN - PAD - width(note, 19), y + 11, note, "#D5DBDB", 19)
        y += BAND_H + 14

        cards = section["cards"]
        is_loop = section.get("loop", False)
        rows = [cards[i:i + COLS] for i in range(0, len(cards), COLS)]
        boxes = {}
        for r, row in enumerate(rows):
            pains = [wrap(c["pain"], PAIN_SIZE, text_w) for c in row]
            bodies = []
            for c in row:
                title_w = text_w - (BADGE + 12 if c.get("step") else 0)
                assert width(c["feature"], TITLE_SIZE) <= title_w, c["feature"]
                bodies.append(wrap(c["solution"], BODY_SIZE, text_w))
            pain_h = max(len(p) for p in pains) * line_h(PAIN_SIZE) + 2 * PAD - 6
            head_h = max(line_h(TITLE_SIZE), BADGE) + 8
            sol_h = (PAD - 2 + head_h
                     + max(len(b) for b in bodies) * line_h(BODY_SIZE) + PAD - 4)
            reverse = is_loop and r % 2 == 1
            for i, c in enumerate(row):
                col = COLS - 1 - i if reverse else i
                x = MARGIN + col * (CARD_W + COL_GAP)
                fill(x, y, CARD_W, pain_h, PAIN_FILL)
                fill(x, y, BAR, pain_h, PAIN_BAR)
                text(x + BAR + PAD, y + PAD - 7, "\n".join(pains[i]), PAIN_INK, PAIN_SIZE)
                sy = y + pain_h
                fill(x, sy, CARD_W, sol_h, SOL_FILL)
                fill(x, sy, BAR, sol_h, SOL_BAR)
                tx = x + BAR + PAD
                ty = sy + PAD - 2
                if c.get("step"):
                    marks.append({"type": "step", "x": tx + BADGE // 2,
                                  "y": ty + head_h // 2 - 4, "number": c["step"],
                                  "color": SOL_BAR, "size": BADGE})
                    text(tx + BADGE + 12, ty + (head_h - 8 - line_h(TITLE_SIZE)) // 2,
                         c["feature"], SOL_INK, TITLE_SIZE)
                else:
                    text(tx, ty + (head_h - 8 - line_h(TITLE_SIZE)) // 2,
                         c["feature"], SOL_INK, TITLE_SIZE)
                text(tx, ty + head_h - 4, "\n".join(bodies[i]), INK, BODY_SIZE)
                boxes[c["id"]] = (x, y, CARD_W, pain_h + sol_h)
            y += pain_h + sol_h + (LOOP_ROW_GAP if is_loop and r < len(rows) - 1 else ROW_GAP)

        if is_loop:
            ids = [c["id"] for c in cards]
            for a, b in zip(ids, ids[1:]):
                ax, ay, aw, ah = boxes[a]
                bx, by, bw, bh = boxes[b]
                if ay == by and bx > ax:      # same row, to the right
                    arrow([ax + aw + 6, ay + ah // 2], [bx - 6, by + bh // 2])
                elif ay == by:                # same row, to the left
                    arrow([ax - 6, ay + ah // 2], [bx + bw + 6, by + bh // 2])
                else:                         # down to the next row
                    arrow([ax + aw // 2, ay + ah + 5], [bx + bw // 2, by - 5])
            back = section.get("loop_back")
            if back:
                ax, ay, aw, ah = boxes[back["from"]]
                bx, by, bw, bh = boxes[back["to"]]
                # Up from the last step, then to the right, then up into the target.
                x1 = ax + aw // 2
                x2 = bx + bw // 2
                mid = (by + bh + ay) // 2
                arrow([x1, ay - 3], [x1, mid], head="none")
                arrow([x1, mid], [x2, mid], head="none")
                arrow([x2, mid], [x2, by + bh + 5])
                label = back["label"]
                text((x1 + x2) / 2 - width(label, 18) / 2, mid - 27, label, FLOW, 18)
        y += 8

    for ln in content.get("footer", []):
        text(MARGIN, y, ln, MUTED, 20)
        y += line_h(20)
    height = y + 22

    out.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (W, height), "#FFFFFF").save(out / "feature-map-canvas.png")
    (out / "feature-map.marks.json").write_text(
        json.dumps(marks, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"canvas {W}x{height}, {len(marks)} marks, "
          f"{(out / 'feature-map.marks.json').stat().st_size} bytes")


if __name__ == "__main__":
    main()
