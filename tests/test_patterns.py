"""Rib Lean, Fade Top / Bottom and Twist Focus: what they do, that they are
off by default, and that the rigid-mold check knows about them. Run with run_tests.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from helpers import Failures, check_mesh, load_addon, mold, shape  # noqa: E402

fails = Failures()
cs = load_addon()

# all three are off by default: zero values give exactly the old geometry
p = shape(cs, "CLASSIC_SWIRL")
q = shape(cs, "CLASSIC_SWIRL", rib_lean=0.0, fade_bottom=0.0, fade_top=0.0, twist_focus=0.0)
fails.expect(np.array_equal(cs.candle_geometry(p, 180, 1.0).rings, cs.candle_geometry(q, 180, 1.0).rings),
             "new settings at 0 change nothing")

# fade: smooth ends, full ribs in between
p = shape(cs, ribs=10, rib_depth=4.0, fade_bottom=20, fade_top=30, top_round=0)
g = cs.candle_geometry(p, 360, 0.5)
mid = np.ptp(g.r[len(g.z) // 2])
fails.expect(np.ptp(g.r[0]) < 1e-9 and np.ptp(g.r[-1]) < 1e-9 and abs(mid - 4.0) < 0.01,
             "Fade Bottom / Top smooth the ends", f"bottom {np.ptp(g.r[0]):.1e}, top {np.ptp(g.r[-1]):.1e}, "
             f"middle {mid:.2f} mm ribs")
f = cs._rib_fade(p, np.array([0.0, 0.1, 0.2, 0.5, 0.85, 1.0]))
fails.expect(np.all(np.diff(f[:3]) > 0) and f[3] == 1.0 and 0 < f[4] < 1 and f[5] == 0,
             "fade eases in and out", str(f.round(3)))

# lean: the crest stays put, the groove moves toward the steep side
p = shape(cs, ribs=8, rib_depth=4.0, rib_fullness=0.0, top_round=0)
for lean, side in ((0.0, 0), (0.5, -1), (-0.5, 1)):
    p.rib_lean = lean
    g = cs.candle_geometry(p, 2880, 50.0)
    r, th = g.r[0, :360], np.degrees(g.theta[:360])  # first rib: 0..45 deg
    groove = th[np.argmin(r)]
    ok = th[np.argmax(r)] == 0.0 and np.sign(round(groove - 22.5, 3)) == side and abs(r.max() - r.min() - 4) < 1e-3
    fails.expect(ok, f"Rib Lean {lean:+.1f}: crest stays, groove at {groove:.1f} deg")

# twist focus: same total twist, front- or back-loaded
for focus, half in ((0.8, 0.835), (0.0, 0.5), (-0.8, 0.165)):
    prog = cs._twist_progress(shape(cs, twist_focus=focus), np.array([0.0, 0.5, 1.0]))
    fails.expect(np.allclose(prog, [0.0, half, 1.0], atol=1e-3), f"Twist Focus {focus:+.1f}", str(prog.round(3)))

# fast-turning leaning ribs get extra rings; plain designs keep even spacing
g = cs.candle_geometry(shape(cs, "SWIRL_FADE"), 320, 0.4)
dz = np.diff(g.z[:g.n_body])
fails.expect(dz.min() < 0.25 and dz.max() <= 0.4 + 1e-9, "rings bunch up where the swirl turns fastest",
             f"{dz.min():.2f}..{dz.max():.2f} mm")
g = cs.candle_geometry(shape(cs, "TIGHT_SPIRAL"), 320, 0.4)
fails.expect(np.ptp(np.diff(g.z[:g.n_body])) < 1e-9, "designs without lean keep even ring spacing")

# rigid (unscrew) mold: uneven twist and faded ribs can't unscrew
cases = {"SWIRL_FADE": {"uneven twist", "rib fade"}, "RIBBED_SPIRAL": set(),
         "WAVE_FINS": {"sway"}}
for key, issues in cases.items():
    got = set(cs.rigid_mold_check(shape(cs, key)))
    fails.expect(got == issues, f"rigid check for {key}", str(sorted(got)))
fails.expect(cs.rigid_mold_check(shape(cs, ribs=8, fade_bottom=30)) == [],
             "a faded bottom still pulls straight out of a rigid mold")

# the new presets make clean molds of every kind
for key in ("SWIRL_FADE", "DRAPED_S", "WAVE_FINS"):
    p, m = shape(cs, key), mold(cs)
    g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
    check_mesh(fails, cs.build_candle(g), f"{key}/candle")
    for mt in ("SILICONE", "RIGID", "FLEX", "SPLIT", "WEDGE"):
        m.mold_type = mt
        for suffix, mesh in cs.mold_parts(p, m, g, 0.0 if mt == "SPLIT" else None):
            if suffix != "screws_x4":
                check_mesh(fails, mesh, f"{key}/{suffix}")
fails.finish()
