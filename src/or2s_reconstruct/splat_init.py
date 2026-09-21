"""CPU sparse Gaussian PLY init from Capture poses + image colors.

Used when nerfstudio splatfacto / CUDA gsplat cannot run (no GPU, no torch).
Produces a gsplat/nerfstudio-compatible Gaussian PLY (required fields) so
scene_pkg layout can be filled. Marked as stub/init in sidecar metadata.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from or2s_reconstruct.math3d import T_from_pose

# Spherical-harmonics DC scale (Inria / nerfstudio)
_SH_C0 = 0.28209479177387814


def _inv_sigmoid(y: float) -> float:
    y = min(max(y, 1e-4), 1.0 - 1e-4)
    return math.log(y / (1.0 - y))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_gaussian_ply(
    path: Path,
    xyz: np.ndarray,
    rgb: np.ndarray,
    *,
    scales: np.ndarray | None = None,
    opacities: np.ndarray | None = None,
) -> int:
    """Write binary little-endian PLY with 3DGS vertex properties."""
    n = int(xyz.shape[0])
    if scales is None:
        scales = np.full((n, 3), math.log(0.02), dtype=np.float32)
    if opacities is None:
        opacities = np.full((n,), _inv_sigmoid(0.7), dtype=np.float32)

    # SH DC from RGB in [0,1]
    f_dc = ((rgb.astype(np.float64) - 0.5) / _SH_C0).astype(np.float32)
    # Identity quaternion wxyz stored as rot_0..3 (nerfstudio: w,x,y,z)
    rots = np.zeros((n, 4), dtype=np.float32)
    rots[:, 0] = 1.0
    normals = np.zeros((n, 3), dtype=np.float32)

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float nx\n"
        "property float ny\n"
        "property float nz\n"
        "property float f_dc_0\n"
        "property float f_dc_1\n"
        "property float f_dc_2\n"
        "property float opacity\n"
        "property float scale_0\n"
        "property float scale_1\n"
        "property float scale_2\n"
        "property float rot_0\n"
        "property float rot_1\n"
        "property float rot_2\n"
        "property float rot_3\n"
        "end_header\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        for i in range(n):
            f.write(
                struct.pack(
                    "<18f",
                    float(xyz[i, 0]),
                    float(xyz[i, 1]),
                    float(xyz[i, 2]),
                    float(normals[i, 0]),
                    float(normals[i, 1]),
                    float(normals[i, 2]),
                    float(f_dc[i, 0]),
                    float(f_dc[i, 1]),
                    float(f_dc[i, 2]),
                    float(opacities[i]),
                    float(scales[i, 0]),
                    float(scales[i, 1]),
                    float(scales[i, 2]),
                    float(rots[i, 0]),
                    float(rots[i, 1]),
                    float(rots[i, 2]),
                    float(rots[i, 3]),
                )
            )
    return n


def init_gaussians_from_poses(
    ingest_dir: Path | str,
    out_ply: Path | str,
    *,
    stride: int = 5,
    rays_per_frame: int = 24,
    depth_m: float = 2.5,
    also_camera_centers: bool = True,
) -> dict[str, Any]:
    """Sparse init: camera centers + a few back-projected pixels per frame."""
    ingest_dir = Path(ingest_dir).resolve()
    out_ply = Path(out_ply).resolve()
    frames = _load_jsonl(ingest_dir / "frames.jsonl")
    poses = _load_jsonl(ingest_dir / "poses.jsonl")
    cameras = json.loads((ingest_dir / "cameras.json").read_text(encoding="utf-8"))
    K = cameras["K"]
    fx, fy, cx, cy = float(K[0]), float(K[4]), float(K[2]), float(K[5])
    w, h = int(cameras["image_size"][0]), int(cameras["image_size"][1])

    n = min(len(frames), len(poses))
    xyz_list: list[np.ndarray] = []
    rgb_list: list[np.ndarray] = []

    # Deterministic pixel sample grid
    cols = max(2, int(math.sqrt(rays_per_frame)))
    rows = max(2, (rays_per_frame + cols - 1) // cols)
    us = np.linspace(w * 0.15, w * 0.85, cols)
    vs = np.linspace(h * 0.15, h * 0.85, rows)
    uu, vv = np.meshgrid(us, vs)
    uu = uu.ravel()[:rays_per_frame]
    vv = vv.ravel()[:rays_per_frame]

    for i in range(0, n, max(1, stride)):
        fr, pose = frames[i], poses[i]
        T = T_from_pose(pose["position_m"], pose["orientation_xyzw"])
        R, t = T[:3, :3], T[:3, 3]
        img_path = ingest_dir / fr["image_path"]
        try:
            with Image.open(img_path) as im:
                arr = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
        except Exception:
            arr = np.full((h, w, 3), 0.5, dtype=np.float32)

        if also_camera_centers:
            # slight inward offset along optical +Z (RDF forward)
            center = t + R @ np.array([0.0, 0.0, 0.15])
            # mean image color
            mean_rgb = arr.reshape(-1, 3).mean(axis=0)
            xyz_list.append(center.astype(np.float64))
            rgb_list.append(mean_rgb.astype(np.float64))

        for u, v in zip(uu, vv):
            ui, vi = int(round(u)), int(round(v))
            ui = min(max(ui, 0), w - 1)
            vi = min(max(vi, 0), arr.shape[0] - 1)
            color = arr[vi, ui]
            # ray in camera RDF
            x = (u - cx) / fx
            y = (v - cy) / fy
            d_cam = np.array([x, y, 1.0], dtype=np.float64)
            d_cam = d_cam / np.linalg.norm(d_cam)
            p = t + R @ (d_cam * depth_m)
            xyz_list.append(p)
            rgb_list.append(color.astype(np.float64))

    xyz = np.stack(xyz_list, axis=0)
    rgb = np.clip(np.stack(rgb_list, axis=0), 0.0, 1.0)
    # Unique-ish by rounding to reduce duplicates from revisits
    keys = np.round(xyz, 3)
    _, uniq_idx = np.unique(keys, axis=0, return_index=True)
    xyz, rgb = xyz[uniq_idx], rgb[uniq_idx]

    scales = np.full((xyz.shape[0], 3), math.log(0.03), dtype=np.float32)
    count = write_gaussian_ply(out_ply, xyz.astype(np.float32), rgb.astype(np.float32), scales=scales)

    meta = {
        "schema": "or2s_reconstruct.splat_init/0.1",
        "method": "sparse_pose_color_init",
        "trained": False,
        "train_backend": None,
        "skip_reason": "no_GPU_no_torch_splatfacto_skipped",
        "gaussian_count": count,
        "ply_path": str(out_ply),
        "stride": stride,
        "rays_per_frame": rays_per_frame,
        "assumed_depth_m": depth_m,
        "note": (
            "Placeholder/valid 3DGS PLY (SH-DC colors from pixels, fixed scales). "
            "Not optimized; synthetic Capture images are weak photoreal. "
            "Replace with nerfstudio splatfacto / gsplat train on a CUDA box."
        ),
    }
    meta_path = out_ply.with_suffix(".init.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta
