"""Install candle_studio.py as a real add-on (in the throwaway Blender profile
run_tests.py sets up) and export every mold type. Run with run_tests.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from helpers import ADDON, Failures, out_dir, read_stl  # noqa: E402

OUT = out_dir()
fails = Failures()
if "BLENDER_USER_SCRIPTS" not in os.environ:
    raise SystemExit("run this through run_tests.py: it installs the add-on into a throwaway profile")

bpy.ops.preferences.addon_install(filepath=ADDON)
bpy.ops.preferences.addon_enable(module="candle_studio")
fails.expect("candle_studio" in bpy.context.preferences.addons, "add-on installs and enables")

s = bpy.context.scene.candle_studio
s.export_dir, s.open_bambu, s.export_quality = OUT, False, "DRAFT"
designs = {"SILICONE": "RIBBED_OVAL", "SPLIT": "SQUARE_CUSHIONS", "WEDGE": "TWISTED_SQUARE",
           "FLEX": "TWISTED_TRIANGLE", "RIGID": "TWISTED_HEX", "NONE": "CLASSIC_SWIRL"}
expected = {"SILICONE": ["master", "sleeve"], "SPLIT": ["half_a", "half_b", "screws_x4"],
            "WEDGE": ["wedge_1", "wedge_2", "wedge_3", "wedge_4", "plug"],
            "FLEX": ["mold_flex"], "RIGID": ["mold_rigid"], "NONE": ["candle"]}
for mt, preset in designs.items():
    s.preset = preset
    s.mold_type = mt
    s.design_name = mt.lower()
    bpy.ops.candle.generate()
    bpy.ops.candle.export()
    for suffix in expected[mt]:
        path = os.path.join(OUT, f"{mt.lower()}_{suffix}.stl")
        if not fails.expect(os.path.exists(path), f"{mt}: {suffix}.stl written"):
            continue
        n, v = read_stl(path)
        fails.expect(n > 0 and abs(v[:, 2].min()) < 1e-4, f"{mt}: {suffix}.stl lies on the bed",
                     f"{n} triangles, {v.max(0)[0] - v.min(0)[0]:.0f} x {v.max(0)[1] - v.min(0)[1]:.0f}"
                     f" x {v.max(0)[2]:.0f} mm")
bpy.ops.preferences.addon_disable(module="candle_studio")
fails.finish()
