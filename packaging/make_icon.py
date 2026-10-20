"""Draws the application icon (an ascending line over a risk grid) as a
multi-resolution .ico. Run once; the result is committed in packaging/."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=48, fill=(14, 19, 29, 255))
colors = [(46, 125, 50), (181, 154, 0), (199, 119, 0), (179, 38, 30)]
cell = 40
x0, y0 = 48, 48
for r in range(4):
    for c in range(4):
        col = colors[min(3, ((3 - r) + c) // 2)]
        d.rounded_rectangle((x0 + c * cell + 3, y0 + r * cell + 3, x0 + (c + 1) * cell - 3, y0 + (r + 1) * cell - 3),
                            radius=6, fill=(*col, 150))
pts = [(56, 200), (104, 160), (144, 172), (200, 72)]
d.line(pts, fill=(63, 184, 183, 255), width=16, joint="curve")
d.polygon([(214, 52), (176, 66), (206, 98)], fill=(63, 184, 183, 255))
out = Path(__file__).with_name("RiskAscent.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(Path(__file__).with_name("RiskAscent.png"))
print(out)
