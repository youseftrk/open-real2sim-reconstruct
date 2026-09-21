"""Convert ingest intermediate → nerfstudio-style transforms.json (+ COLMAP-like notes)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from or2s_reconstruct.math3d import T_from_pose


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_nerfstudio_dataset(
    ingest_dir: Path | str,
    out_dir: Path | str,
    *,
    copy_images: bool = True,
    max_frames: int | None = None,
) -> dict[str, Any]:
    """Write a nerfstudio-compatible dataset from Capture poses + cameras.

    Pose convention in Capture: ``T_world_cam`` as position + quat xyzw of the
    camera/device in the Capture world (synthetic = Z-up orbit). Nerfstudio
    expects ``transform_matrix`` = camera-to-world 4x4 (c2w).
    """
    ingest_dir = Path(ingest_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    images_out = out_dir / "images"
    images_out.mkdir(parents=True, exist_ok=True)

    cameras = json.loads((ingest_dir / "cameras.json").read_text(encoding="utf-8"))
    frames = _load_jsonl(ingest_dir / "frames.jsonl")
    poses = _load_jsonl(ingest_dir / "poses.jsonl")
    summary = json.loads((ingest_dir / "summary.json").read_text(encoding="utf-8"))

    if not frames:
        raise RuntimeError(f"no frames in {ingest_dir}")
    if not poses:
        raise RuntimeError(f"no poses in {ingest_dir}; Capture poses required for v0 path A")

    n = min(len(frames), len(poses))
    if max_frames is not None:
        n = min(n, max_frames)
    frames, poses = frames[:n], poses[:n]

    K = cameras.get("K") or summary.get("K")
    if not K or len(K) < 9:
        raise RuntimeError("intrinsics K missing")
    fx, fy, cx, cy = float(K[0]), float(K[4]), float(K[2]), float(K[5])
    w, h = cameras.get("image_size") or summary.get("image_size") or [0, 0]
    w, h = int(w), int(h)

    ns_frames: list[dict[str, Any]] = []
    for fr, pose in zip(frames, poses):
        src_rel = fr.get("image_path")
        if not src_rel:
            continue
        src = ingest_dir / src_rel
        name = Path(src_rel).name
        dst = images_out / name
        if copy_images:
            if src.is_file():
                shutil.copy2(src, dst)
            else:
                continue
        elif not dst.is_file() and src.is_file():
            # symlink for space
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src)

        T_c2w = T_from_pose(pose["position_m"], pose["orientation_xyzw"])
        ns_frames.append(
            {
                "file_path": f"images/{name}",
                "transform_matrix": T_c2w.tolist(),
                "log_time_ns": fr.get("log_time_ns"),
                "pose_index": pose.get("index"),
                "frame_index": fr.get("index"),
            }
        )

    transforms = {
        "camera_model": "OPENCV",
        "fl_x": fx,
        "fl_y": fy,
        "cx": cx,
        "cy": cy,
        "w": w,
        "h": h,
        "k1": 0.0,
        "k2": 0.0,
        "p1": 0.0,
        "p2": 0.0,
        "coordinate_convention_note": (
            "Capture RDF_optical labeled; synthetic Capture poses are Z-up "
            "walkaround c2w (position + quat xyzw). Used as nerfstudio c2w."
        ),
        "source_session_id": summary.get("session_id"),
        "pose_source": summary.get("pose_source") or "/or2s/pose",
        "frames": ns_frames,
    }
    (out_dir / "transforms.json").write_text(
        json.dumps(transforms, indent=2) + "\n", encoding="utf-8"
    )

    meta = {
        "schema": "or2s_reconstruct.dataset/0.1",
        "format": "nerfstudio_transforms",
        "ingest_dir": str(ingest_dir),
        "out_dir": str(out_dir),
        "frame_count": len(ns_frames),
        "image_size": [w, h],
        "intrinsics": {"fl_x": fx, "fl_y": fy, "cx": cx, "cy": cy},
    }
    (out_dir / "dataset_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return meta
