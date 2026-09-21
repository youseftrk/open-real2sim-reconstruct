"""CLI for or2s-reconstruct."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reconstruct",
        description="Open Real2Sim reconstruction tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser(
        "ingest",
        help="Ingest a Capture bag session into a normalized intermediate",
    )
    p_ingest.add_argument("session_dir", type=Path, help="Capture session directory")
    p_ingest.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for summary.json, images/, poses.jsonl, cameras.json",
    )

    p_dataset = sub.add_parser(
        "dataset",
        help="Build nerfstudio-style transforms.json from an ingest directory",
    )
    p_dataset.add_argument("ingest_dir", type=Path)
    p_dataset.add_argument("--out", type=Path, required=True)
    p_dataset.add_argument(
        "--symlink-images",
        action="store_true",
        help="Symlink images instead of copying",
    )
    p_dataset.add_argument("--max-frames", type=int, default=None)

    p_train = sub.add_parser(
        "train",
        help="Train 3DGS (splatfacto if available) or CPU sparse init fallback",
    )
    p_train.add_argument("ingest_dir", type=Path)
    p_train.add_argument("--out", type=Path, required=True, help="Dir for gaussians.ply")
    p_train.add_argument(
        "--method",
        choices=("auto", "splatfacto", "sparse_init"),
        default="auto",
    )
    p_train.add_argument("--stride", type=int, default=5)
    p_train.add_argument("--rays-per-frame", type=int, default=24)

    p_export = sub.add_parser(
        "export",
        help="Assemble frozen scene_pkg from ingest (+ optional gaussians.ply)",
    )
    p_export.add_argument("ingest_dir", type=Path)
    p_export.add_argument("--out", type=Path, required=True)
    p_export.add_argument("--gaussians", type=Path, default=None)
    p_export.add_argument("--dataset-dir", type=Path, default=None)
    p_export.add_argument("--train-meta", type=Path, default=None)

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(args.session_dir, args.out)
    if args.command == "dataset":
        return _cmd_dataset(args)
    if args.command == "train":
        return _cmd_train(args)
    if args.command == "export":
        return _cmd_export(args)
    parser.error(f"unknown command {args.command}")
    return 2


def _cmd_ingest(session_dir: Path, out_dir: Path) -> int:
    from or2s_reconstruct.ingest import ingest_session

    if not session_dir.exists():
        print(f"error: session dir not found: {session_dir}", file=sys.stderr)
        return 1
    result = ingest_session(session_dir, out_dir)
    summary = {
        "session_id": result.session_id,
        "frame_count": result.frame_count,
        "pose_count": result.pose_count,
        "duration_s": result.duration_s,
        "has_pose": result.has_pose,
        "has_intrinsics": result.has_intrinsics,
        "image_size": result.image_size,
        "K": result.K,
        "reader": result.reader,
        "issues": result.issues,
        "out_dir": result.out_dir,
        "colmap": "deferred",
        "pose_source": "/or2s/pose" if result.has_pose else None,
    }
    print(json.dumps(summary, indent=2))
    return 0 if result.frame_count > 0 else 2


def _cmd_dataset(args) -> int:
    from or2s_reconstruct.dataset import build_nerfstudio_dataset

    meta = build_nerfstudio_dataset(
        args.ingest_dir,
        args.out,
        copy_images=not args.symlink_images,
        max_frames=args.max_frames,
    )
    print(json.dumps(meta, indent=2))
    return 0


def _probe_cuda_torch() -> tuple[bool, str]:
    try:
        import torch  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return False, f"torch not importable: {exc!r}"
    if not torch.cuda.is_available():
        return False, f"torch {torch.__version__} present but CUDA unavailable"
    return True, f"torch {torch.__version__} cuda={torch.version.cuda}"


def _cmd_train(args) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ply_path = out_dir / "gaussians.ply"
    method = args.method

    cuda_ok, cuda_msg = _probe_cuda_torch()
    skip_reason = None
    train_meta: dict

    if method == "auto":
        method = "splatfacto" if cuda_ok else "sparse_init"

    if method == "splatfacto":
        if not cuda_ok:
            skip_reason = f"splatfacto skipped ({cuda_msg}); falling back to sparse_init"
            method = "sparse_init"
        else:
            # Intentionally not pulling nerfstudio here — huge install; document.
            skip_reason = (
                "splatfacto requested and CUDA available, but nerfstudio install "
                "is deferred on this host (prefer lean path). Using sparse_init."
            )
            method = "sparse_init"

    if method == "sparse_init":
        from or2s_reconstruct.splat_init import init_gaussians_from_poses

        train_meta = init_gaussians_from_poses(
            args.ingest_dir,
            ply_path,
            stride=args.stride,
            rays_per_frame=args.rays_per_frame,
        )
        if skip_reason:
            train_meta["skip_reason"] = skip_reason
            train_meta["cuda_probe"] = cuda_msg
        (out_dir / "train_meta.json").write_text(
            json.dumps(train_meta, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(train_meta, indent=2))
        return 0

    print(f"error: unsupported method {method}", file=sys.stderr)
    return 2


def _cmd_export(args) -> int:
    from or2s_reconstruct.export_scene import export_scene_pkg

    train_meta = None
    if args.train_meta and Path(args.train_meta).is_file():
        train_meta = json.loads(Path(args.train_meta).read_text(encoding="utf-8"))
    result = export_scene_pkg(
        args.ingest_dir,
        args.out,
        gaussians_ply=args.gaussians,
        dataset_dir=args.dataset_dir,
        train_meta=train_meta,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
