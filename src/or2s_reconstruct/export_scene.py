"""Assemble frozen scene_pkg layout from ingest + splat + proxies."""

from __future__ import annotations

import json
import math
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from or2s_reconstruct import __version__
from or2s_reconstruct.math3d import IDENTITY_4X4, T_from_pose
from or2s_reconstruct.splat_init import init_gaussians_from_poses, write_gaussian_ply


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_xyzrgb_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> int:
    n = int(xyz.shape[0])
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb_u8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        for i in range(n):
            f.write(
                struct.pack(
                    "<fffBBB",
                    float(xyz[i, 0]),
                    float(xyz[i, 1]),
                    float(xyz[i, 2]),
                    int(rgb_u8[i, 0]),
                    int(rgb_u8[i, 1]),
                    int(rgb_u8[i, 2]),
                )
            )
    return n


def _axis_aligned_box_obj(path: Path, mins: np.ndarray, maxs: np.ndarray) -> int:
    """Write a coarse axis-aligned room shell OBJ (12 tris). Returns triangle count."""
    x0, y0, z0 = mins.tolist()
    x1, y1, z1 = maxs.tolist()
    # Floor at z≈0 preferred; clamp floor to min z but allow slight pad
    verts = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    # 1-based faces, outward-ish
    faces = [
        (1, 2, 3),
        (1, 3, 4),  # bottom
        (5, 7, 6),
        (5, 8, 7),  # top
        (1, 5, 6),
        (1, 6, 2),  # y0
        (2, 6, 7),
        (2, 7, 3),  # x1
        (3, 7, 8),
        (3, 8, 4),  # y1
        (4, 8, 5),
        (4, 5, 1),  # x0
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# or2s-reconstruct coarse collision room shell (meters, Z-up)", "o room_shell"]
    for v in verts:
        lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    for a, b, c in faces:
        lines.append(f"f {a} {b} {c}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(faces)


def build_proxy_pointcloud(
    ingest_dir: Path,
    out_ply: Path,
    *,
    stride: int = 10,
    grid: int = 8,
    depth_m: float = 2.5,
) -> dict[str, Any]:
    frames = _load_jsonl(ingest_dir / "frames.jsonl")
    poses = _load_jsonl(ingest_dir / "poses.jsonl")
    cameras = json.loads((ingest_dir / "cameras.json").read_text(encoding="utf-8"))
    K = cameras["K"]
    fx, fy, cx, cy = float(K[0]), float(K[4]), float(K[2]), float(K[5])
    w, h = int(cameras["image_size"][0]), int(cameras["image_size"][1])
    n = min(len(frames), len(poses))

    us = np.linspace(w * 0.1, w * 0.9, grid)
    vs = np.linspace(h * 0.1, h * 0.9, grid)
    uu, vv = np.meshgrid(us, vs)
    uu, vv = uu.ravel(), vv.ravel()

    xyz_list, rgb_list = [], []
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
        # camera center marker
        xyz_list.append(t.copy())
        rgb_list.append(arr.reshape(-1, 3).mean(axis=0))
        for u, v in zip(uu, vv):
            ui, vi = int(round(u)), int(round(v))
            ui = min(max(ui, 0), w - 1)
            vi = min(max(vi, 0), arr.shape[0] - 1)
            x = (u - cx) / fx
            y = (v - cy) / fy
            d = np.array([x, y, 1.0], dtype=np.float64)
            d /= np.linalg.norm(d)
            xyz_list.append(t + R @ (d * depth_m))
            rgb_list.append(arr[vi, ui].astype(np.float64))

    xyz = np.stack(xyz_list)
    rgb = np.clip(np.stack(rgb_list), 0, 1)
    count = _write_xyzrgb_ply(out_ply, xyz, rgb)
    return {"point_count": count, "path": str(out_ply)}


def export_scene_pkg(
    ingest_dir: Path | str,
    out_dir: Path | str,
    *,
    gaussians_ply: Path | str | None = None,
    dataset_dir: Path | str | None = None,
    train_meta: dict[str, Any] | None = None,
    capture_rdf_to_world: np.ndarray | None = None,
) -> dict[str, Any]:
    """Build scene_pkg matching PACKAGE_CONTRACT.md §B (frozen)."""
    ingest_dir = Path(ingest_dir).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = json.loads((ingest_dir / "summary.json").read_text(encoding="utf-8"))
    session_id = summary["session_id"]
    poses = _load_jsonl(ingest_dir / "poses.jsonl")
    cameras = json.loads((ingest_dir / "cameras.json").read_text(encoding="utf-8"))

    # --- visual/splat ---
    splat_dir = out_dir / "visual" / "splat"
    splat_dir.mkdir(parents=True, exist_ok=True)
    dst_gauss = splat_dir / "gaussians.ply"
    if gaussians_ply and Path(gaussians_ply).is_file():
        shutil.copy2(gaussians_ply, dst_gauss)
        splat_meta = train_meta or {"method": "external", "trained": True}
    else:
        splat_meta = init_gaussians_from_poses(ingest_dir, dst_gauss, stride=5, rays_per_frame=24)
        # also keep init json next to ply
        init_src = Path(str(dst_gauss) + ".init.json") if False else dst_gauss.with_suffix(".init.json")
        # init_gaussians writes alongside; move into splat dir if needed
        if init_src.is_file() and init_src.parent != splat_dir:
            shutil.move(str(init_src), splat_dir / "gaussians.init.json")
        elif dst_gauss.with_suffix(".init.json").is_file():
            pass

    (splat_dir / "train_config.yaml").write_text(
        "# or2s-reconstruct splat train config (stub)\n"
        f"method: {splat_meta.get('method', 'unknown')}\n"
        f"trained: {bool(splat_meta.get('trained', False))}\n"
        f"skip_reason: {splat_meta.get('skip_reason', '')}\n"
        f"gaussian_count: {splat_meta.get('gaussian_count', 'unknown')}\n",
        encoding="utf-8",
    )
    (splat_dir / "render_meta.json").write_text(
        json.dumps(
            {
                "schema": "or2s_reconstruct.render_meta/0.1",
                "trained": bool(splat_meta.get("trained", False)),
                "method": splat_meta.get("method"),
                "skip_reason": splat_meta.get("skip_reason"),
                "gaussian_count": splat_meta.get("gaussian_count"),
                "note": splat_meta.get("note"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # --- visual/proxy ---
    proxy_dir = out_dir / "visual" / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    proxy_info = build_proxy_pointcloud(ingest_dir, proxy_dir / "points.ply", stride=8, grid=6)
    (proxy_dir / "README.md").write_text(
        "# visual/proxy\n\n"
        "Required v0 proxy for Sim Runtime stubs that do not rasterize 3DGS.\n"
        f"- `points.ply`: {proxy_info['point_count']} XYZ+RGB points from "
        "Capture poses + sampled pixels (assumed depth).\n",
        encoding="utf-8",
    )

    # --- collision ---
    positions = np.array([p["position_m"] for p in poses], dtype=np.float64)
    mins = positions.min(axis=0) - np.array([0.8, 0.8, 0.1])
    maxs = positions.max(axis=0) + np.array([0.8, 0.8, 0.8])
    # Prefer floor near z=0: if camera height ~1.4, extend floor down
    mins[2] = min(float(mins[2]), 0.0)
    maxs[2] = max(float(maxs[2]), 2.2)
    coll_path = out_dir / "collision" / "room_shell.obj"
    tri_count = _axis_aligned_box_obj(coll_path, mins, maxs)

    # --- transforms ---
    M = capture_rdf_to_world if capture_rdf_to_world is not None else IDENTITY_4X4
    M = np.asarray(M, dtype=np.float64)
    xf_dir = out_dir / "transforms"
    xf_dir.mkdir(parents=True, exist_ok=True)
    rdf_doc = {
        "schema": "or2s_reconstruct.capture_rdf_to_world/0.1",
        "units": "m",
        "from": "capture_RDF_optical",
        "to": "export_world_RH_Z_up",
        "matrix_4x4_row_major": M.tolist(),
        "note": (
            "Synthetic Capture demo poses are already authored as Z-up walkaround "
            "c2w; matrix is identity for this package. Real phone RDF optical bags "
            "should use the RDF→Z-up (Y-forward) basis change."
        ),
    }
    (xf_dir / "capture_rdf_to_world.json").write_text(
        json.dumps(rdf_doc, indent=2) + "\n", encoding="utf-8"
    )
    (xf_dir / "world_frame.json").write_text(
        json.dumps(
            {
                "convention": "right_handed_z_up",
                "up_axis": "z",
                "floor_z": 0.0,
                "gravity_dir": [0, 0, -1],
                "units": "m",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # bbox from positions + shell
    bbox = [
        float(mins[0]),
        float(mins[1]),
        float(mins[2]),
        float(maxs[0]),
        float(maxs[1]),
        float(maxs[2]),
    ]
    spawn = [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1],
    ]
    # place spawn near origin on floor, facing +Y
    spawn[0][3] = 0.0
    spawn[1][3] = 0.0
    spawn[2][3] = 0.0

    scene = {
        "package_version": "0.1.0-draft",
        "scene_id": f"demo_30s_{session_id[:8]}",
        "source_session_id": session_id,
        "units": "m",
        "world_frame": {
            "convention": "right_handed_z_up",
            "up_axis": "z",
            "floor_z": 0.0,
            "gravity_dir": [0, 0, -1],
            "capture_rdf_to_world_4x4": M.tolist(),
            "note": rdf_doc["note"],
        },
        "visual": {
            "primary": "3dgs",
            "splat_path": "visual/splat/gaussians.ply",
            "proxy_path": "visual/proxy/",
            "bbox_xyz": bbox,
            "splat_trained": bool(splat_meta.get("trained", False)),
            "splat_method": splat_meta.get("method"),
        },
        "collision": {
            "mesh_path": "collision/room_shell.obj",
            "triangle_count": tri_count,
            "wireframe_source": "collision_mesh",
        },
        "synthetic_streams": {
            "rgb": {"source": "proxy_sim"},
            "depth": {
                "source": "proxy_sim",
                "units": "m",
                "encoding_hint": "float32_meters",
            },
            "point_cloud": {"source": "proxy_sim", "frame": "camera"},
            "wireframe": {"source": "collision_mesh"},
            "default_camera_path": "sensors_synth/default_rgbd_camera.json",
        },
        "robot_spawn": {
            "T_world_spawn": spawn,
            "clearance_radius_m": 0.5,
            "note": "Unitree-class first agent is Sim Runtime's call; we export meters + frame",
        },
        "qa": {
            "capture_tier": "cheap",
            "metrics_path": "qa/heldout_metrics.json",
            "splat_is_stub": not bool(splat_meta.get("trained", False)),
        },
    }
    (out_dir / "scene.json").write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")

    # materials
    mat_dir = out_dir / "materials"
    mat_dir.mkdir(parents=True, exist_ok=True)
    (mat_dir / "README.md").write_text(
        "# materials\n\nv0: hero visuals via splat; collision untextured.\n",
        encoding="utf-8",
    )

    # sensors_synth
    sens = out_dir / "sensors_synth"
    sens.mkdir(parents=True, exist_ok=True)
    K = cameras.get("K") or []
    (sens / "default_rgbd_camera.json").write_text(
        json.dumps(
            {
                "model": "pinhole",
                "width": cameras["image_size"][0],
                "height": cameras["image_size"][1],
                "fx": K[0] if K else 280.0,
                "fy": K[4] if len(K) > 4 else 280.0,
                "cx": K[2] if len(K) > 2 else 160.0,
                "cy": K[5] if len(K) > 5 else 120.0,
                "frame": "camera_rgb",
                "convention": "RDF_optical",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # provenance
    prov = out_dir / "provenance"
    prov.mkdir(parents=True, exist_ok=True)
    (prov / "source_session_id.txt").write_text(session_id + "\n", encoding="utf-8")
    (prov / "tool_versions.json").write_text(
        json.dumps(
            {
                "or2s_reconstruct": __version__,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "train_meta": splat_meta,
                "dataset_dir": str(dataset_dir) if dataset_dir else None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (prov / "licenses.json").write_text(
        json.dumps(
            {
                "package": "Apache-2.0",
                "clean_room": True,
                "dependencies_note": (
                    "mcap, foxglove-schemas-protobuf, Pillow, numpy — see repo pins"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # optional capture manifest copy
    session_path = Path(summary.get("session_path", ""))
    man = session_path / "manifest.json"
    if man.is_file():
        shutil.copy2(man, prov / "capture_manifest_copy.json")

    # qa
    qa = out_dir / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "heldout_metrics.json").write_text(
        json.dumps(
            {
                "status": "skipped",
                "reason": splat_meta.get("skip_reason")
                or "no trained splat; synthetic imagery",
                "psnr": None,
                "ssim": None,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (qa / "mesh_stats.json").write_text(
        json.dumps(
            {
                "collision_triangles": tri_count,
                "bbox_xyz": bbox,
                "proxy_points": proxy_info["point_count"],
                "gaussian_count": splat_meta.get("gaussian_count"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = {
        "out_dir": str(out_dir),
        "scene_id": scene["scene_id"],
        "source_session_id": session_id,
        "gaussian_count": splat_meta.get("gaussian_count"),
        "proxy_points": proxy_info["point_count"],
        "collision_triangles": tri_count,
        "splat_trained": bool(splat_meta.get("trained", False)),
        "splat_method": splat_meta.get("method"),
        "skip_reason": splat_meta.get("skip_reason"),
    }
    (out_dir / "export_summary.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result
