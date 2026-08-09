from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
APP_ICON = ROOT / "TreeWatering/Resources/Assets.xcassets/AppIcon.appiconset"
APP_ICON.mkdir(parents=True, exist_ok=True)

SCALE = 4
SIZE = 1024
canvas = Image.new("RGB", (SIZE * SCALE, SIZE * SCALE), "#123e2b")
pixels = canvas.load()
center_x, center_y = SIZE * SCALE * 0.35, SIZE * SCALE * 0.20
max_distance = (SIZE * SCALE * 1.15) ** 2
for y in range(SIZE * SCALE):
    for x in range(SIZE * SCALE):
        ratio = min(1.0, ((x - center_x) ** 2 + (y - center_y) ** 2) / max_distance)
        pixels[x, y] = (
            int(25 + 8 * ratio),
            int(78 - 18 * ratio),
            int(53 - 8 * ratio),
        )

draw = ImageDraw.Draw(canvas, "RGBA")
def box(values):
    return tuple(int(value * SCALE) for value in values)

draw.ellipse(box((72, 65, 770, 763)), fill=(55, 150, 128, 22))
draw.ellipse(box((490, 250, 1110, 870)), fill=(12, 34, 25, 28))

# Sample a cubic Bezier outline for a broad, friendly water drop.
def cubic(p0, p1, p2, p3, steps=80):
    points = []
    for index in range(steps + 1):
        t = index / steps
        u = 1 - t
        x = u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]
        points.append((int(x*SCALE), int(y*SCALE)))
    return points

segments = [
    ((500, 166), (466, 258), (294, 426), (294, 612)),
    ((294, 612), (294, 780), (390, 868), (512, 868)),
    ((512, 868), (650, 868), (738, 770), (738, 620)),
    ((738, 620), (738, 430), (559, 256), (500, 166)),
]
path = []
for segment in segments:
    path.extend(cubic(*segment))
draw.polygon(path, fill=(246, 243, 224, 255))

# A pointed blue-green leaf stays legible at notification-icon sizes.
leaf_segments = [
    ((548, 360), (610, 224), (728, 176), (844, 196)),
    ((844, 196), (794, 316), (674, 388), (548, 360)),
]
leaf_path = []
for segment in leaf_segments:
    leaf_path.extend(cubic(*segment))
draw.polygon(leaf_path, fill=(41, 171, 183, 255))
# Keep the vein inside the leaf so it cannot read as a prohibition slash.
vein = cubic((584, 344), (642, 314), (724, 252), (792, 218), steps=36)
draw.line(vein, fill=(18, 75, 61, 210), width=10*SCALE, joint="curve")
draw.ellipse(box((579, 339, 589, 349)), fill=(18, 75, 61, 210))
draw.ellipse(box((787, 213, 797, 223)), fill=(18, 75, 61, 210))

# Quiet highlight rather than a glossy effect.
draw.ellipse(box((407, 470, 464, 591)), fill=(255, 255, 255, 68))
source = canvas.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
source.save(APP_ICON / "AppIcon-1024.png", optimize=True)

sizes = {
    "AppIcon-20@2x.png": 40,
    "AppIcon-20@3x.png": 60,
    "AppIcon-29@2x.png": 58,
    "AppIcon-29@3x.png": 87,
    "AppIcon-40@2x.png": 80,
    "AppIcon-40@3x.png": 120,
    "AppIcon-60@2x.png": 120,
    "AppIcon-60@3x.png": 180,
}
for filename, size in sizes.items():
    source.resize((size, size), Image.Resampling.LANCZOS).save(APP_ICON / filename, optimize=True)
