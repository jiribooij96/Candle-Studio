"""Printed wedge mold: the release check, how many wedges each preset needs,
clean wedges and plug for every preset, the parts fitting together, the
estimate, and the live check in the panel. Run with run_tests.py."""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402
from helpers import Failures, check_mesh, draw_panels, load_addon, mold, out_dir, shape  # noqa: E402

OUT = out_dir()
fails = Failures()
cs = load_addon()
cs.register()

xy = cs._wedge_slices(shape(cs, ribs=0))
fails.expect(all(cs.pieces_trapped(xy, n, math.radians(a)) == 0.0 for n in cs.WEDGE_COUNTS for a in (0, 7, 33)),
             "a plain round candle releases at any seam")

# how many wedges each preset needs (None: locks even in 6)
needs = {"ROPE_TWIST": 4, "ORGANIC": 4, "TWISTED_SQUARE": 4, "TWISTED_TRIANGLE": 4,
         "CURVED_SPIRAL": 5, "WAVE_FINS": 6, "SWIRL_FADE": None, "DRAPED_S": None}
wrong, slowest = [], (0.0, "")
t0 = time.time()
for key in cs.PRESETS:
    t1 = time.time()
    n, angle, trapped = cs.best_wedges(shape(cs, key))
    slowest = max(slowest, (time.time() - t1, key))
    print(f"     {key:17s} {n} wedges, seam {angle:6.2f} deg, worst undercut {trapped:5.2f} mm")
    got = n if trapped <= cs.LOCK_TOL else None
    if got != needs.get(key, 3):
        wrong.append(f"{key}: {got}")
fails.expect(not wrong, "each preset gets the right number of wedges", ", ".join(wrong))
fails.expect(time.time() - t0 < 0.4 * len(cs.PRESETS) and slowest[0] < 2.5, "wedge checks are quick",
             f"{time.time() - t0:.1f} s in all, slowest {slowest[1]} {slowest[0]:.2f} s")
square = shape(cs, "TWISTED_SQUARE")
fails.expect(cs.best_wedges(square, 3)[2] > cs.LOCK_TOL and cs.best_wedges(square, 4)[2] <= cs.LOCK_TOL,
             "a chosen count is checked as is: Twisted Square locks in 3, releases in 4")
lobes = shape(cs, height=91, diameter=40, ribs=4, rib_depth=7.6, rib_fullness=0.5, twist_turns=0.8, top_round=0)
fails.expect(cs.best_wedges(lobes, 3)[2] > 1.0 and cs.best_wedges(lobes, 4)[2] <= cs.LOCK_TOL,
             "4 deep twisted lobes (like the 3-piece mold from the web) need 4 wedges",
             f"3: {cs.best_wedges(lobes, 3)[2]:.2f} mm, 4: {cs.best_wedges(lobes, 4)[2]:.2f} mm")

# wedges and plug for every preset are clean solids, each lying on the bed
m = mold(cs, mold_type="WEDGE")
for key in cs.PRESETS:
    p = shape(cs, key)
    g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
    parts = cs.mold_parts(p, m, g)
    for suffix, mesh in parts:
        check_mesh(fails, mesh, f"{key}/{suffix}")
    fails.expect(len(parts) == cs.best_wedges(p)[0] + 1 and all(abs(mesh.verts[:, 2].min()) < 1e-9
                                                                 for _, mesh in parts),
                 f"{key}: one file per wedge plus the plug, all on the bed")

# the parts fit: built in place, the wedges are the sleeve minus exactly the
# candle and the socket, and the plug has the fit gap all round its side
for key in ("TWISTED_SQUARE", "S_CURVE", "WAVE_FINS"):
    p = shape(cs, key)
    g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
    n, angle, _ = cs.best_wedges(p)
    L = cs._wedge_layout(g, m)
    phi = math.radians(angle) + math.pi / len(g.theta)
    candle, socket = cs._wedge_cutters(g, L, phi, n)
    blocks = [cs._wedge_block(L, phi + k * cs.TAU / n, phi + (k + 1) * cs.TAU / n) for k in range(n)]
    wedges = [cs.boolean_mesh(b, cut=(candle, socket)) for b in blocks]
    plug = cs.build_wedge_plug(g, m, L)
    body = cs.loft(g.rings[:L.face + 1], cap_start=(*g.centers[0], 0.0), cap_end=(*g.centers[L.face], L.z_face))
    lid = 0.5 * 240 * L.R_sock ** 2 * math.sin(cs.TAU / 240)  # the socket cutter sticks out 1 mm
    expect = sum(b.volume() for b in blocks) - body.volume() - (socket.volume() - lid)
    got = sum(w.volume() for w in wedges)
    fails.expect(abs(got / expect - 1.0) < 1e-4, f"{key}: wedges are the sleeve minus candle and socket",
                 f"{got / expect:.6f}")
    v = plug.verts
    side = (np.linalg.norm(v[:, :2] - L.c, axis=1) > L.R_plug - 1e-6) & (v[:, 2] > L.z_face + 1e-6) \
        & (v[:, 2] < L.z_end - 1e-6)
    trees = [BVHTree.FromPolygons(w.verts.tolist(), w.triangles().tolist()) for w in wedges]
    gap = np.array([min(t.find_nearest(Vector(x))[3] for t in trees) for x in v[side]])
    fails.expect(abs(gap.min() - cs.PLUG_FIT) < 0.01 and gap.max() < cs.PLUG_FIT + 0.1,
                 f"{key}: plug and tongue sit in the socket with a {cs.PLUG_FIT} mm gap",
                 f"{gap.min():.3f}..{gap.max():.3f} mm")

# the live estimate (no booleans) agrees with the real wedges
for key in ("RIBBED_SPIRAL", "S_CURVE", "TWISTED_TRIANGLE"):
    p = shape(cs, key)
    g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
    n, angle, _ = cs.best_wedges(p)
    live = sum(cs.print_grams(v, a, 0.15, 1.25) for _, v, a, _ in cs.print_parts(p, m, g, 0.0, (n, angle)))
    exact = sum(cs.print_grams(mesh.volume(), mesh.area(), 0.15, 1.25)
                for _, mesh in cs.mold_parts(p, m, g, None, (n, angle)))
    fails.expect(abs(live - exact) < 0.02 * exact, f"{key}: live wedge estimate matches the real parts",
                 f"{live:.0f} g vs {exact:.0f} g")

# live check, lock painting, preview and export from the panel
scene = bpy.context.scene
props = scene.candle_studio
props.export_dir, props.open_bambu, props.export_quality = OUT, False, "DRAFT"
bpy.ops.candle.generate()
props.preset = "RIBBED_SPIRAL"
props.mold_type = "WEDGE"
fails.expect(bpy.app.timers.is_registered(cs._mold_timer), "a change schedules the wedge check")
me = scene.objects["Candle"].data
for key, count, ok in (("RIBBED_SPIRAL", None, True), ("DRAPED_S", None, False),
                       ("TWISTED_SQUARE", 3, False), ("TWISTED_SQUARE", 4, True)):
    props.preset = key
    props.wedge_auto = count is None
    props.wedge_count = count or 4
    res = cs.run_wedge_check(scene)
    col = np.empty(len(me.vertices) * 4, np.float32)
    me.color_attributes["Candle Locks"].data.foreach_get("color", col)
    red = int((col.reshape(-1, 4)[:, 1] < 0.1).sum())
    fails.expect(res["ok"] == ok and (red == 0) == ok and (count is None or res["pieces"] == count),
                 f"{key} in {count or 'auto'} wedges: {'releases' if ok else 'locks'}, "
                 f"{'no' if ok else 'some'} red areas", f"{res['pieces']} wedges, {res['trapped']:.2f} mm, {red} red")
props.wedge_auto = True
parts = cs.run_print_estimate(scene, 0.0, (res["pieces"], res["angle"]))
grams = [cs.print_grams(v, a, 0.15, 1.25) for _, v, a, _ in parts]
fails.expect(len(parts) == 5 and all(5 < x < 300 for x in grams), "wedge estimate is plausible",
             ", ".join(f"{x:.0f} g" for x in grams))
props.preset = "TWISTED_SQUARE"
bpy.ops.candle.build_mold()
objs = {o.name for o in bpy.data.collections["Candle Studio"].objects}
want = {"Candle Wedge 1", "Candle Wedge 2", "Candle Wedge 3", "Candle Wedge 4", "Candle Plug"}
fails.expect(want <= objs, "Preview Mold shows the 4 wedges and the plug", str(sorted(objs)))
props.design_name = "square_wedges"
bpy.ops.candle.export()
written = sorted(f for f in os.listdir(OUT) if f.endswith(".stl"))
fails.expect(written == [f"square_wedges_{s}.stl" for s in ("plug", "wedge_1", "wedge_2", "wedge_3", "wedge_4")],
             "export writes every wedge and the plug", str(written))
fails.expect(not [o for o in bpy.data.objects if o.name.startswith("cs_tmp")],
             "no temporary boolean objects left behind")

for auto in (True, False):
    props.wedge_auto = auto
    for state in (None, "ok", "bad"):
        cs._stats.pop("wedge", None)
        if state:
            cs._stats["wedge"] = dict(pieces=4, angle=0.0, trapped=0.0 if state == "ok" else 3.1, ok=state == "ok")
        draw_panels(cs, scene)
fails.expect(True, "panel draws while checking, releasing and locking")
cs.unregister()
fails.finish()
