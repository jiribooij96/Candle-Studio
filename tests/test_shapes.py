"""Starting shapes: exact sizes, straight flat sides, evenly spaced ribs,
release of the plain shapes, and every mold for every shape with a mix of
patterns. Run with run_tests.py."""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from helpers import Failures, check_mesh, load_addon, mold, shape  # noqa: E402

fails = Failures()
cs = load_addon()


def widths(xy):
    """Narrowest and widest caliper width of an outline."""
    a = np.linspace(0.0, math.pi, 1800, endpoint=False)
    proj = xy @ np.stack([np.cos(a), np.sin(a)])
    w = proj.max(0) - proj.min(0)
    return w.min(), w.max()


# Width is the narrow size of every shape; oval and rectangle are Length Ratio x longer
for name in cs.BASE_SHAPES:
    for corner in (0.5, 4.0, 15.0):
        p = shape(cs, base_shape=name, corner_round=corner, ribs=0)
        xy = cs.candle_geometry(p, 720, 5.0).rings[0, :, :2]
        lo, hi = widths(xy)
        ok = abs(lo - p.diameter) < 0.05
        if name in cs.STRETCHED:
            ok &= abs(np.ptp(xy[:, 0]) - p.shape_stretch * p.diameter) < 0.05
        fails.expect(ok, f"{name} (corner {corner} mm) is {p.diameter:.0f} mm wide",
                     f"{lo:.2f} x {hi:.2f} mm")

# flat sides stay straight, also through the rounded top edge
p = shape(cs, base_shape="SQUARE", ribs=0)
g = cs.candle_geometry(p, 720, 1.0)
spread = []
for i in (0, g.n_body - 1, len(g.z) - 2, len(g.z) - 1):
    xy = g.rings[i, :, :2]
    side = (np.abs(xy[:, 1]) < 0.3 * np.ptp(xy[:, 1])) & (xy[:, 0] > 0)
    spread.append(np.ptp(xy[side, 0]))
fails.expect(max(spread) < 1e-9, "square sides are straight up to the top", f"{max(spread):.1e} mm")

# ribs: evenly spaced along the outline, grooves the same depth everywhere
p = shape(cs, base_shape="SQUARE", ribs=8, rib_depth=3.0, rib_fullness=0.0)
g = cs.candle_geometry(p, 2880, 5.0)
r = g.r[0]
peaks = np.degrees(g.theta[(r > np.roll(r, 1)) & (r >= np.roll(r, -1))])
fails.expect(np.allclose(peaks, np.arange(0, 360, 45), atol=0.2), "8 ribs on a square sit every 45 deg",
             str(peaks.round(1)))
r0 = cs.candle_geometry(shape(cs, base_shape="SQUARE", ribs=0), 2880, 5.0).r[0]
fails.expect(abs((r0 - r).max() - 3.0) < 1e-3, "grooves are Rib Depth deep", f"{(r0 - r).max():.4f} mm")

# twist turns the whole shape
p = shape(cs, base_shape="SQUARE", ribs=0, twist_turns=0.125, top_round=0.0)
g = cs.candle_geometry(p, 720, 5.0)
fails.expect(abs(g.r[-1, 90] - g.r[0, 0]) < 1e-6, "an 1/8 turn twist puts the top's flat side at 45 deg")

# round designs ignore the new settings
p = shape(cs, "CLASSIC_SWIRL")
q = shape(cs, "CLASSIC_SWIRL", corner_round=20.0, shape_stretch=2.5)
fails.expect(np.array_equal(cs.candle_geometry(p, 180, 1.0).rings, cs.candle_geometry(q, 180, 1.0).rings),
             "Corner Round and Length Ratio don't touch a round candle")

# every plain shape releases from a two-part mold (triangle/pentagon on a mirror line)
for name in cs.BASE_SHAPES:
    angle, trapped = cs.best_split(shape(cs, base_shape=name, ribs=0))
    fails.expect(trapped <= cs.LOCK_TOL, f"plain {name} releases", f"seam {angle:.0f} deg, {trapped:.2f} mm")

# all molds for all shapes, with a spread of patterns
CONFIGS = {
    "default ribs": {},
    "ribbed twist": dict(ribs=10, rib_depth=3, rib_fullness=0.3, twist_turns=0.6),
    "sway and wave": dict(ribs=6, rib_depth=4, rib_fullness=0.5, sway_angle=20, sway_waves=1.5,
                          sway_stagger=1, wave_amount=6, wave_count=1.2),
    "bubble cone": dict(bulge_mode="BUBBLE", bulge_amount=0.35, bulge_count=3, bulge_phase=60,
                        top_scale=0.5, top_round=4),
    "sharp fluted": dict(corner_round=0.5, ribs=16, rib_depth=2, rib_fullness=-0.6, twist_turns=-0.3,
                         top_round=6),
    "rope corkscrew": dict(ribs=3, rib_depth=9, rib_fullness=0.75, twist_turns=1.5,
                           wave_mode="HELIX", wave_amount=4, wave_count=1.5),
    "faded folds": dict(ribs=9, rib_depth=6, rib_fullness=-0.3, rib_lean=0.6, twist_turns=0.8,
                        twist_focus=0.9, fade_bottom=15, fade_top=40),
}
t0 = time.time()
for name in cs.BASE_SHAPES:
    if name == "ROUND":
        continue  # covered by the presets in the other tests
    for label, over in CONFIGS.items():
        p = shape(cs, base_shape=name, **over)
        m = mold(cs)
        g = cs.candle_geometry(p, 180, 0.8, m.wick_diameter)
        check_mesh(fails, cs.build_candle(g), f"{name}/{label}/candle")
        for mt in ("SILICONE", "RIGID", "FLEX", "SPLIT"):
            m.mold_type = mt
            for suffix, mesh in cs.mold_parts(p, m, g, 0.0 if mt == "SPLIT" else None):
                if suffix != "screws_x4":
                    check_mesh(fails, mesh, f"{name}/{label}/{suffix}")
print(f"shape matrix: {time.time() - t0:.0f} s")
fails.finish()
