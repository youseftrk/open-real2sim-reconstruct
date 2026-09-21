"""Ingest Capture bag v0 sessions into a normalized intermediate.

Prefers ``or2s_capture.read_session`` when importable; otherwise falls back to
mcap + foxglove protobuf schemas (same topics as CAPTURE_BAG_v0).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

TOPIC_RGB = "/or2s/rgb/image"
TOPIC_CAMERA_INFO = "/or2s/rgb/camera_info"
TOPIC_POSE = "/or2s/pose"


@dataclass
class FrameRecord:
    index: int
    log_time_ns: int
    publish_time_ns: int
    frame_id: str
    encoding: str
    width: int | None
    height: int | None
    image_path: str | None
    data_nbytes: int


@dataclass
class PoseRecord:
    index: int
    log_time_ns: int
    publish_time_ns: int
    frame_id: str
    position_m: list[float]
    orientation_xyzw: list[float]


@dataclass
class IngestResult:
    session_id: str
    session_path: str
    out_dir: str
    frame_count: int
    pose_count: int
    duration_s: float | None
    has_pose: bool
    has_intrinsics: bool
    image_size: list[int] | None
    K: list[float] | None
    distortion: list[float] | None
    frames: list[FrameRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    reader: str = "unknown"

    def summary_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_path": self.session_path,
            "out_dir": self.out_dir,
            "frame_count": self.frame_count,
            "pose_count": self.pose_count,
            "duration_s": self.duration_s,
            "has_pose": self.has_pose,
            "has_intrinsics": self.has_intrinsics,
            "image_size": self.image_size,
            "K": self.K,
            "distortion": self.distortion,
            "reader": self.reader,
            "issues": list(self.issues),
            "frames": [asdict(f) for f in self.frames],
            "colmap": "deferred",
            "pose_source": "/or2s/pose" if self.has_pose else None,
        }


def ingest_session(session_dir: Path | str, out_dir: Path | str) -> IngestResult:
    """Read a Capture session and dump normalized intermediate artifacts."""
    session_dir = Path(session_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    if images_dir.exists():
        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    issues: list[str] = []
    reader_name = "or2s_capture"
    try:
        payload = _read_via_capture(session_dir)
    except ImportError:
        reader_name = "mcap_foxglove_fallback"
        payload = _read_via_mcap(session_dir)
        issues.append("or2s_capture not importable; used mcap + foxglove fallback")
    except Exception as exc:  # noqa: BLE001
        try:
            reader_name = "mcap_foxglove_fallback"
            payload = _read_via_mcap(session_dir)
            issues.append(
                f"or2s_capture.read_session failed ({exc!r}); used mcap + foxglove fallback"
            )
        except Exception as exc2:  # noqa: BLE001
            raise RuntimeError(
                f"Both Capture reader and mcap fallback failed: capture={exc!r}, fallback={exc2!r}"
            ) from exc2

    manifest = payload["manifest"]
    calibration = payload["calibration"]
    rgb_frames = payload["rgb"]
    poses = payload["poses"]
    camera_infos = payload["camera_infos"]

    session_id = str(manifest.get("session_id", session_dir.name))
    K, distortion, image_size, has_intrinsics = _resolve_intrinsics(
        calibration, camera_infos, issues
    )

    frame_records: list[FrameRecord] = []
    for i, fr in enumerate(rgb_frames):
        rel, w, h, enc = _write_rgb_frame(fr, i, images_dir, issues)
        if w is None and image_size:
            w, h = image_size[0], image_size[1]
        frame_records.append(
            FrameRecord(
                index=i,
                log_time_ns=int(fr["log_time_ns"]),
                publish_time_ns=int(fr["publish_time_ns"]),
                frame_id=str(fr.get("frame_id") or ""),
                encoding=enc,
                width=w,
                height=h,
                image_path=rel,
                data_nbytes=int(fr.get("data_nbytes", 0)),
            )
        )

    if image_size is None and frame_records:
        fr0 = frame_records[0]
        if fr0.width and fr0.height:
            image_size = [fr0.width, fr0.height]

    pose_records: list[PoseRecord] = []
    poses_path = out_dir / "poses.jsonl"
    with poses_path.open("w", encoding="utf-8") as pf:
        for i, p in enumerate(poses):
            rec = PoseRecord(
                index=i,
                log_time_ns=int(p["log_time_ns"]),
                publish_time_ns=int(p["publish_time_ns"]),
                frame_id=str(p.get("frame_id") or ""),
                position_m=[float(x) for x in p["position_m"]],
                orientation_xyzw=[float(x) for x in p["orientation_xyzw"]],
            )
            pose_records.append(rec)
            pf.write(json.dumps(asdict(rec)) + "\n")
    if not pose_records:
        poses_path.unlink(missing_ok=True)
        issues.append("no /or2s/pose messages found")

    cameras = {
        "schema": "or2s_reconstruct.cameras/0.1",
        "source_calibration": calibration,
        "K": K,
        "distortion": distortion,
        "image_size": image_size,
        "coordinate_convention": manifest.get("coordinate_convention", "RDF_optical"),
        "time_domain": manifest.get("time_domain", "unix_ns"),
    }
    (out_dir / "cameras.json").write_text(
        json.dumps(cameras, indent=2) + "\n", encoding="utf-8"
    )

    duration_s = manifest.get("duration_s")
    if duration_s is None and frame_records:
        t0 = frame_records[0].log_time_ns
        t1 = frame_records[-1].log_time_ns
        duration_s = max(0.0, (t1 - t0) / 1e9)
    elif duration_s is not None:
        duration_s = float(duration_s)

    if not frame_records:
        issues.append("no RGB frames decoded")
    if not has_intrinsics:
        issues.append("intrinsics missing from sensors.json and camera_info")
    if not (session_dir / "manifest.json").is_file():
        issues.append("missing manifest.json")
    mcap_name = manifest.get("mcap", "session.mcap")
    if not (session_dir / mcap_name).is_file():
        issues.append(f"missing {mcap_name}")
    if calibration is None:
        issues.append("missing calibration/sensors.json")
    if not (session_dir / "checksums.sha256").is_file():
        issues.append("checksums.sha256 absent (optional)")

    result = IngestResult(
        session_id=session_id,
        session_path=str(session_dir),
        out_dir=str(out_dir),
        frame_count=len(frame_records),
        pose_count=len(pose_records),
        duration_s=duration_s,
        has_pose=len(pose_records) > 0,
        has_intrinsics=has_intrinsics,
        image_size=image_size,
        K=K,
        distortion=distortion,
        frames=frame_records,
        issues=issues,
        reader=reader_name,
    )
    (out_dir / "summary.json").write_text(
        json.dumps(result.summary_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "frames.jsonl").write_text(
        "\n".join(json.dumps(asdict(f)) for f in frame_records)
        + ("\n" if frame_records else ""),
        encoding="utf-8",
    )
    return result


def _resolve_intrinsics(calibration, camera_infos, issues):
    K = None
    distortion = None
    image_size = None

    if calibration:
        sensors = calibration.get("sensors") or []
        cam = next((s for s in sensors if s.get("type") == "camera"), None)
        if cam is None and sensors:
            cam = sensors[0]
        if cam:
            intr = cam.get("intrinsics") or {}
            fx, fy = intr.get("fx"), intr.get("fy")
            cx, cy = intr.get("cx"), intr.get("cy")
            if None not in (fx, fy, cx, cy):
                K = [
                    float(fx), 0.0, float(cx),
                    0.0, float(fy), float(cy),
                    0.0, 0.0, 1.0,
                ]
            distortion = [float(x) for x in (cam.get("distortion") or [])]
            w, h = cam.get("width"), cam.get("height")
            if w and h:
                image_size = [int(w), int(h)]

    if K is None and camera_infos:
        info = camera_infos[0]
        k_list = info.get("K")
        if k_list and len(k_list) >= 9:
            K = [float(x) for x in k_list[:9]]
        d_list = info.get("D")
        if d_list is not None:
            distortion = [float(x) for x in d_list]
        w, h = info.get("width"), info.get("height")
        if w and h and image_size is None:
            image_size = [int(w), int(h)]
        if K is not None:
            issues.append(
                "intrinsics taken from /or2s/rgb/camera_info (sensors.json incomplete)"
            )

    return K, distortion, image_size, K is not None


def _write_rgb_frame(fr, index, images_dir, issues):
    data = fr["data"]
    encoding = (fr.get("encoding") or "jpeg").lower()
    w = fr.get("width")
    h = fr.get("height")

    if encoding in ("jpeg", "jpg", "png"):
        ext = "jpg" if encoding in ("jpeg", "jpg") else "png"
        path = images_dir / f"frame_{index:06d}.{ext}"
        path.write_bytes(data)
        if w is None or h is None:
            try:
                with Image.open(path) as im:
                    w, h = im.size
            except Exception as exc:  # noqa: BLE001
                issues.append(f"frame {index}: could not probe image size ({exc})")
        return f"images/{path.name}", w, h, encoding

    if encoding in ("rgb8", "bgr8"):
        if not w or not h:
            issues.append(f"frame {index}: raw {encoding} missing width/height")
            return None, None, None, encoding
        mode_data = data
        if encoding == "bgr8":
            arr = bytearray(data)
            for i in range(0, len(arr) - 2, 3):
                arr[i], arr[i + 2] = arr[i + 2], arr[i]
            mode_data = bytes(arr)
        im = Image.frombytes("RGB", (int(w), int(h)), mode_data)
        path = images_dir / f"frame_{index:06d}.png"
        im.save(path)
        return f"images/{path.name}", int(w), int(h), encoding

    path = images_dir / f"frame_{index:06d}.bin"
    path.write_bytes(data)
    issues.append(f"frame {index}: unknown encoding {encoding!r}; wrote .bin")
    return f"images/{path.name}", w, h, encoding


def _read_via_capture(session_dir: Path) -> dict:
    from or2s_capture import read_session  # type: ignore[import-not-found]

    session = read_session(session_dir)
    rgb = []
    for fr in session.iter_rgb():
        rgb.append(
            {
                "log_time_ns": fr.log_time_ns,
                "publish_time_ns": fr.publish_time_ns,
                "frame_id": fr.frame_id,
                "encoding": fr.encoding,
                "width": fr.width,
                "height": fr.height,
                "data": fr.data,
                "data_nbytes": len(fr.data),
            }
        )
    poses = []
    for p in session.iter_poses():
        poses.append(
            {
                "log_time_ns": p.log_time_ns,
                "publish_time_ns": p.publish_time_ns,
                "frame_id": p.frame_id,
                "position_m": list(p.position_m),
                "orientation_xyzw": list(p.orientation_xyzw),
            }
        )
    camera_infos = []
    for proto in session.iter_camera_info():
        camera_infos.append(
            {
                "width": getattr(proto, "width", None),
                "height": getattr(proto, "height", None),
                "K": list(proto.K) if getattr(proto, "K", None) is not None else None,
                "D": list(proto.D) if getattr(proto, "D", None) is not None else None,
                "frame_id": getattr(proto, "frame_id", ""),
                "distortion_model": getattr(proto, "distortion_model", ""),
            }
        )
    return {
        "manifest": session.manifest,
        "calibration": session.calibration,
        "provenance": session.provenance,
        "rgb": rgb,
        "poses": poses,
        "camera_infos": camera_infos,
    }


def _read_via_mcap(session_dir: Path) -> dict:
    from mcap.reader import make_reader
    from mcap_protobuf.decoder import DecoderFactory

    manifest_path = session_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json not found under {session_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    calibration = None
    cal_rel = manifest.get("calibration_ref", "calibration/sensors.json")
    cal_path = session_dir / cal_rel
    if cal_path.is_file():
        calibration = json.loads(cal_path.read_text(encoding="utf-8"))

    provenance = None
    prov_rel = manifest.get("provenance_ref", "provenance/device.json")
    prov_path = session_dir / prov_rel
    if prov_path.is_file():
        provenance = json.loads(prov_path.read_text(encoding="utf-8"))

    mcap_path = session_dir / manifest.get("mcap", "session.mcap")
    rgb, poses, camera_infos = [], [], []

    with open(mcap_path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for schema, channel, message, proto in reader.iter_decoded_messages():
            topic = channel.topic
            schema_name = schema.name if schema else type(proto).__name__
            if topic == TOPIC_RGB:
                rgb.append(_decode_rgb_proto(schema_name, message, proto))
            elif topic == TOPIC_POSE:
                pose = _decode_pose_proto(schema_name, message, proto)
                if pose is not None:
                    poses.append(pose)
            elif topic == TOPIC_CAMERA_INFO:
                camera_infos.append(_decode_caminfo_proto(message, proto))

    return {
        "manifest": manifest,
        "calibration": calibration,
        "provenance": provenance,
        "rgb": rgb,
        "poses": poses,
        "camera_infos": camera_infos,
    }


def _decode_rgb_proto(schema_name, message, proto):
    if "CompressedImage" in schema_name:
        data = bytes(proto.data)
        return {
            "log_time_ns": message.log_time,
            "publish_time_ns": message.publish_time,
            "frame_id": getattr(proto, "frame_id", ""),
            "encoding": getattr(proto, "format", None) or "jpeg",
            "width": None,
            "height": None,
            "data": data,
            "data_nbytes": len(data),
        }
    if "RawImage" in schema_name:
        data = bytes(proto.data)
        return {
            "log_time_ns": message.log_time,
            "publish_time_ns": message.publish_time,
            "frame_id": getattr(proto, "frame_id", ""),
            "encoding": getattr(proto, "encoding", None) or "rgb8",
            "width": int(proto.width),
            "height": int(proto.height),
            "data": data,
            "data_nbytes": len(data),
        }
    data = bytes(getattr(proto, "data", b"") or b"")
    return {
        "log_time_ns": message.log_time,
        "publish_time_ns": message.publish_time,
        "frame_id": getattr(proto, "frame_id", ""),
        "encoding": getattr(proto, "format", getattr(proto, "encoding", "unknown")),
        "width": getattr(proto, "width", None),
        "height": getattr(proto, "height", None),
        "data": data,
        "data_nbytes": len(data),
    }


def _decode_pose_proto(schema_name, message, proto):
    if "PoseInFrame" not in schema_name:
        return None
    pos = proto.pose.position
    ori = proto.pose.orientation
    return {
        "log_time_ns": message.log_time,
        "publish_time_ns": message.publish_time,
        "frame_id": proto.frame_id,
        "position_m": [float(pos.x), float(pos.y), float(pos.z)],
        "orientation_xyzw": [float(ori.x), float(ori.y), float(ori.z), float(ori.w)],
    }


def _decode_caminfo_proto(message, proto):
    return {
        "width": getattr(proto, "width", None),
        "height": getattr(proto, "height", None),
        "K": list(proto.K) if getattr(proto, "K", None) is not None else None,
        "D": list(proto.D) if getattr(proto, "D", None) is not None else None,
        "frame_id": getattr(proto, "frame_id", ""),
        "distortion_model": getattr(proto, "distortion_model", ""),
        "log_time_ns": message.log_time,
    }
