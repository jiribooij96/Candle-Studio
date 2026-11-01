"""Shared helpers for the Candle Studio tests.

The tests run inside Blender (they need bpy and mathutils); use run_tests.py.
"""

import importlib.util
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.dont_write_bytecode = True  # keep __pycache__ out of the repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "candle_studio.py")


def out_dir():
    """Scratch folder passed after Blender's '--' (run_tests.py makes a temporary one)."""
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    path = args[0] if args else os.path.join(ROOT, "test_output")
    os.makedirs(path, exist_ok=True)
    return path


def load_addon(path=ADDON):
    spec = importlib.util.spec_from_file_location("candle_studio", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shape(cs, preset=None, **overrides):
    """Shape settings: defaults, then a preset, then overrides."""
    p = SimpleNamespace(**cs.SHAPE_DEFAULTS)
    for k, v in (cs.PRESETS[preset][2] if preset else {}).items():
        setattr(p, k, v)
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def mold(cs, **overrides):
    m = SimpleNamespace(**cs.MOLD_DEFAULTS)
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class Failures(list):
    """Collects failed checks; finish() fails the Blender run if there were any."""

    def expect(self, ok, label, detail=""):
        print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail else ""))
        if not ok:
            self.append(label)
        return ok

    def finish(self):
        print(f"\n{len(self)} failure(s)" + (": " + ", ".join(self) if self else ""))
        if self:
            raise AssertionError(f"{len(self)} check(s) failed")


def mesh_problems(mesh, overlap=True):
    """Why a mesh isn't a clean printable solid ([] if it is): open or
    non-manifold edges, inside-out, degenerate or self-intersecting triangles."""
    from mathutils.bvhtree import BVHTree

    tris = mesh.triangles()
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = e[:, 0] * (len(mesh.verts) + 1) + e[:, 1]
    rkey = e[:, 1] * (len(mesh.verts) + 1) + e[:, 0]
    problems = []
    if len(np.unique(key)) != len(key) or not np.isin(rkey, key).all():
        problems.append("not manifold")
    if mesh.volume() <= 0:
        problems.append("inside out")
    v = mesh.verts[tris]
    nrm = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    area = np.linalg.norm(nrm, axis=1) / 2
    if (area < 1e-9).any():
        problems.append(f"{int((area < 1e-9).sum())} degenerate")
    if overlap:
        tree = BVHTree.FromPolygons(mesh.verts.tolist(), tris.tolist(), epsilon=0.0)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        hits = 0
        for i, j in tree.overlap(tree):
            if set(tris[i]) & set(tris[j]):  # neighbours touching at a shared vertex
                continue
            coplanar = abs(np.dot(nrm[i], nrm[j])) > 0.9999 and abs(np.dot(nrm[i], v[j, 0] - v[i, 0])) < 1e-4
            pi = {tuple(x) for x in v[i].round(4)}
            pj = {tuple(x) for x in v[j].round(4)}
            if not (coplanar and pi & pj):  # same-plane boolean slivers touching at a corner are fine
                hits += 1
        if hits:
            problems.append(f"{hits} self-intersections")
    return problems


def check_mesh(fails, mesh, label, overlap=True):
    problems = mesh_problems(mesh, overlap)
    return fails.expect(not problems, label, ", ".join(problems) or f"{len(mesh.triangles())} tris")


class RecordingLayout:
    """Stands in for a panel layout: checks property names, icons and
    operators exist, so a typo in a panel fails the test instead of the UI."""

    def __init__(self):
        import bpy
        self._bpy = bpy
        self._icons = set(bpy.types.UILayout.bl_rna.functions["operator"]
                          .parameters["icon"].enum_items.keys())

    def __getattr__(self, name):
        return lambda *a, **k: self._call(name, a, k)

    def _call(self, name, a, k):
        if "icon" in k and k["icon"] not in self._icons:
            raise ValueError("unknown icon " + k["icon"])
        if name == "prop" and a[1] not in a[0].bl_rna.properties:
            raise ValueError("unknown property " + a[1])
        if name == "operator":
            mod, op = a[0].split(".")
            getattr(getattr(self._bpy.ops, mod), op).get_rna_type()
        return self


def draw_panels(cs, scene):
    import bpy
    ctx = SimpleNamespace(scene=scene)
    for cls in cs.classes:
        if issubclass(cls, bpy.types.Panel):
            cls.draw(SimpleNamespace(layout=RecordingLayout()), ctx)


def read_stl(path):
    """Binary STL -> (triangle count, vertices); also checks the file size matches."""
    with open(path, "rb") as fh:
        n = int.from_bytes(fh.read(84)[80:84], "little")
    assert os.path.getsize(path) == 84 + 50 * n, path
    d = np.fromfile(path, dtype=[("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")], offset=84)
    return n, d["v"].reshape(-1, 3)
