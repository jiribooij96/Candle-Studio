"""Every preset: candle, silicone kit, rigid and flexible mold are clean solids;
operators, export and Load Design work. Run with run_tests.py."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from helpers import (Failures, check_mesh, draw_panels, load_addon, mold, out_dir,  # noqa: E402
                     read_stl, shape)

OUT = out_dir()
fails = Failures()
cs = load_addon()
cs.register()
load_addon().register()  # running the script twice (Text Editor) must re-register cleanly
cs.register()

t0 = time.time()
for key in cs.PRESETS:
    p = shape(cs, key)
    m = mold(cs)
    g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
    check_mesh(fails, cs.build_candle(g), f"{key}/candle")
    for mt in ("SILICONE", "RIGID", "FLEX"):
        m.mold_type = mt
        for suffix, mesh in cs.mold_parts(p, m, g):
            check_mesh(fails, mesh, f"{key}/{suffix}")
    m.flange_width = 0
    check_mesh(fails, cs.mold_parts(p, m, g)[0][1], f"{key}/mold_flex without rim")
print(f"preset molds: {time.time() - t0:.1f} s")

p = shape(cs, "SPIRAL_TAPER")
m = mold(cs, mold_type="FLEX")
t0 = time.time()
g = cs.candle_geometry(p, *cs.QUALITY["FINE"], m.wick_diameter)
mesh = cs.mold_parts(p, m, g)[0][1]
fails.expect(time.time() - t0 < 5.0, "FINE flex mold builds in under 5 s", f"{time.time() - t0:.2f} s")
check_mesh(fails, mesh, "SPIRAL_TAPER/FINE flex", overlap=False)

# operators end to end
scene = bpy.context.scene
props = scene.candle_studio
props.export_dir, props.open_bambu, props.export_candle = OUT, False, True
bpy.ops.candle.generate()
fails.expect(props.preset == "DEFAULT", "a fresh scene starts on the Defaults preset")
props.preset = "CLASSIC_SWIRL"
t0 = time.time()
for i in range(20):
    props.sway_angle = 10 + i  # a slider drag
fails.expect(time.time() - t0 < 2.0, "20 live updates stay quick", f"{time.time() - t0:.2f} s")
for mt, names in (("SILICONE", {"Candle Master", "Candle Sleeve"}), ("FLEX", {"Candle Mold"}),
                  ("RIGID", {"Candle Mold"}), ("NONE", set())):
    props.mold_type = mt
    bpy.ops.candle.build_mold()
    objs = {o.name for o in bpy.data.collections["Candle Studio"].objects} - {"Candle", "Candle Wick"}
    fails.expect(objs == names, f"Preview Mold ({mt}) shows the right parts", str(sorted(objs)))

props.mold_type = "SILICONE"
props.export_quality = "DRAFT"
bpy.ops.candle.export()
written = sorted(f for f in os.listdir(OUT) if f.endswith(".stl"))
fails.expect(written == ["swirl_candle_candle.stl", "swirl_candle_master.stl", "swirl_candle_sleeve.stl"],
             "export writes master, sleeve and candle", str(written))
for f in written:
    n, v = read_stl(os.path.join(OUT, f))
    fails.expect(abs(v[:, 2].min()) < 1e-4, f"{f} sits on z = 0")

props.preset = "BUBBLE_STACK"
bpy.ops.candle.load_design(filepath=os.path.join(OUT, "swirl_candle_design.json"))
fails.expect(props.ribs == 7 and abs(props.sway_angle - 29) < 1e-6, "Load Design restores the settings",
             f"ribs {props.ribs}, sway {props.sway_angle:.1f}")
bpy.ops.candle.randomize()

for mt in ("SILICONE", "SPLIT", "FLEX", "RIGID", "NONE"):
    props.mold_type = mt
    draw_panels(cs, scene)
fails.expect(True, "panels draw for every mold type")
cs.unregister()
fails.finish()
