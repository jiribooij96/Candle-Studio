"""Printed two-part mold: the release check, the halves and screws of every
preset, the thread fit and the live check in the panel. Run with run_tests.py."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import bpy  # noqa: E402
from helpers import Failures, check_mesh, draw_panels, load_addon, mold, out_dir, shape  # noqa: E402

OUT = out_dir()
fails = Failures()
cs = load_addon()
cs.register()

# release check: these presets come out of two rigid halves, the rest lock
released = set()
t0 = time.time()
for key in cs.PRESETS:
    angle, trapped = cs.best_split(shape(cs, key))
    print(f"     {key:17s} seam {angle:5.1f} deg, worst undercut {trapped:5.2f} mm")
    if trapped <= cs.LOCK_TOL:
        released.add(key)
expected = {"BUBBLE_STACK", "CURVY", "RIBBED_OVAL", "SQUARE_CUSHIONS"}
fails.expect(released == expected, "the right presets release", str(sorted(released)))
fails.expect(time.time() - t0 < 0.5 * len(cs.PRESETS), "release checks are quick",
             f"{time.time() - t0:.1f} s for {len(cs.PRESETS)}")
angle, trapped = cs.best_split(shape(cs, ribs=8, rib_depth=4.0, rib_fullness=0.0))
fails.expect(trapped <= cs.LOCK_TOL, "8 straight ribs release", f"seam {angle}")

# halves and screws for every preset, plus the other fasteners
m = mold(cs, mold_type="SPLIT")
for key in cs.PRESETS:
    g = cs.candle_geometry(shape(cs, key), 180, 0.8, m.wick_diameter)
    for suffix, mesh in cs.mold_parts(shape(cs, key), m, g, 0.0):
        check_mesh(fails, mesh, f"{key}/{suffix}", overlap=suffix != "screws_x4")
for fastener in ("M5", "NONE"):
    m.fastener = fastener
    g = cs.candle_geometry(shape(cs, "BUBBLE_STACK"), 180, 0.8, m.wick_diameter)
    for suffix, mesh in cs.mold_parts(shape(cs, "BUBBLE_STACK"), m, g, 0.0):
        check_mesh(fails, mesh, f"BUBBLE_STACK/{fastener}/{suffix}")
check_mesh(fails, cs.build_screw(30.0, 33.0), "screw on its own")

# screw and nut thread come from the same helix: the gap is the clearance everywhere
s, r_nut, _ = cs._thread_rings(0.0, 10.0, extra=cs.SCREW["clearance"])
s, r_screw, _ = cs._thread_rings(0.0, 10.0)
gap = r_nut - r_screw
fails.expect(np.allclose(gap, cs.SCREW["clearance"]), "thread gap equals the clearance",
             f"{gap.min():.3f}..{gap.max():.3f} mm")

# live check, lock painting, preview and export from the panel
scene = bpy.context.scene
props = scene.candle_studio
props.export_dir, props.open_bambu = OUT, False
bpy.ops.candle.generate()
props.preset = "BUBBLE_STACK"
props.mold_type = "SPLIT"
fails.expect(bpy.app.timers.is_registered(cs._mold_timer), "a change schedules the release check")
me = scene.objects["Candle"].data
col = np.empty(len(me.vertices) * 4, np.float32)
for key, ok in (("BUBBLE_STACK", True), ("CLASSIC_SWIRL", False)):
    props.preset = key
    res = cs.run_split_check(scene)
    me.color_attributes["Candle Locks"].data.foreach_get("color", col)
    red = int((col.reshape(-1, 4)[:, 1] < 0.1).sum())
    fails.expect(res["ok"] == ok and (red == 0) == ok, f"{key}: {'releases' if ok else 'locks'}, "
                 f"{'no' if ok else 'some'} red areas", f"{res['trapped']:.2f} mm, {red} red vertices")
props.preset = "CURVY"
bpy.ops.candle.build_mold()
objs = {o.name for o in bpy.data.collections["Candle Studio"].objects}
fails.expect({"Candle Mold A", "Candle Mold B", "Candle Screws"} <= objs, "Preview Mold shows both halves")
props.design_name = "curvy_split"
bpy.ops.candle.export()
written = sorted(f for f in os.listdir(OUT) if f.endswith(".stl"))
fails.expect(written == ["curvy_split_half_a.stl", "curvy_split_half_b.stl", "curvy_split_screws_x4.stl"],
             "export writes both halves and the screws", str(written))
fails.expect(not [o for o in bpy.data.objects if o.name.startswith("cs_tmp")]
             and not [c for c in bpy.data.collections if c.name.startswith("cs_tmp")],
             "no temporary boolean objects left behind")

for state in (None, "ok", "bad"):
    cs._stats.pop("split", None)
    if state:
        cs._stats["split"] = dict(angle=12.0, trapped=0.0 if state == "ok" else 4.2, ok=state == "ok")
    draw_panels(cs, scene)
fails.expect(True, "panel draws while checking, releasing and locking")
cs.unregister()
fails.finish()
