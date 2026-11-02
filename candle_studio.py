"""
Candle Studio - parametric swirl / wave pillar candles (round, oval, square,
rectangle or polygon base) for Blender,
plus 3D-printable molds you can send straight to Bambu Studio.

Install:  Edit > Preferences > Add-ons > (v) menu > Install from Disk... > this file
     or:  open this file in Blender's Text Editor and press Run Script.
Use:      3D Viewport > press N > "Candle" tab.

All dimensions are millimetres. Exported STL files are in mm, oriented for
printing, and watertight: every solid is built as a closed surface (only the
two-part halves and the wedges are cut with Blender's boolean), so Bambu
Studio has nothing to repair.
"""

bl_info = {
    "name": "Candle Studio",
    "version": (1, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N) > Candle",
    "description": "Design swirl / wave pillar candles and export printable molds for Bambu Studio",
    "category": "Add Mesh",
}

import json
import math
import os
import random
import struct
import subprocess
import sys
from types import SimpleNamespace

import numpy as np

import bmesh
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy_extras.io_utils import ImportHelper

TAU = 2.0 * math.pi


def _hex(h):
    """sRGB hex -> linear RGB (what Blender colour properties store)."""
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


PALETTE = {
    "ivory": _hex("F3EBD8"), "cream": _hex("F1E1BE"), "sage": _hex("9AAA8A"),
    "forest": _hex("4F6B55"), "blush": _hex("DDA096"), "rose": _hex("C9737A"),
    "lavender": _hex("B9A7CC"), "peach": _hex("F2A98C"), "blue": _hex("8FA3BF"),
    "mustard": _hex("E2B04A"), "sand": _hex("E8C9A0"),
}

# ---------------------------------------------------------------------------
# Design parameters
# ---------------------------------------------------------------------------

# (label, description, sides); 0 sides = curved outline
BASE_SHAPES = {
    "ROUND": ("Round", "Circular cross-section", 0),
    "OVAL": ("Oval", "Ellipse: Width across the narrow side, Length Ratio sets how long", 0),
    "SQUARE": ("Square", "Width = side length", 4),
    "RECTANGLE": ("Rectangle", "Width = short side, Length Ratio sets the long side", 4),
    "TRIANGLE": ("Triangle", "Width = from a flat side to the opposite corner", 3),
    "PENTAGON": ("Pentagon", "Width = from a flat side to the opposite corner", 5),
    "HEXAGON": ("Hexagon", "Width = across the flat sides", 6),
    "OCTAGON": ("Octagon", "Width = across the flat sides", 8),
}
STRETCHED = ("OVAL", "RECTANGLE")

SHAPE_DEFAULTS = dict(
    base_shape="ROUND", shape_stretch=1.5, corner_round=4.0,
    height=150.0, diameter=60.0, top_scale=1.0, taper_power=1.0, top_round=2.5,
    ribs=8, rib_depth=4.0, rib_fullness=0.3, rib_lean=0.0, fade_bottom=0.0, fade_top=0.0,
    twist_turns=0.0, twist_focus=0.0,
    sway_angle=0.0, sway_waves=1.5, sway_phase=0.0, sway_stagger=0,
    wave_mode="PLANAR", wave_amount=0.0, wave_count=1.0, wave_phase=0.0, wave_direction=0.0,
    bulge_mode="SINE", bulge_amount=0.0, bulge_count=2.0, bulge_phase=0.0,
    color=PALETTE["ivory"],
)

MOLD_DEFAULTS = dict(
    mold_type="SILICONE", wick_diameter=2.5,
    sil_wall=8.0, sil_top=6.0, sleeve_wall=2.0, fit_clearance=0.3,
    plate_thickness=3.0, step_height=4.0,
    mold_wall=4.0, mold_floor=3.0, flex_wall=1.8, flange_width=8.0, flange_thickness=2.0,
    split_wall=5.0, split_floor=4.0, fastener="PRINTED", split_auto=True, split_angle=0.0,
    wedge_auto=True, wedge_count=4, infill=15,
)

# (label, description, overrides of SHAPE_DEFAULTS)
PRESETS = {
    "DEFAULT": ("Defaults", "Start fresh: every shape and mold setting back to its default", {}),
    "CLASSIC_SWIRL": ("Classic Swirl", "Rounded ribs that sway left and right",
                      dict(ribs=7, rib_depth=4.5, rib_fullness=0.45, twist_turns=0.1,
                           sway_angle=26, sway_waves=1.25, sway_phase=-30)),
    "RIBBED_SPIRAL": ("Ribbed Spiral", "Many fine ribs in a slow spiral",
                      dict(ribs=12, rib_depth=3.0, rib_fullness=0.25, twist_turns=0.6,
                           color=PALETTE["cream"])),
    "ROPE_TWIST": ("Rope Twist", "Three fat strands twisted like rope",
                   dict(diameter=55, ribs=3, rib_depth=9, rib_fullness=0.75, twist_turns=1.6,
                        color=PALETTE["rose"])),
    "DOUBLE_TWIST": ("Double Twist", "Two deep strands, tightly twisted",
                     dict(diameter=55, ribs=2, rib_depth=11, rib_fullness=0.6, twist_turns=1.3,
                          color=PALETTE["peach"])),
    "TIGHT_SPIRAL": ("Tight Spiral", "Slim candle with a fast spiral",
                     dict(height=160, diameter=45, ribs=6, rib_depth=4, rib_fullness=0.4,
                          twist_turns=2.4, color=PALETTE["sage"])),
    "WIDE_TWIST": ("Wide Twist", "Four broad soft lobes, one slow turn",
                   dict(ribs=4, rib_depth=6, rib_fullness=0.1, twist_turns=0.65,
                        color=PALETTE["lavender"])),
    "FLUTED": ("Fluted Column", "Concave flutes with narrow ridges",
               dict(ribs=14, rib_depth=2.5, rib_fullness=-0.6, twist_turns=0.35,
                    color=PALETTE["sand"])),
    "SPIRAL_TAPER": ("Spiral Taper", "Cone-shaped spiral",
                     dict(height=160, diameter=65, ribs=5, rib_depth=5, rib_fullness=0.4,
                          twist_turns=2.2, top_scale=0.3, top_round=1.5,
                          color=PALETTE["lavender"])),
    "PETAL": ("Petal Pillar", "Flower-shaped cross-section, straight",
              dict(ribs=6, rib_depth=7, rib_fullness=0.85, twist_turns=0.0, color=PALETTE["blush"])),
    "SOFT_WAVES": ("Soft Waves", "Wavy silhouette with flowing ribs",
                   dict(ribs=6, rib_depth=5, rib_fullness=0.4, sway_angle=14, sway_waves=2.5,
                        wave_amount=4.5, wave_count=2.5, color=PALETTE["peach"])),
    "S_CURVE": ("S-Curve", "The whole candle bends in an S",
                dict(ribs=8, rib_depth=3.5, rib_fullness=0.35, sway_angle=10, sway_waves=1,
                     wave_amount=9, wave_count=1, color=PALETTE["blush"])),
    "FLOWING_RIDGES": ("Flowing Ridges", "Ridges that wiggle many times",
                       dict(ribs=9, rib_depth=4, rib_fullness=0.2, sway_angle=13, sway_waves=4,
                            wave_amount=2.5, wave_count=4, color=PALETTE["rose"])),
    "ORGANIC": ("Organic Waves", "Ribs drift out of sync for a hand-made look",
                dict(ribs=6, rib_depth=6, rib_fullness=0.5, sway_angle=24, sway_waves=1.8,
                     sway_stagger=1, wave_amount=4, wave_count=1.5, bulge_amount=0.06,
                     bulge_count=1.5, color=PALETTE["sage"])),
    "BUBBLE_STACK": ("Bubble Stack", "Stacked round bubbles",
                     dict(ribs=0, bulge_mode="BUBBLE", bulge_amount=0.42, bulge_count=3.6,
                          bulge_phase=70, top_round=3, color=PALETTE["blue"])),
    "RIPPLED": ("Rippled Wave", "Fine ribs over gentle bulges",
                dict(ribs=10, rib_depth=2.5, rib_fullness=0.3, sway_angle=10, sway_waves=4,
                     bulge_amount=0.08, bulge_count=4, bulge_phase=90, color=PALETTE["rose"])),
    "CURVED_SPIRAL": ("Curved Spiral", "Corkscrew: twist plus a helical wave",
                      dict(diameter=50, ribs=2, rib_depth=10, rib_fullness=0.7, twist_turns=2,
                           wave_mode="HELIX", wave_amount=5, wave_count=2,
                           color=PALETTE["mustard"])),
    "CURVY": ("Curvy Form", "Smooth body with soft curves",
              dict(ribs=0, bulge_amount=0.12, bulge_count=1.5, bulge_phase=0, wave_amount=5,
                   wave_count=1, color=PALETTE["sage"])),
    "TWISTED_SQUARE": ("Twisted Square", "Square pillar with a half turn of twist",
                       dict(base_shape="SQUARE", corner_round=5, diameter=55, ribs=0,
                            twist_turns=0.5, color=PALETTE["cream"])),
    "TWISTED_HEX": ("Twisted Hexagon", "Hexagonal pillar, gently twisted",
                    dict(base_shape="HEXAGON", corner_round=3, ribs=0, twist_turns=0.35,
                         color=PALETTE["blue"])),
    "TWISTED_TRIANGLE": ("Twisted Triangle", "Soft triangle that spirals up",
                         dict(base_shape="TRIANGLE", corner_round=9, diameter=55, ribs=0,
                              twist_turns=0.6, color=PALETTE["mustard"])),
    "RIBBED_OVAL": ("Ribbed Oval", "Oval with fine straight ribs",
                    dict(base_shape="OVAL", shape_stretch=1.5, diameter=50, ribs=18, rib_depth=2,
                         rib_fullness=0.2, color=PALETTE["sand"])),
    "SQUARE_CUSHIONS": ("Square Cushions", "Stacked square pillows",
                        dict(base_shape="SQUARE", corner_round=12, ribs=0, bulge_mode="BUBBLE",
                             bulge_amount=0.2, bulge_count=3.6, bulge_phase=70, top_round=4,
                             color=PALETTE["blush"])),
    "SWIRL_FADE": ("Swirl Fade", "Folds swirling tight at the bottom, fading into a smooth top",
                   dict(height=93, ribs=8, rib_depth=7, rib_fullness=-0.3, rib_lean=0.5,
                        twist_turns=0.75, twist_focus=0.8, fade_top=50, top_round=2,
                        color=PALETTE["peach"])),
    "DRAPED_S": ("Draped S-Curve", "Leaning folds flowing over an S-bend",
                 dict(height=142, diameter=63, ribs=11, rib_depth=5.5, rib_fullness=-0.3, rib_lean=0.55,
                      sway_angle=22, sway_waves=1.25, wave_amount=6, wave_count=1, top_round=1.5,
                      color=PALETTE["peach"])),
    "WAVE_FINS": ("Wave Fins", "Short pillar of leaning fins with one wave",
                  dict(height=61, diameter=66, ribs=14, rib_depth=4.5, rib_fullness=-0.4, rib_lean=0.5,
                       sway_angle=16, sway_waves=1.0, top_round=1.0, color=PALETTE["blush"])),
}

QUALITY = {  # segments around, ring spacing (mm)
    "DRAFT": (180, 0.8),
    "FINE": (320, 0.4),
    "ULTRA": (480, 0.25),
}

# ---------------------------------------------------------------------------
# Candle surface
#
# The candle is a stack of horizontal slices. Each slice is star-shaped around
# its own centre: radius(theta, z) = overall radius x (base shape - rib grooves).
# Because of that, every mesh below is a set of rings with the same vertex
# count, joined by quads - always a clean, closed, non-self-intersecting surface.
# ---------------------------------------------------------------------------


def _norm_height(p, z):
    return np.clip(np.asarray(z, float) / p.height, 0.0, 1.0)


def _rounded_polygon(normals, dist, rc, n_pts=2048):
    """Dense counter-clockwise outline of a convex polygon (outward normal
    angles in increasing order, distances of the sides from the centre) with
    its corners rounded to radius rc."""
    nrm = np.column_stack([np.cos(normals), np.sin(normals)])
    d = np.asarray(dist, float) - rc
    nxt = np.roll(np.arange(len(d)), -1)
    A = np.stack([nrm, nrm[nxt]], 1)
    corner = np.linalg.solve(A, np.stack([d, d[nxt]], 1)[..., None])[..., 0]  # side j meets j+1
    sweep = np.mod(normals[nxt] - normals, TAU)
    sides = [(corner[j - 1] + rc * nrm[j], corner[j] + rc * nrm[j]) for j in range(len(d))]
    density = n_pts / (sum(np.linalg.norm(b - a) for a, b in sides) + rc * TAU)
    pts = []
    for j, (a, b) in enumerate(sides):
        k = max(2, int(math.ceil(np.linalg.norm(b - a) * density)))
        pts.append(a + np.linspace(0.0, 1.0, k, endpoint=False)[:, None] * (b - a))
        k = max(1, int(math.ceil(rc * sweep[j] * density)))
        ang = normals[j] + np.linspace(0.0, sweep[j], k, endpoint=False)
        pts.append(corner[j] + rc * np.column_stack([np.cos(ang), np.sin(ang)]))
    return np.vstack(pts)


def base_outline(p, offset=0.0):
    """The plain cross-section in units of half the Width: outline points
    sorted by angle (0..2pi, starting and ending on the +x axis), their angles,
    and the fraction of the way round the outline at each, so ribs can be
    spaced evenly along it. `offset` moves the outline inwards along its
    normal (flat sides stay flat)."""
    shape = p.base_shape
    k = p.shape_stretch if shape in STRETCHED else 1.0
    rc = p.corner_round / (0.5 * p.diameter)
    if shape in ("ROUND", "OVAL"):
        u = np.linspace(0.0, TAU, 4096, endpoint=False)
        nrm = np.column_stack([np.cos(u) / k, np.sin(u)])
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        pts = np.column_stack([k * np.cos(u), np.sin(u)]) - offset * nrm
    else:
        n = BASE_SHAPES[shape][2]
        normals = TAU * np.arange(n) / n  # a flat side faces +x
        if shape == "RECTANGLE":
            dist = np.array([k, 1.0, k, 1.0])
        elif n % 2 == 0:
            dist = np.ones(n)
        else:  # odd: Width runs from a flat to the opposite (rounded) corner
            c = math.cos(math.pi / n)
            rc = min(rc, 0.9 * 2.0 / (1.0 + 1.0 / c))
            dist = np.full(n, (2.0 + rc * (1.0 / c - 1.0)) / (1.0 + 1.0 / c))
        rc = min(rc, 0.95 * dist.min())
        pts = _rounded_polygon(normals, dist - offset, max(rc - offset, 1e-4), n_pts=4096)
    pts = pts[np.argsort(np.mod(np.arctan2(pts[:, 1], pts[:, 0]), TAU), kind="stable")]
    a, b = pts[-1], pts[0]  # these straddle the +x axis: start and end exactly on it
    x0 = a + a[1] / (a[1] - b[1]) * (b - a)
    pts = np.vstack([x0, pts, x0])
    ang = np.mod(np.arctan2(pts[:, 1], pts[:, 0]), TAU)
    ang[0], ang[-1] = 0.0, TAU
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return ang, pts, arc / arc[-1]


def _outline_radius_at(ang, pts, rel):
    """Where rays at angles `rel` leave the sampled outline. An exact ray /
    chord hit, so straight sides come out perfectly straight."""
    k = np.clip(np.searchsorted(ang, rel, side="right") - 1, 0, len(ang) - 2)
    p0, p1 = pts[k], pts[k + 1]
    den = np.cos(rel) * (p1[..., 1] - p0[..., 1]) - np.sin(rel) * (p1[..., 0] - p0[..., 0])
    num = p0[..., 0] * p1[..., 1] - p0[..., 1] * p1[..., 0]
    ok = np.abs(den) > 1e-12
    return np.where(ok, num / np.where(ok, den, 1.0), np.hypot(p0[..., 0], p0[..., 1]))


def _shape_fold(p):
    """How many times the plain cross-section repeats in one turn (0 = round)."""
    if p.base_shape == "ROUND":
        return 0
    return 2 if p.base_shape in STRETCHED else BASE_SHAPES[p.base_shape][2]


def _outline_radius(p, t):
    """Half the Width at normalised height t (taper + bulges)."""
    R = 0.5 * p.diameter * (1.0 + (p.top_scale - 1.0) * t ** p.taper_power)
    if p.bulge_amount > 0:
        ph = math.radians(p.bulge_phase)
        if p.bulge_mode == "BUBBLE":
            m = np.abs(np.sin(math.pi * p.bulge_count * t + ph))
            R = R * (1.0 - p.bulge_amount + p.bulge_amount * np.sqrt(m))
        else:
            R = R * (1.0 + p.bulge_amount * np.sin(TAU * p.bulge_count * t + ph))
    return R


def _twist_progress(p, t):
    """Share of the twist done at normalised height t: even, or tighter
    toward the bottom (focus > 0) or the top (focus < 0)."""
    k = 1.0 + 2.0 * abs(p.twist_focus)
    if p.twist_focus > 0:
        return 1.0 - (1.0 - t) ** k
    if p.twist_focus < 0:
        return t ** k
    return t


def _rib_fade(p, t):
    """Rib depth factor: 1, easing to 0 over the faded bottom / top share of the height."""
    f = np.ones_like(t)
    for share, x in ((p.fade_bottom, t), (p.fade_top, 1.0 - t)):
        if share > 0:
            x = np.clip(x / (0.01 * share), 0.0, 1.0)
            f = f * x * x * (3.0 - 2.0 * x)
    return f


def radius_field(p, z, theta, inset=None):
    """Surface radius, shape (len(z), len(theta)). `inset` (mm per z) pulls
    the outline in, for the rounded top edge."""
    t = _norm_height(p, z)[:, None]
    th = np.asarray(theta, float)[None, :]
    shape = (t.shape[0], th.shape[1])
    R = _outline_radius(p, t)
    ribs = p.ribs > 0 and p.rib_depth > 0
    if not ribs and p.base_shape == "ROUND":
        r = np.broadcast_to(R, shape).copy()
        return r if inset is None else r - inset[:, None]
    phase = TAU * p.twist_turns * _twist_progress(p, t)  # twist and sway turn the whole cross-section
    if p.sway_angle:
        phase = phase + math.radians(p.sway_angle) * np.sin(
            TAU * p.sway_waves * t + math.radians(p.sway_phase) + p.sway_stagger * th)
    rel = np.broadcast_to(th - phase, shape)
    if p.base_shape == "ROUND":
        rho, around, rho_min = 1.0, rel / TAU, 1.0
    else:
        ang, pts, arc = base_outline(p)
        rel = np.mod(rel, TAU)
        rho, around = _outline_radius_at(ang, pts, rel), np.interp(rel, ang, arc)
        rho_min = np.hypot(pts[:, 0], pts[:, 1]).min()
        if inset is not None:  # offset the outline itself, so flat sides stay flat
            for i in np.flatnonzero(inset > 0):
                ang_i, pts_i, _ = base_outline(p, inset[i] / R[i, 0])
                rho[i] = _outline_radius_at(ang_i, pts_i, rel[i])
            inset = None
    if ribs:
        if p.rib_lean:  # leaning ribs: one steep side, one gentle side, smooth all round
            e = np.exp(1j * TAU * p.ribs * around)
            b = 1j * p.rib_lean  # a disc automorphism bunches each cycle up on one side
            w = (e - b) / (1.0 + b * e) * (1.0 + b) / (1.0 - b)  # (keeps the crest in place)
            s = np.clip(0.5 + 0.5 * w.real, 0.0, 1.0)
        else:
            s = np.clip(0.5 + 0.5 * np.cos(TAU * p.ribs * around), 0.0, 1.0)
        profile = s ** (2.0 ** (-2.0 * p.rib_fullness))  # fullness>0: fat lobes, <0: thin ridges
        depth = min(p.rib_depth / (0.5 * p.diameter), 0.9 * rho_min)
        if p.fade_bottom > 0 or p.fade_top > 0:
            depth = depth * _rib_fade(p, t)
        r = R * (rho - depth * (1.0 - profile))
    else:
        r = np.broadcast_to(R * rho, shape).copy()
    return r if inset is None else r - inset[:, None]


def wave_center(p, z):
    """Sideways offset of each slice, shape (len(z), 2). Zero at the base."""
    t = _norm_height(p, z)
    if p.wave_amount <= 0:
        return np.zeros((len(t), 2))
    ph = math.radians(p.wave_phase)
    w = TAU * p.wave_count * t + ph
    if p.wave_mode == "HELIX":
        x = p.wave_amount * (np.cos(w) - math.cos(ph))
        y = p.wave_amount * (np.sin(w) - math.sin(ph))
    else:
        s = p.wave_amount * (np.sin(w) - math.sin(ph))
        a = math.radians(p.wave_direction)
        x, y = s * math.cos(a), s * math.sin(a)
    return np.column_stack([x, y])


def _body_heights(p, top, step, segs):
    """Ring heights from 0 to `top`: every `step` mm, but closer together where
    leaning ribs turn quickly, so their steep sides don't zig-zag between rings
    (the pattern turns at most one segment from one ring to the next)."""
    zs = np.linspace(0.0, top, 2001)
    speed = np.abs(np.gradient(TAU * p.twist_turns * _twist_progress(p, zs / p.height), zs))
    if p.sway_angle:
        speed = speed + math.radians(p.sway_angle) * TAU * p.sway_waves / p.height
    density = np.maximum(1.0 / step, speed * segs / TAU)  # rings per mm
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (density[1:] + density[:-1]) * np.diff(zs))])
    return np.interp(np.linspace(0.0, cdf[-1], max(2, int(math.ceil(cdf[-1])) + 1)), cdf, zs)


def candle_geometry(p, segs, step, wick_d=0.0):
    H = p.height
    theta = np.linspace(0.0, TAU, segs, endpoint=False)
    r_top = radius_field(p, [H], theta)[0]
    f = max(0.0, min(p.top_round, 0.25 * H, 0.45 * (r_top.min() - 0.5 * wick_d - 0.5)))
    if p.rib_lean and p.ribs > 0:
        z = _body_heights(p, H - f, step, segs)
    else:
        z = np.linspace(0.0, H - f, max(2, int(math.ceil((H - f) / step)) + 1))
    n_body = len(z)
    inset = np.zeros(n_body)
    if f > 1e-3:  # rounded top edge: quarter circle of radius f
        k = max(3, int(math.ceil(0.5 * math.pi * f / step)))
        a = np.linspace(0.0, 0.5 * math.pi, k + 1)[1:]
        z = np.concatenate([z, H - f + f * np.sin(a)])
        inset = np.concatenate([inset, f * (1.0 - np.cos(a))])
    r = np.maximum(radius_field(p, z, theta, inset), 0.3)
    centers = wave_center(p, z)
    dirs = np.column_stack([np.cos(theta), np.sin(theta)])
    xy = centers[:, None, :] + r[:, :, None] * dirs[None]
    rings = np.concatenate([xy, np.broadcast_to(z[:, None, None], (len(z), segs, 1))], axis=2)
    return SimpleNamespace(theta=theta, dirs=dirs, z=z, r=r, centers=centers, rings=rings,
                           n_body=n_body, H=H, f=f)


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------

class Mesh:
    def __init__(self, verts, quads, tris):
        self.verts = np.asarray(verts, float)
        self.quads = np.asarray(quads, np.int64).reshape(-1, 4)
        self.tris = np.asarray(tris, np.int64).reshape(-1, 3)

    def triangles(self):
        q = self.quads
        return np.vstack([self.tris, q[:, [0, 1, 2]], q[:, [0, 2, 3]]])

    def volume(self):
        v = self.verts[self.triangles()]
        return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0)

    def area(self):
        v = self.verts[self.triangles()]
        return float(np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum() / 2.0)


def loft(rings, closed=False, cap_start=None, cap_end=None):
    """Join rings (n, S, 3) with quads. Profile order must keep the solid on
    the left in the (radius, z) plane so normals face outwards. Caps are
    triangle fans to a centre point; closed=True joins last ring to first."""
    rings = np.asarray(rings, float)
    n, S, _ = rings.shape
    verts = [rings.reshape(-1, 3)]
    idx = np.arange(n * S).reshape(n, S)
    nxt = np.roll(idx, -1, axis=1)
    quads = [np.stack([idx[:-1], nxt[:-1], nxt[1:], idx[1:]], -1).reshape(-1, 4)]
    if closed:
        quads.append(np.stack([idx[-1], nxt[-1], nxt[0], idx[0]], -1))
    quads = np.vstack(quads)
    # Quads get split along their 0-2 diagonal (here and in Blender). Start each
    # quad so that diagonal joins the two corners at the most similar radius:
    # the split then follows ridges and cliffs that run slanted across the rings,
    # instead of cutting across them in a zig-zag.
    rad = np.linalg.norm(rings[..., :2] - rings[..., :2].mean(axis=1, keepdims=True), axis=-1).ravel()
    turn = np.abs(rad[quads[:, 0]] - rad[quads[:, 2]]) > np.abs(rad[quads[:, 1]] - rad[quads[:, 3]])
    quads[turn] = quads[turn][:, [1, 2, 3, 0]]
    tris = []
    count = n * S
    if cap_start is not None:
        verts.append(np.asarray(cap_start, float)[None])
        tris.append(np.stack([np.full(S, count), nxt[0], idx[0]], -1))
        count += 1
    if cap_end is not None:
        verts.append(np.asarray(cap_end, float)[None])
        tris.append(np.stack([np.full(S, count), idx[-1], nxt[-1]], -1))
    return Mesh(np.vstack(verts), quads, np.vstack(tris) if tris else np.zeros((0, 3), np.int64))


def _ring(xy, z):
    return np.column_stack([xy, np.full(len(xy), z)])


def circle_ring(origin, center, radius, theta, z):
    """Points where rays from `origin` (inside the circle) hit a circle."""
    d = np.column_stack([np.cos(theta), np.sin(theta)])
    oc = np.asarray(origin, float) - np.asarray(center, float)
    b = d @ oc
    s = -b + np.sqrt(np.maximum(b * b - (oc @ oc - radius * radius), 0.0))
    return _ring(np.asarray(origin, float) + s[:, None] * d, z)


def disc_ring(center, radius, theta, z):
    return circle_ring(center, center, radius, theta, z)


def bounding_circle(xy):
    xy = xy.reshape(-1, 2)
    c = 0.5 * (xy.min(0) + xy.max(0))
    return c, float(np.sqrt(((xy - c) ** 2).sum(1)).max())


def place_for_print(mesh, flip=False):
    """Optionally turn upside down (180 deg about X, keeps it un-mirrored),
    then centre in XY and drop onto z = 0."""
    v = mesh.verts.copy()
    if flip:
        v[:, 1] *= -1.0
        v[:, 2] *= -1.0
    lo, hi = v.min(0), v.max(0)
    v -= [0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), lo[2]]
    return Mesh(v, mesh.quads, mesh.tris)


def outward_offset(g, t, rows):
    """Radius (per ring centre and direction) of the candle surface grown by
    thickness t in 3D: the union of balls of radius t on the surface, which
    stays star-shaped. Used for the even-walled flexible mold."""
    P, z, C, d = g.rings, g.z, g.centers, g.dirs
    n, S, _ = P.shape
    rout = g.r[:rows] + t
    step = max(float(np.diff(z[:g.n_body]).min()), 1e-3)
    wi = int(min(n - 1, math.ceil(t / step) + 2))
    arc = TAU * max(float(g.r.min()), 1.0) / S
    wj = int(min(S // 4, 24, math.ceil(t / arc) + 2))
    for di in range(-wi, wi + 1):
        lo, hi = max(0, -di), min(rows, n - di)
        if lo >= hi:
            continue
        rho2 = t * t - (z[lo + di:hi + di] - z[lo:hi]) ** 2
        if rho2.max() <= 0:
            continue
        wx = P[lo + di:hi + di, :, 0] - C[lo:hi, None, 0]
        wy = P[lo + di:hi + di, :, 1] - C[lo:hi, None, 1]
        for dj in range(-wj, wj + 1):
            ax, ay = np.roll(wx, -dj, axis=1), np.roll(wy, -dj, axis=1)
            b = ax * d[None, :, 0] + ay * d[None, :, 1]
            h = rho2[:, None] - (ax * ax + ay * ay - b * b)
            s = np.where(h > 0, b + np.sqrt(np.maximum(h, 0.0)), -np.inf)
            np.maximum(rout[lo:hi], s, out=rout[lo:hi])
    return rout


# ---------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------

def build_candle(g):
    return loft(g.rings, cap_start=(*g.centers[0], 0.0), cap_end=(*g.centers[-1], g.H))


def build_silicone_kit(p, m, g):
    """Master (candle on a base plate with a wick pin) + pour sleeve.
    The sleeve slides over the plate's step; silicone fills the gap."""
    th, H = g.theta, g.H
    c, rmax = bounding_circle(g.rings[..., :2])
    Ri = rmax + m.sil_wall
    Rs = Ri - m.fit_clearance
    Rp = Ri + m.sleeve_wall + 4.0
    b0, tc = g.centers[0], g.centers[-1]
    z_step = -m.step_height
    z_bot = z_step - m.plate_thickness
    pin_top = H + m.sil_top + 3.0
    rings = [circle_ring(b0, c, Rp, th, z_bot), circle_ring(b0, c, Rp, th, z_step),
             circle_ring(b0, c, Rs, th, z_step), circle_ring(b0, c, Rs, th, 0.0)]
    rings += list(g.rings)
    rings += [disc_ring(tc, 0.5 * m.wick_diameter, th, H),
              disc_ring(tc, 0.5 * m.wick_diameter, th, pin_top)]
    master = loft(rings, cap_start=(*b0, z_bot), cap_end=(*tc, pin_top))

    Ro = Ri + m.sleeve_wall
    z_top = H + m.sil_top + 2.0
    sleeve = loft([disc_ring(c, Ro, th, z_step), disc_ring(c, Ro, th, z_top),
                   disc_ring(c, Ri, th, z_top), disc_ring(c, Ri, th, z_step)], closed=True)
    master.verts -= [c[0], c[1], z_bot]
    sleeve.verts -= [c[0], c[1], z_step]
    return master, sleeve, Ri


def build_rigid_mold(p, m, g):
    """Solid cylinder with the candle as cavity, open at the candle's base,
    wick hole through the floor. Built upright, flipped for printing."""
    th, H = g.theta, g.H
    c, rmax = bounding_circle(g.rings[..., :2])
    Rb = rmax + m.mold_wall
    Hf = H + m.mold_floor
    tc = g.centers[-1]
    zs = np.linspace(0.0, Hf, max(8, int(Hf / 4.0)))
    origins = wave_center(p, zs)
    rings = [g.rings[0]]
    rings += [circle_ring(o, c, Rb, th, zz) for o, zz in zip(origins, zs)]
    rings += [disc_ring(tc, 0.5 * m.wick_diameter, th, Hf),
              disc_ring(tc, 0.5 * m.wick_diameter, th, H)]
    rings += list(g.rings[:0:-1])
    return place_for_print(loft(rings, closed=True), flip=True)


def build_flex_mold(p, m, g):
    """Even-walled shell that follows the candle (print in TPU and peel off).
    Optional rim flange with a 45 degree underside so it prints support-free
    and lets the mold hang in a jar while you pour."""
    th, H, f, nb, dirs = g.theta, g.H, g.f, g.n_body, g.dirs
    t, tf = m.flex_wall, m.mold_floor
    wick_r = 0.5 * m.wick_diameter
    rout = outward_offset(g, t, nb)
    shell = g.centers[:nb, None, :] + rout[:, :, None] * dirs[None]
    rings = [g.rings[0]]
    start = 0
    if m.flange_width > 0:
        c, rmax = bounding_circle(shell)
        Rf = rmax + m.flange_width
        k = int(min(np.searchsorted(g.z[:nb], m.flange_thickness), nb - 2))
        rings += [circle_ring(g.centers[0], c, Rf, th, 0.0),
                  circle_ring(g.centers[k], c, Rf, th, g.z[k])]
        start = k + 1
        while start < nb - 1:  # 45 deg underside, row by row, never inside the shell
            o = g.centers[start]
            Rc = Rf - (g.z[start] - g.z[k])
            if Rc <= np.linalg.norm(o - c) + 1e-3:
                break
            cone = np.linalg.norm(circle_ring(o, c, Rc, th, 0.0)[:, :2] - o, axis=1)
            if (cone <= rout[start]).all():
                break
            rings.append(_ring(o + np.maximum(cone, rout[start])[:, None] * dirs, g.z[start]))
            start += 1
    rings += [_ring(shell[i], g.z[i]) for i in range(start, nb)]
    k = max(4, int(math.ceil(0.5 * math.pi * (f + t) / (g.z[1] - g.z[0]))))
    angles = np.linspace(0.0, 0.5 * math.pi, k + 1)[1:]
    if f > 1e-3:  # one ring level with the candle top
        angles = np.union1d(angles, [math.asin(f / (f + tf))])
    for a in angles:
        zz = H - f + (f + tf) * math.sin(a)
        rr = np.maximum(rout[-1] - (f + t) * (1.0 - math.cos(a)), wick_r + 1.0)
        if zz <= H + 1e-9:  # stay a wall outside the candle's rounded top edge
            j = int(np.clip(np.searchsorted(g.z, zz), 1, len(g.z) - 1))
            w = (zz - g.z[j - 1]) / max(g.z[j] - g.z[j - 1], 1e-9)
            rr = np.maximum(rr, (1.0 - w) * g.r[j - 1] + w * g.r[j] + t)
        o = wave_center(p, [min(zz, H)])[0]
        rings.append(_ring(o + rr[:, None] * dirs, zz))
    tc = g.centers[-1]
    rings += [disc_ring(tc, wick_r, th, H + tf), disc_ring(tc, wick_r, th, H)]
    rings += list(g.rings[:0:-1])
    return place_for_print(loft(rings, closed=True), flip=True)


def rigid_mold_check(p):
    """A one-piece rigid mold only releases if the candle can be unscrewed:
    constant twist, no sideways waves, no bulges, never wider higher up."""
    issues = []
    if p.sway_angle:
        issues.append("sway")
    if p.wave_amount > 0:
        issues.append("waves")
    if p.bulge_amount > 0:
        issues.append("bulges")
    if p.top_scale > 1.0:
        issues.append("wider top")
    turning = p.twist_turns and (p.ribs > 0 and p.rib_depth > 0 or p.base_shape != "ROUND")
    if turning and p.twist_focus:
        issues.append("uneven twist")
    if p.ribs > 0 and p.rib_depth > 0 and (p.fade_top > 0 or p.fade_bottom > 0 and p.twist_turns):
        issues.append("rib fade")
    return issues


# ---------------------------------------------------------------------------
# Release check (two-part and wedge molds)
#
# Each mold piece pulls straight out, away from the candle axis; the halves of
# the two-part mold are two pieces of 180 degrees. Within a slice, take lines
# parallel to a piece's pull: its plastic on a line starts at its seam, and any
# of it with candle further along the line is trapped. That trapped length is
# the undercut we report, and the candle surface it catches on is painted red.
# Only candle surface inside the piece that faces away from the pull can catch
# it, so only lines across those spots are traced. The lines are 0.1 mm apart
# and a hook has to span three of them: a sliver thinner than that, or a line
# that just grazes the tip of a rib, isn't a lock.
# ---------------------------------------------------------------------------

LOCK_TOL = 0.3  # mm of undercut that wax shrinkage and mold release can live with
PULL_LINE = 0.1  # mm between pull lines


def _pull_frame(xy, beta, half):
    """Slices xy (Z, S, 2) around the mold axis, seen from the piece whose
    middle points along beta (half = half its angle): position along (a) and
    across (w) its pull, the same for the next vertex, and the edges that face
    away from the pull inside this piece (the only ones that can hook it)."""
    u = np.array([math.cos(beta), math.sin(beta)])
    a, w = xy @ u, xy @ np.array([-u[1], u[0]])
    a1, w1 = np.roll(a, -1, -1), np.roll(w, -1, -1)
    sh, ch = math.sin(half), math.cos(half)
    inside = (a * sh > np.abs(w) * ch) | (a1 * sh > np.abs(w1) * ch)
    return a, w, a1, w1, (w1 < w) & inside


def _hooks(xy, beta, half):
    """For that piece: (rows, w of the first line, trapped mm per row and
    line, keeping only hooks at least 3 lines wide), in chunks of rows."""
    a, w, a1, w1, hook = _pull_frame(xy, beta, half)
    rows = np.flatnonzero(hook.any(1))
    deep = np.where(hook, a - np.abs(w) / math.tan(half), -np.inf)[rows].max(1)
    rows = rows[np.argsort(-deep)]  # likely-worst slices first, so a lock is found (and stops) early
    span = max(1.0, float(np.ptp(w)) / PULL_LINE)
    chunk = max(1, min(4, int(4e6 // (xy.shape[1] * span))))  # small arrays; a lock can stop early
    for i in range(0, len(rows), chunk):
        r = rows[i:i + chunk]
        lo = np.where(hook[r], np.minimum(w[r], w1[r]), np.inf).min()
        hi = np.where(hook[r], np.maximum(w[r], w1[r]), -np.inf).max()
        W = np.arange(math.floor(lo / PULL_LINE), math.ceil(hi / PULL_LINE) + 1) * PULL_LINE
        L = W[None, :, None]
        W0, W1 = w[r][:, None, :], w1[r][:, None, :]
        cross = (W0 <= L) != (W1 <= L)  # a vertex exactly on a line counts once
        s = np.where(cross, (L - W0) / np.where(cross, W1 - W0, 1.0), 0.0)
        ac = a[r][:, None, :] + s * (a1 - a)[r][:, None, :]
        sign = np.where(cross, np.sign(W1 - W0), 0.0)  # +1 leaving the candle, -1 entering
        a0 = (np.abs(W) / math.tan(half))[None, :, None]  # where the line enters the piece
        amax = np.where(cross, ac, -np.inf).max(-1)
        trap = np.maximum(amax - a0[..., 0], 0.0) - (sign * np.maximum(ac, a0)).sum(-1)
        trap = np.pad(np.where(np.isfinite(amax), trap, 0.0), ((0, 0), (1, 1)))
        yield r, W[0], np.minimum(np.minimum(trap[:, :-2], trap[:, 1:-1]), trap[:, 2:])


def pieces_trapped(xy, n, phi, stop=np.inf):
    """Worst trapped length (mm) of n equal pieces with seams at
    phi + k * 360/n deg (phi in radians). Stops early once it reaches `stop`."""
    half, worst = math.pi / n, 0.0
    for k in range(n):
        for _, _, trap in _hooks(xy, phi + (2 * k + 1) * half, half):
            worst = max(worst, float(trap.max()))
            if worst >= stop:
                return worst
    return worst


def _hook_mask(xy, n, phi, tol=LOCK_TOL):
    """Per vertex of slices xy: True on candle surface that hooks the piece it
    touches - both ends of every edge with a deep enough hook across it."""
    half = math.pi / n
    along = np.linspace(0.0, 1.0, 5)  # sample points across each edge
    out = np.zeros(xy.shape[:2], bool)
    for k in range(n):
        beta = phi + (2 * k + 1) * half
        _, w, _, w1, hook = _pull_frame(xy, beta, half)
        for rows, w0, trap in _hooks(xy, beta, half):
            ws = w[rows][..., None] + along * (w1 - w)[rows][..., None]
            j = np.clip(np.rint((ws - w0) / PULL_LINE).astype(int), 0, trap.shape[1] - 1)
            deep = np.take_along_axis(trap, j.reshape(len(rows), -1), 1).reshape(j.shape).max(-1) > tol
            edge = hook[rows] & deep
            out[rows] |= edge | np.roll(edge, 1, axis=1)
    return out


# ---------------------------------------------------------------------------
# Two-part rigid mold
#
# The halves meet on a flat seam through the candle axis and pull apart along
# +u / -u.
# ---------------------------------------------------------------------------

SCREW = dict(major=8.0, pitch=2.5, depth=1.2, clearance=0.35, head_d=14.0, head_h=5.0)
PIN_R, PIN_LEN = 3.0, 4.0


def split_trapped(rings_xy, phi, stop=np.inf):
    """Worst trapped length (mm) over all slices for a seam at angle phi (the
    halves pull along phi and phi + 180 deg)."""
    return pieces_trapped(rings_xy, 2, phi - 0.5 * math.pi, stop)


def best_split(p, step_deg=5.0):
    """(seam angle in degrees, worst trapped mm) - the angle that traps least."""
    xy = candle_geometry(p, 96, 2.0).rings[..., :2]
    period = 180.0
    fold = _shape_fold(p)
    if p.wave_amount <= 0:
        if fold == 0 and p.ribs <= 0:
            period = step_deg  # round slices: every angle is the same
        elif fold == 0 and p.sway_stagger % p.ribs == 0:
            period = min(180.0, 360.0 / p.ribs)
        elif fold and not (p.sway_angle and p.sway_stagger):
            period = min(180.0, 360.0 / (math.gcd(fold, p.ribs) if p.ribs > 0 else fold))
    turned = abs(p.twist_turns) * 360.0 + 2.0 * p.sway_angle >= period  # every seam angle occurs
    coarse = np.arange(0.0, period, period / 6.0 if turned else step_deg)
    if fold:  # straight-sided shapes release only within ~0.5 deg of a mirror line
        coarse = np.concatenate([np.arange(0.0, 180.0, 90.0 / fold), coarse])

    def least(angles):
        top, at = np.inf, float(angles[0])
        for d in angles:
            t = split_trapped(xy, math.radians(d), top)
            if t < top:
                top, at = t, float(d)
            if top == 0.0:
                break
        return at, top

    best, score = least(coarse)
    if score > 0.0 and not turned:
        best, score = least(best + np.concatenate([[0.0], np.arange(1.0 - step_deg, step_deg, 1.0)]))
    return best % 180.0, score


def lock_mask(g, phi, tol=LOCK_TOL):
    """Per ring vertex: True where the candle hooks into its mold half."""
    return _hook_mask(g.rings[..., :2], 2, phi - 0.5 * math.pi, tol)


def _rod(profile, segs=32):
    """Round rod along +z from (z, radius) pairs, capped at both ends."""
    th = np.linspace(0.0, TAU, segs, endpoint=False)
    rings = [disc_ring((0.0, 0.0), r, th, z) for z, r in profile]
    return loft(rings, cap_start=(0.0, 0.0, profile[0][0]), cap_end=(0.0, 0.0, profile[-1][0]))


def _along_x(mesh, y, z):
    """Turn a +z rod to point along +x (a rotation, so threads keep their hand)."""
    v = mesh.verts
    return Mesh(np.column_stack([v[:, 2], v[:, 1] + y, z - v[:, 0]]), mesh.quads, mesh.tris)


def _thread_rings(s0, s1, extra=0.0, segs=48, avoid=()):
    th = np.linspace(0.0, TAU, segs, endpoint=False)
    s = np.linspace(s0, s1, int(math.ceil((s1 - s0) / (SCREW["pitch"] / 10.0))) + 1)
    for a in avoid:  # a ring lying (almost) in a block face leaves slivers in the boolean
        near = np.abs(s - a) < 0.02
        s[near] = np.where(s[near] >= a, a + 0.02, a - 0.02)
    x = np.mod(s[:, None] / SCREW["pitch"] - th[None] / TAU, 1.0)
    r = 0.5 * SCREW["major"] + extra - SCREW["depth"] * np.abs(2.0 * x - 1.0)
    return s, r, th


def _rings_from(s, r, th):
    dirs = np.column_stack([np.cos(th), np.sin(th)])
    return [_ring(ri[:, None] * dirs, si) for si, ri in zip(s, r)]


def build_screw(thread_len, shank_len):
    """Printed screw, tip at z=0, head on top. The matching nut thread in half A
    comes from the same helix, so they always fit."""
    s, r, th = _thread_rings(0.0, thread_len)
    pitch, root = SCREW["pitch"], 0.5 * SCREW["major"] - SCREW["depth"]
    r_shank = 0.5 * SCREW["major"] - 0.15
    r = np.minimum(r, root - 0.6 + s[:, None])                      # lead-in at the tip
    fade = np.clip((s - (thread_len - pitch)) / pitch, 0.0, 1.0)[:, None]
    r = r * (1.0 - fade) + r_shank * fade                          # thread run-out
    top = thread_len + shank_len
    rh, hh = 0.5 * SCREW["head_d"], SCREW["head_h"]
    rings = _rings_from(s, r, th)
    rings += [disc_ring((0.0, 0.0), r_shank, th, top), disc_ring((0.0, 0.0), rh, th, top),
              disc_ring((0.0, 0.0), rh, th, top + hh - 1.0),
              disc_ring((0.0, 0.0), rh - 1.0, th, top + hh)]
    return loft(rings, cap_start=(0.0, 0.0, 0.0), cap_end=(0.0, 0.0, top + hh))


def _thread_cutter(s0, s1, avoid=()):
    s, r, th = _thread_rings(s0, s1, extra=SCREW["clearance"], avoid=avoid)
    return loft(_rings_from(s, r, th), cap_start=(0.0, 0.0, s0), cap_end=(0.0, 0.0, s1))


def _chamfer_box(x0, x1, y0, y1, z0, z1, c):
    def ring(inset, z):
        a0, a1, b0, b1 = x0 + inset, x1 - inset, y0 + inset, y1 - inset
        return _ring(np.array([(a0 + c, b0), (a1 - c, b0), (a1, b0 + c), (a1, b1 - c),
                               (a1 - c, b1), (a0 + c, b1), (a0, b1 - c), (a0, b0 + c)]), z)
    cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    return loft([ring(c, z0), ring(0.0, z0 + c), ring(0.0, z1 - c), ring(c, z1)],
                cap_start=(cx, cy, z0), cap_end=(cx, cy, z1))


def _merge(meshes):
    verts, quads, tris, n = [], [], [], 0
    for mesh in meshes:
        verts.append(mesh.verts)
        quads.append(mesh.quads + n)
        tris.append(mesh.tris + n)
        n += len(mesh.verts)
    return Mesh(np.vstack(verts), np.vstack(quads), np.vstack(tris))


def _flip_needles(bm):
    """Booleans can leave needle triangles (three corners almost in a line).
    Flip the long edge of each, where that's safe: the far corners aren't
    joined yet and the needle's middle corner lies between the edge's ends."""
    for _ in range(4):
        flipped = 0
        for f in [f for f in bm.faces if f.calc_area() < 1e-6]:
            if not f.is_valid:
                continue
            e = max(f.edges, key=lambda e: e.calc_length())
            if not e.is_manifold or any(len(lf.verts) != 3 for lf in e.link_faces):
                continue
            v1, v2 = e.verts
            a = next(v for v in f.verts if v not in e.verts)
            b = next(v for v in next(lf for lf in e.link_faces if lf != f).verts if v not in e.verts)
            if any(x.other_vert(a) == b for x in a.link_edges):
                continue
            d = v2.co - v1.co
            if 0.0 < (a.co - v1.co).dot(d) / d.length_squared < 1.0 \
                    and bmesh.utils.edge_rotate(e, True) is not None:
                flipped += 1
        if not flipped:
            return


def boolean_mesh(base, cut=(), add=()):
    """Blender boolean (Manifold solver when available) on our closed meshes."""
    temp_objs, temp_colls = [], []

    def make(mesh, name):  # split only bent quads, so every output polygon is flat
        v, q = mesh.verts, mesh.quads
        nrm = np.cross(v[q[:, 1]] - v[q[:, 0]], v[q[:, 2]] - v[q[:, 0]])
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        flat = np.abs(np.einsum("ij,ij->i", v[q[:, 3]] - v[q[:, 0]], nrm)) < 1e-6
        bent = q[~flat]
        faces = q[flat].tolist() + bent[:, [0, 1, 2]].tolist() + bent[:, [0, 2, 3]].tolist() \
            + mesh.tris.tolist()
        me = bpy.data.meshes.new(name)
        me.from_pydata(v.tolist(), [], faces)
        me.update()
        obj = bpy.data.objects.new(name, me)
        temp_objs.append(obj)
        return obj

    solvers = bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items.keys()
    target = make(base, "cs_tmp_base")
    bpy.context.scene.collection.objects.link(target)
    try:
        for op, meshes in (("DIFFERENCE", cut), ("UNION", add)):
            if not meshes:
                continue
            coll = bpy.data.collections.new("cs_tmp_" + op)
            temp_colls.append(coll)
            for i, mesh in enumerate(meshes):
                coll.objects.link(make(mesh, f"cs_tmp_{op}_{i}"))
            mod = target.modifiers.new(op, "BOOLEAN")
            mod.operation = op
            mod.solver = "MANIFOLD" if "MANIFOLD" in solvers else "EXACT"
            mod.operand_type = "COLLECTION"
            mod.collection = coll
        ev = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
        bm = bmesh.new()
        bm.from_mesh(ev.to_mesh())
        ev.to_mesh_clear()
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)  # seams where cutters cross
        bmesh.ops.dissolve_degenerate(bm, dist=1e-4, edges=bm.edges)
        bmesh.ops.triangulate(bm, faces=bm.faces, quad_method="BEAUTY", ngon_method="BEAUTY")
        _flip_needles(bm)
        verts = np.array([v.co[:] for v in bm.verts], float)
        bm.verts.index_update()
        tris = np.array([[v.index for v in f.verts] for f in bm.faces], np.int64)
        bm.free()
    finally:
        for obj in temp_objs:
            me = obj.data
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(me)
        for coll in temp_colls:
            bpy.data.collections.remove(coll)
    return Mesh(verts, np.zeros((0, 4)), tris)


def _split_layout(g, m, angle_deg):
    """The candle turned so the halves pull apart along x, and the block size:
    each half is D deep, 2 Wy wide (centred on yc) and Hb long."""
    phi = math.radians(angle_deg)
    cs, sn = math.cos(phi), math.sin(phi)

    def rot(xy):  # turn the candle so the pull direction becomes +x
        return np.stack([xy[..., 0] * cs + xy[..., 1] * sn, -xy[..., 0] * sn + xy[..., 1] * cs], -1)

    rings = g.rings.copy()
    rings[..., :2] = rot(rings[..., :2])
    x, y = rings[..., 0], rings[..., 1]
    zone = 16.0 if m.fastener != "NONE" else 12.0  # strip beside the cavity for pins/screws
    return SimpleNamespace(rings=rings, centers=rot(g.centers), Hb=g.H + m.split_floor,
                           D=max(x.max(), -x.min()) + m.split_wall, yc=0.5 * (y.min() + y.max()),
                           Wy=0.5 * (y.max() - y.min()) + m.split_wall + zone, zone=zone)


def build_split_mold(p, m, g, angle_deg):
    """Two halves + pins (+ screws). Built with the seam on x = 0 and the
    halves pulling apart along x, then laid on their backs, seam side up."""
    L = _split_layout(g, m, angle_deg)
    rings, centers, D, yc, Wy, Hb, zone = L.rings, L.centers, L.D, L.yc, L.Wy, L.Hb, L.zone
    H = g.H

    base = _ring(rings[0][:, :2], -1.0)  # cavity pokes through the pour face
    candle = loft([base] + list(rings), cap_start=(*centers[0], -1.0), cap_end=(*centers[-1], H))
    on_seam = np.abs(candle.verts[:, 0]) < 1e-6  # rounding left these a hair off the seam plane:
    candle.verts[on_seam, 0] = 0.0                # exactly on it is clean, nearly on it leaves slivers
    wr = 0.5 * m.wick_diameter
    tc = centers[-1]
    th = np.linspace(0.0, TAU, 32, endpoint=False)
    wick = loft([disc_ring(tc, wr, th, H - 1.0), disc_ring(tc, wr, th, Hb + 1.0)],
                cap_start=(*tc, H - 1.0), cap_end=(*tc, Hb + 1.0))

    cols = (yc - Wy + 0.5 * zone, yc + Wy - 0.5 * zone)
    cut_a, cut_b, add_b, extra = [candle, wick], [candle, wick], [], []
    for yy in cols:
        for zz in (0.38 * Hb, 0.62 * Hb):  # alignment pins on B, sockets in A
            add_b.append(_along_x(_rod([(-1.0, PIN_R), (PIN_LEN - 0.6, PIN_R),
                                        (PIN_LEN, PIN_R - 0.6)]), yy, zz))
            cut_a.append(_along_x(_rod([(-1.0, PIN_R + 0.25), (PIN_LEN + 0.6, PIN_R + 0.25)]), yy, zz))
        for zz in (9.0, Hb - 9.0):
            if m.fastener == "PRINTED":
                cut_a.append(_along_x(_thread_cutter(-1.0, D + 1.0, avoid=(0.0, D)), yy, zz))
                cut_b.append(_along_x(_rod([(-D - 1.0, 0.5 * SCREW["major"] + 0.45),
                                            (1.0, 0.5 * SCREW["major"] + 0.45)]), yy, zz))
            elif m.fastener == "M5":
                hole = _along_x(_rod([(-D - 1.0, 2.75), (D + 1.0, 2.75)]), yy, zz)
                cut_a += [hole, _along_x(_rod([(D - 4.5, 4.85), (D + 1.0, 4.85)], segs=6), yy, zz)]
                cut_b.append(hole)
    if m.fastener == "PRINTED":
        screw = place_for_print(build_screw(D - 1.0, D - 2.0), flip=True)  # head on the bed
        copies = []
        for i in range(4):
            c = Mesh(screw.verts + [i * (SCREW["head_d"] + 4.0), 0.0, 0.0], screw.quads, screw.tris)
            copies.append(c)
        extra.append(("screws_x4", place_for_print(_merge(copies))))

    box_a = _chamfer_box(0.0, D, yc - Wy, yc + Wy, 0.0, Hb, 1.5)
    box_b = _chamfer_box(-D, 0.0, yc - Wy, yc + Wy, 0.0, Hb, 1.5)
    half_a = boolean_mesh(box_a, cut=cut_a)
    half_b = boolean_mesh(box_b, cut=cut_b, add=add_b)
    va, vb = half_a.verts, half_b.verts
    half_a = Mesh(np.column_stack([va[:, 2], va[:, 1], -va[:, 0]]), half_a.quads, half_a.tris)
    half_b = Mesh(np.column_stack([-vb[:, 2], vb[:, 1], vb[:, 0]]), half_b.quads, half_b.tris)
    _stats["split_build"] = dict(depth=D, bolt=5 * int(2 * D // 5))
    return [("half_a", place_for_print(half_a)), ("half_b", place_for_print(half_b))] + extra


# ---------------------------------------------------------------------------
# Wedge mold
#
# A round sleeve cut into 3 to 6 equal wedges through the mold axis, plus a
# plug that carries the candle's top (with its rounded edge) and the wick hole.
# A tongue around the plug sits in a groove inside the wedges; rubber bands in
# the grooves outside hold everything together. Each wedge pulls straight out
# along its middle; the release check is the one above.
# ---------------------------------------------------------------------------

WEDGE_COUNTS = (3, 4, 5, 6)
PLUG_WALL, PLUG_FIT = 2.5, 0.25  # plug rim beyond the candle top; gap between plug and socket
TONGUE = (1.2, 1.6, 0.4)  # height, half-width at its base and at its top (45 deg flanks)
BAND_GROOVE = 1.5  # depth of the V-grooves for the rubber bands


def _plug_face(g):
    """Index of the first ring the plug carries: where the rounded top edge
    starts, or higher up while the candle is still getting wider (the plug has
    to lift straight off the top)."""
    i = len(g.z) - 1
    while i > g.n_body - 1 and np.all(g.r[i - 1] >= g.r[i] - 1e-9):
        i -= 1
    return i


def _wedge_slices(p):
    """Check slices around the mold axis; the plug carries the top."""
    g = candle_geometry(p, 96, 2.0)
    c, _ = bounding_circle(g.rings[..., :2])
    return g.rings[:_plug_face(g) + 1, :, :2] - c


def best_wedges(p, count=None):
    """(pieces, seam angle in degrees, worst trapped mm): the fewest pieces
    that release (or exactly `count`), with the seams where they trap least."""
    xy = _wedge_slices(p)
    fold = _shape_fold(p)
    best = None
    for n in (count,) if count else WEDGE_COUNTS:
        period = 360.0 / n
        turned = abs(p.twist_turns) * 360.0 + 2.0 * p.sway_angle >= period  # every seam angle occurs
        angles = list(np.arange(0.0, period, period / (3 if turned else 8)))
        if p.ribs > 0:  # seams on a crest or in a groove
            angles += list(np.arange(0.0, period, 180.0 / p.ribs))
        if fold:  # or on a corner or a flat
            angles += list(np.arange(0.0, period, 90.0 / fold))
        top, at = np.inf, 0.0
        for a in sorted({round(float(x), 6) for x in angles}):
            t = pieces_trapped(xy, n, math.radians(a), top)
            if t < top:
                top, at = t, a
            if top == 0.0:
                break
        if best is None or top < best[2]:
            best = (n, at, top)
        if top <= LOCK_TOL:
            break
    return best


def wedge_lock_mask(g, n, phi, tol=LOCK_TOL):
    """Per ring vertex: True where the candle hooks the wedge it touches."""
    c, _ = bounding_circle(g.rings[..., :2])
    face = _plug_face(g)
    out = np.zeros(g.rings.shape[:2], bool)
    out[:face + 1] = _hook_mask(g.rings[:face + 1, :, :2] - c, n, phi, tol)
    return out


def _wedge_layout(g, m):
    """Mold axis and sizes, in candle coordinates (base at z = 0, top at H)."""
    c, rmax = bounding_circle(g.rings[..., :2])
    face = _plug_face(g)
    z_face = float(g.z[face])
    R_plug = float(np.linalg.norm(g.rings[face:, :, :2] - c, axis=-1).max()) + PLUG_WALL
    z_end = max(g.H + m.split_floor, z_face + 6.0)
    lo, hi = 2.0 + BAND_GROOVE, z_face - 2.0 - BAND_GROOVE  # rubber band grooves, clear of the socket
    bands = list(np.linspace(lo, hi, int((hi - lo) // 70.0) + 2)) if hi - lo > 12.0 else [0.5 * z_face]
    return SimpleNamespace(c=c, face=face, z_face=z_face, z_end=z_end, zt=0.5 * (z_face + z_end),
                           R_plug=R_plug, R_sock=R_plug + PLUG_FIT, bands=bands,
                           Rm=max(rmax + m.split_wall + BAND_GROOVE, R_plug + PLUG_FIT + TONGUE[0] + 3.0))


def _wedge_block(L, a0, a1):
    """Solid sector of the sleeve between angles a0 and a1, with the band grooves."""
    t = np.linspace(a0, a1, max(8, int(math.ceil(math.degrees(a1 - a0) / 1.5))) + 1)
    d = np.column_stack([np.cos(t), np.sin(t)])
    prof = [(0.0, L.Rm)]
    for zb in L.bands:
        prof += [(zb - BAND_GROOVE, L.Rm), (zb, L.Rm - BAND_GROOVE), (zb + BAND_GROOVE, L.Rm)]
    prof.append((L.z_end, L.Rm))
    mid = L.c + 0.5 * L.Rm * np.array([math.cos(0.5 * (a0 + a1)), math.sin(0.5 * (a0 + a1))])
    return loft([_ring(np.vstack([L.c, L.c + R * d]), z) for z, R in prof],
                cap_start=(*mid, 0.0), cap_end=(*mid, L.z_end))


def _socket_profile(L, grow):
    """(z, radius) of the plug's side with its tongue, grown by `grow` (the
    gap for the socket); 45 deg flanks stay 45 deg."""
    h, base, tip = TONGUE
    e = grow * (math.sqrt(2.0) - 1.0)  # how much wider a 45 deg flank gets when grown
    R = L.R_plug + grow
    return [(L.zt - base - e, R), (L.zt - tip - e, R + h), (L.zt + tip + e, R + h), (L.zt + base + e, R)]


def build_wedge_plug(g, m, L):
    """The plug: the candle's top and rounded edge as a recess, the wick hole,
    and the tongue around its side. Built upright; printed face up."""
    th, i, H = g.theta, L.face, g.H
    tc = g.centers[-1]
    prof = [(L.z_face, L.R_plug)] + _socket_profile(L, 0.0) + [(L.z_end, L.R_plug)]
    rings = [g.rings[i]] + [circle_ring(tc, L.c, r, th, z) for z, r in prof]
    rings += [disc_ring(tc, 0.5 * m.wick_diameter, th, L.z_end), disc_ring(tc, 0.5 * m.wick_diameter, th, H)]
    rings += list(g.rings[:i:-1])
    return loft(rings, closed=True)


def _wedge_cutters(g, L, phi, n):
    """The candle (through the pour face and on into the socket) and the socket
    with its groove. Socket corners sit halfway between the seams."""
    i = L.face
    rings = [_ring(g.rings[0][:, :2], -1.0)] + list(g.rings[:i + 1])
    rings.append(_ring(g.rings[i][:, :2], L.z_face + 1.0))
    candle = loft(rings, cap_start=(*g.centers[0], -1.0), cap_end=(*g.centers[i], L.z_face + 1.0))
    xy = candle.verts[:, :2]  # a vertex (almost) in a seam plane leaves slivers: keep them 0.02 mm clear
    for k in range(n):
        s = phi + k * TAU / n
        out, nrm = np.array([math.cos(s), math.sin(s)]), np.array([-math.sin(s), math.cos(s)])
        d = (xy - L.c) @ nrm
        near = ((xy - L.c) @ out > 0) & (np.abs(d) < 0.02)
        xy[near] += (np.where(d[near] >= 0, 0.02, -0.02) - d[near])[:, None] * nrm
    th = phi + (np.arange(240) + 0.5) * (TAU / 240)
    prof = [(L.z_face, L.R_sock)] + _socket_profile(L, PLUG_FIT) + [(L.z_end + 1.0, L.R_sock)]
    socket = loft([circle_ring(L.c, L.c, r, th, z) for z, r in prof],
                  cap_start=(*L.c, L.z_face), cap_end=(*L.c, L.z_end + 1.0))
    return candle, socket


def build_wedge_mold(p, m, g, n, angle_deg):
    """n wedges and the plug, placed for printing: wedges standing on the
    pour end, the plug face up."""
    L = _wedge_layout(g, m)
    # half a vertex step off the checked seam, so no candle vertex lies (almost) in a seam plane
    phi = math.radians(angle_deg) + math.pi / len(g.theta)
    cuts = _wedge_cutters(g, L, phi, n)
    parts = []
    for k in range(n):
        a0 = phi + k * TAU / n
        wedge = boolean_mesh(_wedge_block(L, a0, a0 + TAU / n), cut=cuts)
        parts.append((f"wedge_{k + 1}", place_for_print(wedge)))
    plug = build_wedge_plug(g, m, L)
    return parts + [("plug", place_for_print(plug, flip=True))]


def mold_parts(p, m, g, split_angle=None, wedges=None):
    """[(file suffix, Mesh)] oriented and placed for printing. wedges:
    (pieces, seam angle), found with best_wedges if not given."""
    if m.mold_type == "SPLIT":
        if split_angle is None:
            split_angle = best_split(p)[0] if m.split_auto else m.split_angle
        return build_split_mold(p, m, g, split_angle)
    if m.mold_type == "WEDGE":
        if wedges is None:
            wedges = best_wedges(p, None if m.wedge_auto else m.wedge_count)[:2]
        return build_wedge_mold(p, m, g, *wedges)
    if m.mold_type == "SILICONE":
        master, sleeve, _ = build_silicone_kit(p, m, g)
        return [("master", master), ("sleeve", sleeve)]
    if m.mold_type == "RIGID":
        return [("mold_rigid", build_rigid_mold(p, m, g))]
    if m.mold_type == "FLEX":
        return [("mold_flex", build_flex_mold(p, m, g))]
    return [("candle", place_for_print(build_candle(g)))]


# ---------------------------------------------------------------------------
# Print material estimate
#
# A slicer prints a shell (walls, top and bottom layers) solid and fills the
# rest with sparse infill, so grams ~ (shell + infill x inside) x density.
# ---------------------------------------------------------------------------

SHELL_MM = 0.85  # Bambu Studio defaults: 2 walls of 0.42 mm, 1.0 mm top and 0.6 mm bottom layers
PRINT_MATERIAL = {"SILICONE": ("PLA", 1.24), "SPLIT": ("PLA/PETG", 1.25), "WEDGE": ("PLA/PETG", 1.25),
                  "FLEX": ("TPU", 1.21), "RIGID": ("PETG", 1.27)}
PART_NAMES = {"master": "master", "sleeve": "sleeve", "half_a": "half A", "half_b": "half B",
              "screws_x4": "4 screws", "mold_rigid": "mold", "mold_flex": "mold", "plug": "plug",
              **{f"wedge_{k}": f"wedge {k}" for k in range(1, max(WEDGE_COUNTS) + 1)}}


def print_grams(volume, area, infill, density):
    """Filament for one part: volume and surface in mm, infill 0..1, g/cm3."""
    shell = min(volume, area * SHELL_MM)
    inside = volume - shell
    if inside < 0.25 * area:  # thin-walled part (gap between walls < 0.5 mm): printed solid
        infill = 1.0
    return (shell + infill * inside) * density / 1000.0


def _wedge_parts(g, m, n, angle_deg):
    """Volume and surface of each wedge from the sleeve and the candle slices
    it holds (no booleans); the plug is built directly, so it is exact."""
    L = _wedge_layout(g, m)
    nb, half, phi = L.face + 1, math.pi / n, math.radians(angle_deg)
    P, C = g.rings[:nb, :, :2] - L.c, g.centers[:nb, None, :] - L.c
    a, b = P - C, np.roll(P, -1, axis=1) - C
    fan = 0.5 * (a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0])  # slice area as triangles from its centre

    def sector(xy):
        return np.floor(np.mod(np.arctan2(xy[..., 1], xy[..., 0]) - phi, TAU) / (2.0 * half)).astype(int) % n

    k_fan = sector(3.0 * C + a + b)  # by the triangle's centroid (times 3)
    A = g.rings[:nb]
    B = np.roll(A, -1, axis=1)
    side = 0.5 * np.linalg.norm(np.cross(B[1:] - A[:-1], A[1:] - B[:-1]), axis=-1)  # candle wall quads
    k_side = sector(A[:-1, :, :2] + B[1:, :, :2] - 2.0 * L.c)
    dz = np.diff(g.z[:nb])
    wz = 0.5 * (np.concatenate([dz, [0.0]]) + np.concatenate([[0.0], dz]))  # trapezoid weights
    ang, rad = np.mod(np.arctan2(P[..., 1], P[..., 0]), TAU), np.linalg.norm(P, axis=-1)
    order = np.argsort(ang, axis=1)
    ang, rad = np.take_along_axis(ang, order, 1), np.take_along_axis(rad, order, 1)
    T, Rm, Rs = L.z_end - L.z_face, L.Rm, L.R_sock
    h, base, tip = TONGUE
    e = PLUG_FIT * (math.sqrt(2.0) - 1.0)
    groove = h * (base + tip + 2.0 * e)  # cross-section of the tongue groove
    v_bands = len(L.bands) * BAND_GROOVE ** 2 * 2.0 * half * (Rm - BAND_GROOVE / 3.0)
    s_bands = len(L.bands) * 2.0 * BAND_GROOVE * (math.sqrt(2.0) - 1.0) * 2.0 * half * Rm
    parts = []
    for k in range(n):
        held = (fan * (k_fan == k)).sum(axis=1)  # candle area in this wedge, per slice
        seams = sum(((Rm - np.array([np.interp(np.mod(s, TAU), a, r, period=TAU) for a, r in zip(ang, rad)]))
                     * wz).sum() for s in (phi + 2 * k * half, phi + 2 * (k + 1) * half))
        vol = (half * Rm * Rm * L.z_face - (held * wz).sum() + half * (Rm * Rm - Rs * Rs) * T
               - v_bands - groove * 2.0 * half * (Rs + 0.5 * h))
        area = (2.0 * half * Rm * L.z_end + s_bands + seams + 2.0 * (Rm - Rs) * T
                + side[k_side == k].sum() + 2.0 * half * Rm * Rm - held[0] - held[-1]
                + 2.0 * half * Rs * (T + 2.0 * (math.sqrt(2.0) - 1.0) * h))
        parts.append((f"wedge_{k + 1}", vol, area, False))
    plug = build_wedge_plug(g, m, L)
    return parts + [("plug", plug.volume(), plug.area(), False)]


def print_parts(p, m, g, split_angle=0.0, wedges=None):
    """[(part, volume mm3, surface mm2, printed solid)] for the estimate. The
    two-part halves and the wedges are worked out from the block and cavity
    sizes, so no booleans are needed and it is quick enough to run while
    designing."""
    if m.mold_type == "WEDGE":
        if wedges is None:
            wedges = best_wedges(p, None if m.wedge_auto else m.wedge_count)[:2]
        return _wedge_parts(g, m, *wedges)
    if m.mold_type == "SPLIT":
        L = _split_layout(g, m, split_angle)
        candle = build_candle(g)
        P, c = L.rings[..., :2], L.centers[:, None, :]
        a, b = P - c, np.roll(P, -1, axis=1) - c
        dz = np.gradient(g.z)[:, None]
        tri = 0.5 * (a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0])  # slice area, as fan triangles
        side_a = c[..., 0] + P[..., 0] + np.roll(P[..., 0], -1, axis=1) > 0  # centroid x (times 3)
        fa = float((tri * dz)[side_a].sum() / (tri * dz).sum())  # share of the cavity in half A
        base = float(tri[0].sum())  # pour opening
        seam = float((np.ptp(P[..., 1], axis=1) * dz[:, 0]).sum())  # cavity opening in the seam face
        box_v = L.D * 2.0 * L.Wy * L.Hb
        box_s = 2.0 * (L.D * 2.0 * L.Wy + L.D * L.Hb + 2.0 * L.Wy * L.Hb)
        holes = {"PRINTED": (0.5 * SCREW["major"] + SCREW["clearance"] - 0.5 * SCREW["depth"],
                             0.5 * SCREW["major"] + 0.45),
                 "M5": (2.75, 2.75)}.get(m.fastener, (0.0, 0.0))
        parts = []
        for name, f, r in (("half_a", fa, holes[0]), ("half_b", 1.0 - fa, holes[1])):
            vol = box_v - f * candle.volume() - 4.0 * math.pi * r * r * L.D
            area = box_s - seam + f * (candle.area() - 2.0 * base) + 4.0 * TAU * r * L.D
            parts.append((name, vol, area, False))
        if m.fastener == "PRINTED":
            screw = build_screw(L.D - 1.0, L.D - 2.0)
            parts.append(("screws_x4", 4.0 * screw.volume(), 4.0 * screw.area(), True))
        return parts
    if m.mold_type == "NONE":
        return []
    return [(name, mesh.volume(), mesh.area(), False) for name, mesh in mold_parts(p, m, g)]


def write_stl(path, mesh, name="Candle Studio"):
    tri = mesh.verts[mesh.triangles()]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = np.divide(nrm, length, out=np.zeros_like(nrm), where=length > 0)
    rec = np.zeros(len(tri), dtype=[("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec["n"] = nrm
    rec["v"] = tri
    with open(path, "wb") as fh:
        fh.write(("binary STL, mm - " + name).encode("ascii", "replace")[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(rec)))
        rec.tofile(fh)


def open_in_bambu(paths):
    try:
        if sys.platform == "darwin":
            return subprocess.run(["open", "-a", "BambuStudio", *paths],
                                  capture_output=True, timeout=20).returncode == 0
        if os.name == "nt":
            for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                         os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
                exe = os.path.join(root, "Bambu Studio", "bambu-studio.exe")
                if os.path.exists(exe):
                    subprocess.Popen([exe, *paths])
                    return True
            return False
        subprocess.Popen(["bambu-studio", *paths])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Blender side
# ---------------------------------------------------------------------------

COLLECTION = "Candle Studio"
OBJ_CANDLE, OBJ_WICK = "Candle", "Candle Wick"
OBJ_MOLDS = ("Candle Master", "Candle Sleeve", "Candle Mold",
             "Candle Mold A", "Candle Mold B", "Candle Screws", "Candle Plug",
             *(f"Candle Wedge {k}" for k in range(1, max(WEDGE_COUNTS) + 1)))
_suspend = [False]
_stats = {}


def _snapshot(props):
    p = SimpleNamespace(**{k: getattr(props, k) for k in SHAPE_DEFAULTS})
    p.color = tuple(props.color)
    m = SimpleNamespace(**{k: getattr(props, k) for k in MOLD_DEFAULTS})
    return p, m


def _collection(scene):
    coll = bpy.data.collections.get(COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(COLLECTION)
    if scene.collection.children.get(coll.name) is None:
        scene.collection.children.link(coll)
    return coll


def _object(scene, name):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    if not obj.users_collection:
        _collection(scene).objects.link(obj)
    return obj


def _set_mesh(me, mesh):
    key = f"{len(mesh.verts)}/{len(mesh.quads)}/{len(mesh.tris)}"
    if me.get("candle_key") == key and len(me.vertices) == len(mesh.verts):
        me.vertices.foreach_set("co", mesh.verts.astype(np.float32).ravel())
    else:
        me.clear_geometry()
        me.from_pydata(mesh.verts.tolist(), [], mesh.quads.tolist() + mesh.tris.tolist())
        me["candle_key"] = key
    me.update()
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(60))  # crisp base / top edges, smooth steep ribs


def _material(name, rgb, roughness=0.5, subsurface=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) \
        if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        if "Subsurface Weight" in bsdf.inputs:
            bsdf.inputs["Subsurface Weight"].default_value = subsurface
    return mat


def _assign(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def _setup_scene_units(scene):
    us = scene.unit_settings
    if us.scale_length != 0.001:
        us.system = "METRIC"
        us.scale_length = 0.001  # 1 Blender unit = 1 mm
        us.length_unit = "MILLIMETERS"
        for area in getattr(bpy.context.screen, "areas", []):
            if area.type == "VIEW_3D":
                area.spaces.active.clip_start = 0.1
                area.spaces.active.clip_end = 20000.0


def update_candle(scene):
    props = scene.candle_studio
    p, m = _snapshot(props)
    g = candle_geometry(p, props.preview_segments, props.preview_step, m.wick_diameter)
    mesh = build_candle(g)
    obj = _object(scene, OBJ_CANDLE)
    _set_mesh(obj.data, mesh)
    _assign(obj, _material("Candle Wax", p.color, roughness=0.45, subsurface=0.2))

    tc = g.centers[-1]
    th = np.linspace(0.0, TAU, 16, endpoint=False)
    wick = loft([disc_ring(tc, 1.0, th, g.H - 1.0), disc_ring(tc, 1.0, th, g.H + 14.0)],
                cap_start=(*tc, g.H - 1.0), cap_end=(*tc, g.H + 14.0))
    wobj = _object(scene, OBJ_WICK)
    _set_mesh(wobj.data, wick)
    wobj.hide_viewport = wobj.hide_render = not props.show_wick
    _assign(wobj, _material("Candle Wick", _hex("EDE6D6"), roughness=0.9))

    c, rmax = bounding_circle(g.rings[..., :2])
    vol = mesh.volume() / 1000.0
    Ri = rmax + m.sil_wall
    base_x, base_y = np.ptp(g.rings[0, :, :2], axis=0)
    _stats.update(height=p.height, dia=2.0 * rmax, base_x=base_x, base_y=base_y, ml=vol, wax=vol * 0.86,
                  silicone=(math.pi * Ri * Ri * (p.height + m.sil_top)) / 1000.0 - vol)

    locks = m.mold_type in ("SPLIT", "WEDGE") and props.show_locks
    if locks:  # plain wax colour while sliders move; red zones follow once you pause
        _paint_locks(obj.data, p.color, None)
    for key in ("split", "wedge", "print"):
        _stats.pop(key, None)
    _schedule_mold_checks()
    _set_lock_view(locks)
    return obj


LOCK_RED = (0.8, 0.06, 0.04)


def _paint_locks(me, wax, mask):
    attr = me.color_attributes.get("Candle Locks")
    if attr is None:
        attr = me.color_attributes.new("Candle Locks", "FLOAT_COLOR", "POINT")
    col = np.tile([*wax, 1.0], (len(me.vertices), 1))
    if mask is not None and mask.size <= len(me.vertices):
        col[:mask.size][mask.ravel()] = (*LOCK_RED, 1.0)
    attr.data.foreach_set("color", col.astype(np.float32).ravel())
    me.color_attributes.active_color = attr
    me.update()


def _view3d_spaces():
    wm = bpy.context.window_manager
    for win in (wm.windows if wm else []):
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                yield area


def _set_lock_view(on):
    """Solid view shows the red lock zones only in 'Attribute' colour mode."""
    for area in _view3d_spaces():
        shading = area.spaces.active.shading
        if on and shading.color_type == "MATERIAL":
            shading.color_type = "VERTEX"
        elif not on and shading.color_type == "VERTEX":
            shading.color_type = "MATERIAL"


def run_split_check(scene):
    """Find the best seam (or use the manual one), store the result and paint
    the lock zones on the viewport candle."""
    props = scene.candle_studio
    p, m = _snapshot(props)
    if m.split_auto:
        angle, trapped = best_split(p)
    else:
        angle = m.split_angle
        xy = candle_geometry(p, 96, 2.0).rings[..., :2]
        trapped = split_trapped(xy, math.radians(angle))
    _stats["split"] = dict(angle=angle, trapped=trapped, ok=trapped <= LOCK_TOL)
    obj = scene.objects.get(OBJ_CANDLE)
    if obj is not None and props.show_locks:
        g = candle_geometry(p, props.preview_segments, props.preview_step, m.wick_diameter)
        _paint_locks(obj.data, p.color, lock_mask(g, math.radians(angle)))
    return _stats["split"]


def run_wedge_check(scene):
    """Find how many wedges release (or check the chosen count), store the
    result and paint the lock zones on the viewport candle."""
    props = scene.candle_studio
    p, m = _snapshot(props)
    n, angle, trapped = best_wedges(p, None if m.wedge_auto else m.wedge_count)
    _stats["wedge"] = dict(pieces=n, angle=angle, trapped=trapped, ok=trapped <= LOCK_TOL)
    obj = scene.objects.get(OBJ_CANDLE)
    if obj is not None and props.show_locks:
        mask = None
        if trapped > LOCK_TOL:
            g = candle_geometry(p, props.preview_segments, props.preview_step, m.wick_diameter)
            mask = wedge_lock_mask(g, n, math.radians(angle))
        _paint_locks(obj.data, p.color, mask)
    return _stats["wedge"]


def run_print_estimate(scene, split_angle=0.0, wedges=None):
    """Store the printed parts' volume and surface for the filament estimate."""
    props = scene.candle_studio
    p, m = _snapshot(props)
    g = candle_geometry(p, props.preview_segments, props.preview_step, m.wick_diameter)
    _stats["print"] = print_parts(p, m, g, split_angle, wedges)
    return _stats["print"]


def _mold_timer():
    """Runs a moment after the sliders stop: release check and print estimate."""
    scene = bpy.context.scene
    if scene is not None and hasattr(scene, "candle_studio"):
        angle, wedges = 0.0, None
        if scene.candle_studio.mold_type == "SPLIT":
            angle = run_split_check(scene)["angle"]
        elif scene.candle_studio.mold_type == "WEDGE":
            res = run_wedge_check(scene)
            wedges = (res["pieces"], res["angle"])
        run_print_estimate(scene, angle, wedges)
        for area in _view3d_spaces():
            area.tag_redraw()
    return None


def _schedule_mold_checks(delay=0.35):
    if bpy.app.timers.is_registered(_mold_timer):
        bpy.app.timers.unregister(_mold_timer)
    bpy.app.timers.register(_mold_timer, first_interval=delay)


def update_mold_preview(scene):
    props = scene.candle_studio
    p, m = _snapshot(props)
    g = candle_geometry(p, props.preview_segments, props.preview_step, m.wick_diameter)
    _, rmax = bounding_circle(g.rings[..., :2])
    for name in OBJ_MOLDS:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            me = obj.data
            bpy.data.objects.remove(obj)
            if me.users == 0:
                bpy.data.meshes.remove(me)
    if m.mold_type == "NONE":
        return []
    names = {"master": "Candle Master", "sleeve": "Candle Sleeve",
             "mold_rigid": "Candle Mold", "mold_flex": "Candle Mold",
             "half_a": "Candle Mold A", "half_b": "Candle Mold B", "screws_x4": "Candle Screws",
             "plug": "Candle Plug",
             **{f"wedge_{k}": f"Candle Wedge {k}" for k in range(1, max(WEDGE_COUNTS) + 1)}}
    mat = _material("Candle Mold Print", _hex("7FB8B0"), roughness=0.6)
    created = []
    x = rmax + 2.0 * (rmax + m.sil_wall) + 20.0
    angle = run_split_check(scene)["angle"] if m.mold_type == "SPLIT" else None
    res = run_wedge_check(scene) if m.mold_type == "WEDGE" else None
    for suffix, mesh in mold_parts(p, m, g, angle, res and (res["pieces"], res["angle"])):
        obj = _object(scene, names[suffix])
        _set_mesh(obj.data, mesh)
        _assign(obj, mat)
        width = float(np.ptp(mesh.verts[:, 0]))
        x += 0.5 * width
        obj.location = (x, 0.0, 0.0)
        x += 0.5 * width + 20.0
        created.append(obj)
    return created


def _on_change(self, context):
    if not _suspend[0]:
        update_candle(context.scene)


def _apply(props, values):
    _suspend[0] = True
    try:
        for k, v in values.items():
            if hasattr(props, k):
                setattr(props, k, v)
    finally:
        _suspend[0] = False


def _apply_preset(props, key):
    values = dict(SHAPE_DEFAULTS)
    values.update(PRESETS[key][2])
    if key == "DEFAULT":  # the mold too (export name, folder and viewport detail stay)
        values.update(MOLD_DEFAULTS, show_wick=True, show_locks=True)
    _apply(props, values)


def _on_preset(self, context):
    _apply_preset(self, self.preset)
    update_candle(context.scene)


def _export_dir(props):
    if props.export_dir:
        return bpy.path.abspath(props.export_dir)
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "candle_exports")
    return os.path.join(os.path.expanduser("~"), "Documents", "Candle Studio")


def _safe_name(name):
    keep = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip())
    return keep or "candle"


def random_design(rng, keep):
    d = dict(SHAPE_DEFAULTS)
    d.update(keep)
    family = rng.choice(["twist", "sway", "rope", "bubble", "wave"])
    if family == "twist":
        d.update(ribs=rng.randint(4, 14), rib_depth=rng.uniform(2, 6),
                 rib_fullness=rng.uniform(-0.5, 0.8),
                 twist_turns=rng.uniform(0.3, 2.5) * rng.choice([-1, 1]),
                 top_scale=rng.choice([1.0, 1.0, 0.7, 0.4]))
    elif family == "sway":
        d.update(ribs=rng.randint(5, 10), rib_depth=rng.uniform(3, 6),
                 rib_fullness=rng.uniform(0.2, 0.7), twist_turns=rng.uniform(-0.3, 0.3),
                 sway_angle=rng.uniform(12, 30), sway_waves=rng.uniform(1, 3.5),
                 sway_phase=rng.uniform(-90, 90), sway_stagger=rng.choice([0, 0, 1]),
                 wave_amount=rng.choice([0, 3, 6]), wave_count=rng.uniform(1, 2.5))
    elif family == "rope":
        d.update(ribs=rng.randint(2, 4), rib_depth=rng.uniform(7, 12),
                 rib_fullness=rng.uniform(0.5, 0.9), twist_turns=rng.uniform(1, 2.5))
    elif family == "bubble":
        d.update(ribs=rng.choice([0, 0, 6, 10]), rib_depth=rng.uniform(1.5, 3),
                 bulge_mode="BUBBLE", bulge_amount=rng.uniform(0.3, 0.5),
                 bulge_count=rng.uniform(2.5, 4.5), bulge_phase=rng.uniform(40, 80),
                 twist_turns=rng.uniform(0, 0.5), top_round=3.0)
    else:
        count = rng.uniform(1, 3)
        d.update(ribs=rng.randint(5, 12), rib_depth=rng.uniform(2, 5),
                 wave_mode=rng.choice(["PLANAR", "PLANAR", "HELIX"]),
                 wave_amount=rng.uniform(4, 9), wave_count=count,
                 sway_angle=rng.uniform(0, 15), sway_waves=count)
    if family in ("twist", "sway", "wave") and rng.random() < 0.4:  # folds / fins
        d.update(rib_lean=rng.uniform(0.3, 0.7) * rng.choice([-1, 1]),
                 rib_fullness=rng.uniform(-0.6, 0.0))
    if family == "twist" and rng.random() < 0.3:  # swirl that settles toward the top
        d.update(twist_focus=rng.uniform(0.4, 0.9), fade_top=rng.uniform(25, 50))
    d["color"] = rng.choice(list(PALETTE.values()))
    return d


def _preset_items():
    return [(k, v[0], v[1]) for k, v in PRESETS.items()]


class CandleProps(bpy.types.PropertyGroup):
    design_name: StringProperty(name="Name", default="swirl_candle",
                                description="Used for the exported file names")
    preset: EnumProperty(name="Preset", items=_preset_items(), update=_on_preset)

    # shape & size
    base_shape: EnumProperty(name="Shape", update=_on_change,
                             items=[(k, v[0], v[1]) for k, v in BASE_SHAPES.items()])
    shape_stretch: FloatProperty(name="Length Ratio", default=1.5, min=1.0, max=3.0, update=_on_change,
                                 description="Length / Width of the oval or rectangle")
    corner_round: FloatProperty(name="Corner Round (mm)", default=4.0, min=0.5, max=60.0,
                                update=_on_change,
                                description="Radius of the rounded corners (large = softer shape)")
    height: FloatProperty(name="Height (mm)", default=150.0, min=20.0, max=400.0, update=_on_change)
    diameter: FloatProperty(name="Diameter (mm)", default=60.0, min=15.0, max=200.0,
                            description="Size at the base, measured over the ribs: the diameter, "
                                        "or for other shapes the width across the flats "
                                        "(narrow side of an oval or rectangle)",
                            update=_on_change)
    top_scale: FloatProperty(name="Top Size", default=1.0, min=0.15, max=2.0,
                             description="Width at the top relative to the base (<1 = cone)",
                             update=_on_change)
    taper_power: FloatProperty(name="Taper Curve", default=1.0, min=0.3, max=4.0,
                               description="1 = straight cone, >1 = stays wide longer, <1 = narrows early",
                               update=_on_change)
    top_round: FloatProperty(name="Top Edge Round (mm)", default=2.5, min=0.0, max=15.0,
                             update=_on_change)
    color: FloatVectorProperty(name="Wax Colour", subtype="COLOR", size=3, min=0.0, max=1.0,
                               default=SHAPE_DEFAULTS["color"], update=_on_change)
    show_wick: BoolProperty(name="Show Wick", default=True, update=_on_change)

    # ribs, twist, sway
    ribs: IntProperty(name="Ribs", default=8, min=0, max=40, update=_on_change,
                      description="Number of lobes, spaced evenly around the outline (0 = smooth)")
    rib_depth: FloatProperty(name="Rib Depth (mm)", default=4.0, min=0.0, max=25.0, update=_on_change)
    rib_fullness: FloatProperty(name="Rib Fullness", default=0.3, min=-1.0, max=1.0, update=_on_change,
                                description="+ fat round lobes with narrow grooves (rope / flower), "
                                            "- thin ridges with wide grooves (fluted)")
    rib_lean: FloatProperty(name="Rib Lean", default=0.0, min=-0.8, max=0.8, update=_on_change,
                            description="Tilts every rib: one steep side and one gentle side, like "
                                        "overlapping folds or fins. 0 = symmetric; sign = direction")
    fade_bottom: FloatProperty(name="Fade Bottom", subtype="PERCENTAGE", default=0.0, min=0.0, max=100.0,
                               update=_on_change,
                               description="Ribs ease out to a smooth surface over this share of the "
                                           "height, at the bottom")
    fade_top: FloatProperty(name="Fade Top", subtype="PERCENTAGE", default=0.0, min=0.0, max=100.0,
                            update=_on_change,
                            description="Ribs ease out to a smooth surface over this share of the "
                                        "height, at the top")
    twist_turns: FloatProperty(name="Twist (turns)", default=0.0, min=-6.0, max=6.0, update=_on_change,
                               description="Full turns the ribs (and a non-round shape) spiral over "
                                           "the height; sign = direction")
    twist_focus: FloatProperty(name="Twist Focus", default=0.0, min=-1.0, max=1.0, update=_on_change,
                               description="Where the twist is tightest: 0 = even, + toward the bottom "
                                           "(ribs straighten out going up), - toward the top")
    sway_angle: FloatProperty(name="Sway (deg)", default=0.0, min=0.0, max=90.0, update=_on_change,
                              description="Ribs swing left and right by this angle")
    sway_waves: FloatProperty(name="Sway Waves", default=1.5, min=0.1, max=12.0, update=_on_change,
                              description="How many back-and-forth swings over the height")
    sway_phase: FloatProperty(name="Sway Phase (deg)", default=0.0, min=-360.0, max=360.0,
                              update=_on_change)
    sway_stagger: IntProperty(name="Sway Stagger", default=0, min=0, max=4, update=_on_change,
                              description="0 = all ribs sway together; 1+ = ribs drift out of sync (organic)")

    # waves & bulges
    wave_mode: EnumProperty(name="Wave", items=[
        ("PLANAR", "S-Wave", "The candle bends side to side in one plane"),
        ("HELIX", "Corkscrew", "The candle's axis winds around in a helix")], update=_on_change)
    wave_amount: FloatProperty(name="Wave Size (mm)", default=0.0, min=0.0, max=40.0, update=_on_change)
    wave_count: FloatProperty(name="Wave Count", default=1.0, min=0.1, max=10.0, update=_on_change)
    wave_phase: FloatProperty(name="Wave Phase (deg)", default=0.0, min=-360.0, max=360.0,
                              update=_on_change)
    wave_direction: FloatProperty(name="Wave Direction (deg)", default=0.0, min=-180.0, max=180.0,
                                  update=_on_change)
    bulge_mode: EnumProperty(name="Bulge", items=[
        ("SINE", "Soft", "Smooth swelling and narrowing"),
        ("BUBBLE", "Bubbles", "Stacked round bubbles with pinched waists")], update=_on_change)
    bulge_amount: FloatProperty(name="Bulge Amount", default=0.0, min=0.0, max=0.7, update=_on_change)
    bulge_count: FloatProperty(name="Bulge Count", default=2.0, min=0.2, max=12.0, update=_on_change)
    bulge_phase: FloatProperty(name="Bulge Phase (deg)", default=0.0, min=-360.0, max=360.0,
                               update=_on_change)

    # quality
    preview_segments: IntProperty(name="Viewport Segments", default=144, min=32, max=512,
                                  update=_on_change)
    preview_step: FloatProperty(name="Viewport Ring Spacing (mm)", default=1.0, min=0.2, max=5.0,
                                update=_on_change)
    export_quality: EnumProperty(name="Export Quality", default="FINE", items=[
        ("DRAFT", "Draft", "180 segments, 0.8 mm rings - quick test prints"),
        ("FINE", "Fine", "320 segments, 0.4 mm rings"),
        ("ULTRA", "Ultra", "480 segments, 0.25 mm rings - big files")])

    # mold
    mold_type: EnumProperty(name="Mold", default="SILICONE", update=_on_change, items=[
        ("SILICONE", "Silicone mold kit", "Print a master + pour sleeve, cast silicone around it. "
                                          "Works for every design"),
        ("SPLIT", "Printed two-part mold", "Two halves held by screws, like a classic block mold. "
                                           "Only for shapes that release - the panel checks"),
        ("WEDGE", "Printed wedge mold (3-6 pieces)", "A sleeve split into 3 to 6 wedges plus an end plug, "
                                                     "held by rubber bands. Releases most twisted "
                                                     "designs - the panel checks"),
        ("FLEX", "Printed flexible mold (TPU)", "Thin shell that follows the candle; peel it off"),
        ("RIGID", "Printed rigid mold (PETG)", "One-piece block; only for twist-only designs, "
                                               "the candle unscrews out"),
        ("NONE", "Candle only", "Export the candle shape itself")])
    wick_diameter: FloatProperty(name="Wick Hole (mm)", default=2.5, min=1.0, max=8.0, update=_on_change)
    sil_wall: FloatProperty(name="Silicone Wall (mm)", default=8.0, min=3.0, max=30.0, update=_on_change,
                            description="Silicone thickness around the widest point")
    sil_top: FloatProperty(name="Silicone Top (mm)", default=6.0, min=3.0, max=30.0, update=_on_change,
                           description="Silicone thickness above the candle top (mold floor)")
    sleeve_wall: FloatProperty(name="Sleeve Wall (mm)", default=2.0, min=0.8, max=6.0)
    fit_clearance: FloatProperty(name="Sleeve Fit (mm)", default=0.3, min=0.0, max=1.0,
                                 description="Gap between the sleeve and the base plate step")
    plate_thickness: FloatProperty(name="Plate Thickness (mm)", default=3.0, min=1.5, max=10.0)
    step_height: FloatProperty(name="Plate Step (mm)", default=4.0, min=2.0, max=15.0)
    mold_wall: FloatProperty(name="Min Wall (mm)", default=4.0, min=1.5, max=30.0)
    mold_floor: FloatProperty(name="Floor (mm)", default=3.0, min=1.0, max=15.0)
    flex_wall: FloatProperty(name="Wall (mm)", default=1.8, min=0.8, max=6.0)
    flange_width: FloatProperty(name="Rim Flange (mm)", default=8.0, min=0.0, max=40.0,
                                description="Rim around the opening; 0 = none")
    flange_thickness: FloatProperty(name="Flange Thickness (mm)", default=2.0, min=1.0, max=8.0)
    split_wall: FloatProperty(name="Min Wall (mm)", default=5.0, min=2.0, max=30.0,
                              description="Plastic between the candle and the outside of the mold")
    split_floor: FloatProperty(name="Floor (mm)", default=4.0, min=2.0, max=20.0,
                               description="Mold thickness beyond the candle top (wick end)")
    fastener: EnumProperty(name="Hold Together", default="PRINTED", items=[
        ("PRINTED", "Printed screws", "4 printed 8 mm screws, threads printed into half A"),
        ("M5", "M5 bolts + nuts", "Through holes with hex nut pockets in half A"),
        ("NONE", "Clamps / rubber bands", "No holes, just alignment pins")])
    split_auto: BoolProperty(name="Auto Seam", default=True, update=_on_change,
                             description="Turn the seam to the angle where the candle releases best")
    split_angle: FloatProperty(name="Seam Angle (deg)", default=0.0, min=0.0, max=180.0,
                               update=_on_change)
    wedge_auto: BoolProperty(name="Auto Pieces", default=True, update=_on_change,
                             description="Use the fewest wedges (3 to 6) that release the candle")
    wedge_count: IntProperty(name="Pieces", default=4, min=3, max=6, update=_on_change,
                             description="Number of wedges; more pieces release deeper and "
                                         "twistier designs, but leave more seam lines")
    show_locks: BoolProperty(name="Show Lock Areas", default=True, update=_on_change,
                             description="Paint the places where the candle would grip a two-part "
                                         "or wedge mold red (viewport colour switches to Attribute)")
    infill: IntProperty(name="Infill", subtype="PERCENTAGE", default=15, min=0, max=100,
                        description="Sparse infill used for the filament estimate. 10-15% is plenty "
                                    "for molds; the printed screws are counted solid")

    # export
    export_dir: StringProperty(name="Folder", subtype="DIR_PATH", default="",
                               description="Empty = 'candle_exports' next to the .blend, "
                                           "or ~/Documents/Candle Studio")
    export_candle: BoolProperty(name="Also export candle shape", default=False)
    open_bambu: BoolProperty(name="Open in Bambu Studio", default=True)


def _props(context):
    return context.scene.candle_studio


class CANDLE_OT_generate(bpy.types.Operator):
    bl_idname = "candle.generate"
    bl_label = "Create / Refresh Candle"
    bl_description = "Build the candle from the current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _setup_scene_units(context.scene)
        obj = update_candle(context.scene)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class CANDLE_OT_reset_preset(bpy.types.Operator):
    bl_idname = "candle.reset_preset"
    bl_label = "Reset to Preset"
    bl_description = "Throw away tweaks and reload the selected preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = _props(context)
        _apply_preset(props, props.preset)
        update_candle(context.scene)
        return {"FINISHED"}


class CANDLE_OT_randomize(bpy.types.Operator):
    bl_idname = "candle.randomize"
    bl_label = "Surprise Me"
    bl_description = "Random design (keeps the shape, height and width)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = _props(context)
        keep = {k: getattr(props, k) for k in ("base_shape", "shape_stretch", "corner_round",
                                               "height", "diameter")}
        _apply(props, random_design(random.Random(), keep))
        update_candle(context.scene)
        return {"FINISHED"}


class CANDLE_OT_build_mold(bpy.types.Operator):
    bl_idname = "candle.build_mold"
    bl_label = "Preview Mold"
    bl_description = "Show the printable mold parts next to the candle (print orientation)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _setup_scene_units(context.scene)
        update_candle(context.scene)
        objs = update_mold_preview(context.scene)
        self.report({"INFO"}, f"Built {len(objs)} mold part(s)")
        return {"FINISHED"}


class CANDLE_OT_export(bpy.types.Operator):
    bl_idname = "candle.export"
    bl_label = "Export for Bambu Studio"
    bl_description = "Write print-ready STL files (mm) plus the design settings as JSON"

    def execute(self, context):
        props = _props(context)
        p, m = _snapshot(props)
        segs, step = QUALITY[props.export_quality]
        g = candle_geometry(p, segs, step, m.wick_diameter)
        check = run_split_check(context.scene) if m.mold_type == "SPLIT" else None
        wedge = run_wedge_check(context.scene) if m.mold_type == "WEDGE" else None
        parts = mold_parts(p, m, g, check["angle"] if check else None,
                           wedge and (wedge["pieces"], wedge["angle"]))
        if props.export_candle and m.mold_type != "NONE":
            parts.append(("candle", place_for_print(build_candle(g))))
        folder = _export_dir(props)
        os.makedirs(folder, exist_ok=True)
        base = _safe_name(props.design_name)
        written = []
        for suffix, mesh in parts:
            path = os.path.join(folder, f"{base}_{suffix}.stl")
            write_stl(path, mesh, f"{base} {suffix}")
            written.append(path)
        settings = {"candle_studio": 1, "shape": vars(p), "mold": vars(m)}
        settings["shape"]["color"] = list(p.color)
        with open(os.path.join(folder, f"{base}_design.json"), "w") as fh:
            json.dump(settings, fh, indent=2)
        msg = f"Exported {len(written)} STL file(s) to {folder}"
        if m.mold_type in PRINT_MATERIAL:
            material, density = PRINT_MATERIAL[m.mold_type]
            grams = sum(print_grams(mesh.volume(), mesh.area(),
                                    1.0 if suffix == "screws_x4" else m.infill / 100.0, density)
                        for suffix, mesh in parts if suffix != "candle")
            msg += f". Print: about {grams:.0f} g {material} at {m.infill}% infill"
        if check is not None:
            if m.fastener == "M5":
                msg += f". Use 4x M5 x {_stats['split_build']['bolt']} mm bolts + nuts"
            if not check["ok"]:
                msg += (f". WARNING: this shape locks in a two-part mold "
                        f"({check['trapped']:.1f} mm undercut, red areas)")
        if wedge is not None:
            msg += f". {wedge['pieces']} wedges + plug: hold them with rubber bands in the grooves"
            if not wedge["ok"]:
                msg += (f". WARNING: this shape locks in {wedge['pieces']} wedges "
                        f"({wedge['trapped']:.1f} mm undercut, red areas)")
        if props.open_bambu:
            printable = [w for w in written if not w.endswith("_candle.stl")] or written
            if not open_in_bambu(printable):
                msg += " (couldn't launch Bambu Studio - open the files from there)"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class CANDLE_OT_load_design(bpy.types.Operator, ImportHelper):
    bl_idname = "candle.load_design"
    bl_label = "Load Design"
    bl_description = "Load settings from a *_design.json written by Export"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        with open(self.filepath) as fh:
            data = json.load(fh)
        values = dict(SHAPE_DEFAULTS)  # older files have no base shape: they are round
        values.update(data.get("shape", {}))
        values.update(data.get("mold", {}))
        _apply(_props(context), values)
        update_candle(context.scene)
        return {"FINISHED"}


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Candle"


class CANDLE_PT_main(_Panel, bpy.types.Panel):
    bl_label = "Candle Studio"

    def draw(self, context):
        props = _props(context)
        layout = self.layout
        row = layout.row(align=True)
        row.prop(props, "preset", text="")
        row.operator("candle.reset_preset", text="", icon="LOOP_BACK")
        layout.operator("candle.randomize", icon="MOD_NOISE")
        if context.scene.objects.get(OBJ_CANDLE) is None:
            layout.operator("candle.generate", icon="MESH_CYLINDER")
            return
        if _stats:
            box = layout.box().column(align=True)
            if props.base_shape == "ROUND":
                box.label(text=f"{_stats['height']:.0f} mm tall, {_stats['dia']:.0f} mm wide")
            else:
                box.label(text=f"{_stats['height']:.0f} mm tall, base "
                               f"{_stats['base_x']:.0f} x {_stats['base_y']:.0f} mm")
            box.label(text=f"Wax: {_stats['ml']:.0f} ml, about {_stats['wax']:.0f} g")
            if props.mold_type == "SILICONE":
                box.label(text=f"Silicone: about {_stats['silicone']:.0f} ml")


class CANDLE_PT_size(_Panel, bpy.types.Panel):
    bl_label = "Shape & Size"
    bl_parent_id = "CANDLE_PT_main"

    def draw(self, context):
        props = _props(context)
        self.layout.prop(props, "base_shape")
        shape = props.base_shape
        if shape in STRETCHED or BASE_SHAPES[shape][2]:
            col = self.layout.column(align=True)
            if shape in STRETCHED:
                col.prop(props, "shape_stretch")
            if BASE_SHAPES[shape][2]:
                col.prop(props, "corner_round")
        col = self.layout.column(align=True)
        col.prop(props, "height")
        col.prop(props, "diameter", text="Diameter (mm)" if shape == "ROUND" else "Width (mm)")
        for name in ("top_scale", "taper_power", "top_round"):
            col.prop(props, name)
        row = self.layout.row()
        row.prop(props, "color", text="")
        row.prop(props, "show_wick")


class CANDLE_PT_ribs(_Panel, bpy.types.Panel):
    bl_label = "Ribs, Twist & Sway"
    bl_parent_id = "CANDLE_PT_main"

    def draw(self, context):
        props = _props(context)
        col = self.layout.column(align=True)
        for name in ("ribs", "rib_depth", "rib_fullness", "rib_lean"):
            col.prop(props, name)
        row = self.layout.row(align=True)
        row.prop(props, "fade_bottom")
        row.prop(props, "fade_top")
        col = self.layout.column(align=True)
        col.prop(props, "twist_turns")
        col.prop(props, "twist_focus")
        col = self.layout.column(align=True)
        for name in ("sway_angle", "sway_waves", "sway_phase", "sway_stagger"):
            col.prop(props, name)


class CANDLE_PT_waves(_Panel, bpy.types.Panel):
    bl_label = "Waves & Bulges"
    bl_parent_id = "CANDLE_PT_main"

    def draw(self, context):
        props = _props(context)
        col = self.layout.column(align=True)
        col.prop(props, "wave_mode", expand=True)
        for name in ("wave_amount", "wave_count", "wave_phase"):
            col.prop(props, name)
        if props.wave_mode == "PLANAR":
            col.prop(props, "wave_direction")
        col = self.layout.column(align=True)
        col.prop(props, "bulge_mode", expand=True)
        for name in ("bulge_amount", "bulge_count", "bulge_phase"):
            col.prop(props, name)


class CANDLE_PT_mold(_Panel, bpy.types.Panel):
    bl_label = "Mold"
    bl_parent_id = "CANDLE_PT_main"

    def draw(self, context):
        props = _props(context)
        layout = self.layout
        layout.prop(props, "mold_type", text="")
        col = layout.column(align=True)
        t = props.mold_type
        if t == "SILICONE":
            hint = ("Print master + sleeve in PLA, fine layers.",
                    "Slide sleeve onto the plate, pour silicone.")
            names = ("wick_diameter", "sil_wall", "sil_top", "sleeve_wall", "fit_clearance",
                     "plate_thickness", "step_height")
        elif t == "SPLIT":
            hint = ("Print both halves lying on their backs,",
                    "seam side up: no supports needed.")
            names = ("wick_diameter", "split_wall", "split_floor", "fastener")
        elif t == "WEDGE":
            hint = ("Print the wedges standing, pour end down,",
                    "the plug face up. Rubber bands hold it.")
            names = ("wick_diameter", "split_wall", "split_floor")
        elif t == "FLEX":
            hint = ("Print in TPU 95A, floor on the bed.",
                    "The rim lets it hang in a jar while pouring.")
            names = ("wick_diameter", "flex_wall", "mold_floor", "flange_width", "flange_thickness")
        elif t == "RIGID":
            hint = ("Print in PETG (PLA softens near 60 C).",
                    "Twist the cooled candle to unscrew it.")
            names = ("wick_diameter", "mold_wall", "mold_floor")
        else:
            hint, names = ("Exports the candle shape as-is.",), ()
        for name in names:
            col.prop(props, name)
        if t == "SPLIT":
            row = layout.row(align=True)
            row.prop(props, "split_auto", toggle=True)
            sub = row.row(align=True)
            sub.enabled = not props.split_auto
            sub.prop(props, "split_angle", text="Seam")
        if t == "WEDGE":
            row = layout.row(align=True)
            row.prop(props, "wedge_auto", toggle=True)
            sub = row.row(align=True)
            sub.enabled = not props.wedge_auto
            sub.prop(props, "wedge_count")
        if t in ("SPLIT", "WEDGE"):
            layout.prop(props, "show_locks")
        box = layout.box().column(align=True)
        for line in hint:
            box.label(text=line)
        if t == "SPLIT":
            res = _stats.get("split")
            if res is None:
                box.label(text="Checking whether it releases...", icon="TIME")
            elif res["ok"]:
                box.label(text=f"Releases cleanly (seam at {res['angle']:.0f} deg)", icon="CHECKMARK")
            else:
                box.label(text=f"Locks: {res['trapped']:.1f} mm undercut (red)", icon="ERROR")
                if props.twist_turns or props.sway_angle:
                    box.label(text="Twisting or swaying ribs always lock.")
                box.label(text="Try fewer, thinner or straight ribs,")
                box.label(text="the wedge mold, or Silicone or TPU.")
        if t == "WEDGE":
            res = _stats.get("wedge")
            if res is None:
                box.label(text="Checking whether it releases...", icon="TIME")
            elif res["ok"]:
                box.label(text=f"Releases cleanly in {res['pieces']} pieces", icon="CHECKMARK")
            else:
                box.label(text=f"Locks{' even' if props.wedge_auto else ''} in {res['pieces']} pieces: "
                               f"{res['trapped']:.1f} mm (red)", icon="ERROR")
                if props.wedge_auto:
                    box.label(text="Try shallower or fewer ribs,")
                    box.label(text="or use the Silicone or TPU mold.")
                else:
                    box.label(text="Try more pieces, or Auto Pieces.")
        if t in PRINT_MATERIAL:
            parts = _stats.get("print")
            if parts is None:
                box.label(text="Estimating print material...", icon="TIME")
            else:
                material, density = PRINT_MATERIAL[t]
                grams = [(PART_NAMES[name], print_grams(v, a, 1.0 if solid else props.infill / 100.0,
                                                        density)) for name, v, a, solid in parts]
                box.label(text=f"Print: about {sum(g for _, g in grams):.0f} g {material}",
                          icon="MOD_BUILD")
                if t == "WEDGE":  # one line, however many wedges
                    each = [g for n, g in grams if n.startswith("wedge")]
                    box.label(text=f"{len(each)} wedges {min(each):.0f}-{max(each):.0f} g each, "
                                   f"plug {grams[-1][1]:.0f} g")
                elif len(grams) > 1:
                    box.label(text=", ".join(f"{n} {g:.0f} g" for n, g in grams))
            box.prop(props, "infill", text="Infill for estimate")
        if t == "RIGID":
            p, _ = _snapshot(props)
            issues = rigid_mold_check(p)
            if issues:
                box.label(text="Won't release: " + ", ".join(issues), icon="ERROR")
                box.label(text="Use Silicone or TPU for this shape.")
            else:
                box.label(text="Shape can unscrew from a rigid mold", icon="CHECKMARK")
        layout.operator("candle.build_mold", icon="MOD_SOLIDIFY")


class CANDLE_PT_export(_Panel, bpy.types.Panel):
    bl_label = "Export"
    bl_parent_id = "CANDLE_PT_main"

    def draw(self, context):
        props = _props(context)
        layout = self.layout
        layout.prop(props, "design_name")
        layout.prop(props, "export_dir")
        layout.prop(props, "export_quality")
        layout.prop(props, "export_candle")
        layout.prop(props, "open_bambu")
        layout.operator("candle.export", icon="EXPORT")
        layout.operator("candle.load_design", icon="IMPORT")


class CANDLE_PT_quality(_Panel, bpy.types.Panel):
    bl_label = "Viewport Detail"
    bl_parent_id = "CANDLE_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        props = _props(context)
        col = self.layout.column(align=True)
        col.prop(props, "preview_segments")
        col.prop(props, "preview_step")


classes = (
    CandleProps,
    CANDLE_OT_generate, CANDLE_OT_reset_preset, CANDLE_OT_randomize,
    CANDLE_OT_build_mold, CANDLE_OT_export, CANDLE_OT_load_design,
    CANDLE_PT_main, CANDLE_PT_size, CANDLE_PT_ribs, CANDLE_PT_waves,
    CANDLE_PT_mold, CANDLE_PT_export, CANDLE_PT_quality,
)


_REGISTRY = "candle_studio_classes"  # remembers the last registration across Text Editor re-runs


def _unregister(cls_list):
    if bpy.app.timers.is_registered(_mold_timer):
        bpy.app.timers.unregister(_mold_timer)
    if hasattr(bpy.types.Scene, "candle_studio"):
        del bpy.types.Scene.candle_studio
    for cls in reversed(cls_list):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass


def register():
    _unregister(bpy.app.driver_namespace.pop(_REGISTRY, ()))
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.candle_studio = PointerProperty(type=CandleProps)
    bpy.app.driver_namespace[_REGISTRY] = classes


def unregister():
    _unregister(bpy.app.driver_namespace.pop(_REGISTRY, classes))


if __name__ == "__main__":
    register()
    try:
        bpy.ops.candle.generate()
    except RuntimeError:
        pass
