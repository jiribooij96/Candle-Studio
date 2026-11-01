"""Panel and operators: shapes in the panel, presets, Defaults, Surprise Me,
saving and loading designs, and the filament estimate. Run with run_tests.py."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from helpers import Failures, draw_panels, load_addon, out_dir  # noqa: E402

OUT = out_dir()
fails = Failures()
cs = load_addon()
cs.register()
scene = bpy.context.scene
props = scene.candle_studio
props.export_dir, props.open_bambu, props.export_quality = OUT, False, "DRAFT"
bpy.ops.candle.generate()

for name in cs.BASE_SHAPES:
    props.base_shape = name
    for mt in ("SILICONE", "SPLIT", "FLEX", "RIGID", "NONE"):
        props.mold_type = mt
        draw_panels(cs, scene)
fails.expect(True, "panels draw for every shape and mold type")

props.preset = "TWISTED_TRIANGLE"
fails.expect(props.base_shape == "TRIANGLE" and abs(props.corner_round - 9) < 1e-6,
             "a preset sets its shape")
for _ in range(5):
    bpy.ops.candle.randomize()
fails.expect(props.base_shape == "TRIANGLE" and abs(props.corner_round - 9) < 1e-6,
             "Surprise Me keeps the shape")

# Defaults puts every shape and mold setting back
props.mold_type, props.split_wall, props.infill, props.show_wick = "SPLIT", 12.0, 40, False
props.preset = "DEFAULT"
off = []
for k, v in {**cs.SHAPE_DEFAULTS, **cs.MOLD_DEFAULTS}.items():
    cur = getattr(props, k)
    same = (max(abs(a - b) for a, b in zip(cur, v)) < 1e-6 if k == "color"
            else abs(cur - v) < 1e-5 if isinstance(v, float) else cur == v)
    if not same:
        off.append(k)
fails.expect(not off and props.show_wick, "Defaults resets every shape and mold setting", str(off))

# designs round-trip through the exported JSON; files from before shapes load as round
props.preset = "RIBBED_OVAL"
props.mold_type = "SILICONE"
props.design_name = "oval"
bpy.ops.candle.export()
path = os.path.join(OUT, "oval_design.json")
props.preset = "CLASSIC_SWIRL"
bpy.ops.candle.load_design(filepath=path)
fails.expect(props.base_shape == "OVAL" and abs(props.shape_stretch - 1.5) < 1e-6 and props.ribs == 18,
             "Load Design restores the shape")
data = json.load(open(path))
for k in ("base_shape", "shape_stretch", "corner_round"):
    del data["shape"][k]
json.dump(data, open(os.path.join(OUT, "old.json"), "w"))
bpy.ops.candle.load_design(filepath=os.path.join(OUT, "old.json"))
fails.expect(props.base_shape == "ROUND", "a design file without a shape loads as round")

# filament estimate for every printed mold, and the panel while it's pending and done
props.preset = "DEFAULT"
for mt in ("SILICONE", "SPLIT", "FLEX", "RIGID", "NONE"):
    props.mold_type = mt
    draw_panels(cs, scene)  # "Estimating..."
    angle = cs.run_split_check(scene)["angle"] if mt == "SPLIT" else 0.0
    parts = cs.run_print_estimate(scene, angle)
    draw_panels(cs, scene)
    if mt == "NONE":
        fails.expect(parts == [], "no estimate without a mold")
        continue
    material, density = cs.PRINT_MATERIAL[mt]
    grams = {cs.PART_NAMES[n]: cs.print_grams(v, a, 1.0 if solid else 0.15, density)
             for n, v, a, solid in parts}
    fails.expect(all(10 < g < 400 for g in grams.values()), f"{mt} estimate is plausible",
                 ", ".join(f"{n} {g:.0f} g" for n, g in grams.items()) + f" {material}")

# the live estimate (no booleans) agrees with the exported parts
props.mold_type = "SPLIT"
angle = cs.run_split_check(scene)["angle"]
live = sum(cs.print_grams(v, a, 0.15, 1.25) for n, v, a, s in cs.run_print_estimate(scene, angle) if not s)
p, m = cs._snapshot(props)
g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
exact = sum(cs.print_grams(mesh.volume(), mesh.area(), 0.15, 1.25)
            for suffix, mesh in cs.mold_parts(p, m, g, angle) if suffix != "screws_x4")
fails.expect(abs(live - exact) < 0.03 * exact, "live two-part estimate matches the real halves",
             f"{live:.0f} g vs {exact:.0f} g")
cs.unregister()
fails.finish()
