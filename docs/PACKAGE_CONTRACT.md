# Package contracts — capture input ↔ scene output

I/O between **Capture Lead** (`open-real2sim-capture`), **this repo**, and
**Physical Sim** (`open-physical-sim` / Sim Runtime).

- **Input (capture bag):** CTO-locked — see
  `/workspace/open-real2sim-capture/docs/CAPTURE_BAG_v0.md`. Reproduce here for
  Reconstruct Eng; do not invent alternate layouts.
- **Output (scene package):** owned by Reconstruct Eng + Sim Runtime. Capture
  emits observations + calibration only.

Clean-room: public Real2Sim demo visuals (multi-device densify → photoreal
continuous twin → robot in room; 2×2 RGB/depth/point/wireframe debug) + locked
Capture bag. No proprietary SDK internals.

---

## Demo-driven requirements (visuals only)

| # | Implication |
|---|-------------|
| 1 | Sessions may later fuse phone + robot; bag must support multi-stream timestamps; Reconstruct aligns into **one world frame**. |
| 2 | Primary visual = **3DGS / NeRF**; meshes = **collision / proxy / wireframe**, not hero look. |
| 3 | Scene package must support sim synthetic **RGB + depth + point cloud + wireframe**. |
| 4 | Units = **meters**; Capture camera optical = **RDF**; the Reconstruct export world frame is confirmed with Sim Runtime (frozen in §B). |

---

## A. Input — Capture bag v0 (CTO-locked)

**Authoritative doc:** `open-real2sim-capture/docs/CAPTURE_BAG_v0.md`  
**Status:** draft, CTO lock 2026-09-21. No real sample yet; Capture Lead shipping
**synthetic RGB + poses** this week (`or2s write-synthetic`).

### A.1 Canonical package

A session is either:

1. **Preferred:** `session.mcap` + sibling `manifest.json`, or
2. Directory `session_<uuid>/` with the same logical content (dev convenience).

```
session_<uuid>/
  manifest.json                 # required
  session.mcap                  # required — primary stream store
  calibration/
    sensors.json                # intrinsics / extrinsics
  provenance/
    device.json                 # hardware / OS / app / SDK versions
  checksums.sha256              # optional but recommended
```

All frame data lives in **MCAP topics**. Sidecar JSON is for discovery +
non-stream metadata (Reconstruct can read without scanning the whole bag).

Secondary import path (Capture-owned): **rosbag2** → session via
`or2s import-rosbag` (stub OK). Not HDF5.

### A.2 `manifest.json` (locked shape)

```json
{
  "schema": "open-real2sim.capture.manifest/0.1",
  "session_id": "uuid",
  "created_at": "RFC3339",
  "capture_mode": "android | robot_ros2 | tablet_android | ios_later",
  "purpose": "scene | object | demo_episode | calibration_only",
  "duration_s": 0.0,
  "mcap": "session.mcap",
  "streams": [ /* see topics below */ ],
  "calibration_ref": "calibration/sensors.json",
  "provenance_ref": "provenance/device.json",
  "time_domain": "unix_ns",
  "coordinate_convention": "RDF_optical",
  "license": "Apache-2.0",
  "attribution": { "contributor": "", "site": "", "notes": "" }
}
```

`coordinate_convention`: camera optical **RDF** (x right, y down, z forward).
Robot base / world documented in `sensors.json` (`ENU` or `robot_base` as
`parent_frame`).

### A.3 MCAP topics (v0)

| Topic | Payload | Required |
|-------|---------|----------|
| `/or2s/rgb/image` | Image (rgb8 or jpeg) | **yes** |
| `/or2s/rgb/camera_info` | CameraInfo (K, D, width, height) | **yes** (or bake into sensors.json; prefer both) |
| `/or2s/depth/image` | uint16 mm **or** float32 m | no |
| `/or2s/imu` | Imu | no |
| `/or2s/lidar/points` | PointCloud2 XYZI or XYZ | no |
| `/or2s/pose` | PoseStamped (device/AR or robot) | **recommended** |
| `/tf` / `/tf_static` | TFMessage | robot path |

Every message: log time = publish time in **unix nanoseconds** (or ROS time with
`time_domain` declared and offset in provenance). No silent clock domains.

Stream entries in `manifest.streams` name these topics (`rgb` required;
`depth` / `imu` / `lidar` optional; `pose` recommended). Depth may declare
`unit`: `mm_uint16` | `m_float32` and `aligned_to`: `camera_rgb`.

### A.4 Calibration — `calibration/sensors.json`

```json
{
  "schema": "open-real2sim.capture.calibration/0.1",
  "sensors": [
    {
      "frame_id": "camera_rgb",
      "type": "camera",
      "model": "pinhole_radtan",
      "width": 1920,
      "height": 1080,
      "intrinsics": { "fx": 0.0, "fy": 0.0, "cx": 0.0, "cy": 0.0 },
      "distortion": [0, 0, 0, 0, 0],
      "parent_frame": "imu",
      "T_parent_sensor": {
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "translation_m": [0.0, 0.0, 0.0]
      }
    }
  ],
  "rig_id": "android_default | robot_<name>",
  "calibration_date": "RFC3339",
  "method": "factory | arkit | arcore | kalibr | manual | unknown"
}
```

**Pose convention (locked for Reconstruct Eng):**

- `T_parent_sensor` = **parent ← sensor** (transforms a point in sensor frame
  into parent).
- Quaternion **xyzw**.
- Depth (if present) shares RGB optical frame when `aligned_to: camera_rgb`.
- Units: **meters**.

### A.5 Provenance — `provenance/device.json`

```json
{
  "schema": "open-real2sim.capture.device/0.1",
  "platform": "android | ros2",
  "device_model": "",
  "os_version": "",
  "app_or_node": "or2s-android/0.1.0",
  "sdk_versions": {},
  "time_sync": {
    "time_domain": "unix_ns",
    "source": "system | ros_clock | arcore",
    "notes": ""
  }
}
```

### A.6 Minimum viable session for Reconstruct ingest

1. `manifest.json` + `session.mcap` with `/or2s/rgb/image` (+ camera_info).
2. `calibration/sensors.json` with RGB intrinsics (extrinsics identity OK for
   monocular phone).
3. Optional but strongly preferred: depth aligned to RGB **or** `/or2s/pose`.

**Not available yet:** real capture samples. Use Capture Lead synthetic
RGB+poses writer until Android/ROS2 bags land.

**Not Capture’s job:** Isaac/MuJoCo / splat export formats — Reconstruct + Sim
Runtime only.

### A.7 Multi-device / multi-session (demo stretch)

v0 bag is one session / one primary RGB rig. Demo showed phone densifying while
robot head rays contribute. Until Capture defines multi-rig or multi-session
merge:

- Reconstruct v0: **single-session** ingest.
- v1: co-register multiple sessions into one world (open question).

### A.8 Capture-side still open (non-blocking for us)

- Default depth unit preference (`mm_uint16` when Android provides it).
- Exact foxglove vs ROS 2 CDR encodings inside MCAP (Capture Python stub).

Reconstruct should consume via Capture’s `or2s_capture.read_session` / validate
when available; otherwise mcap + foxglove/ROS readers pinned in our deps.

---

## B. Output — scene package (Reconstruct + Sim Runtime)

**Status: FROZEN with Sim Runtime.** Capture does **not** own this half.

### B.1 Design split (demo-aligned)

| Layer | Asset | Consumer |
|-------|-------|----------|
| **Hero visual** | 3DGS (primary) or NeRF | Photoreal RGB |
| **Synthetic depth / points** | Offline splat render (QA) or proxy/collision sim cameras | 2×2 depth + point cloud |
| **Wireframe / collision** | Coarse mesh | Physics + wireframe pane |
| **Metadata** | `scene.json` | Loaders, Env Commons later |

### B.2 Folder layout (frozen)

```
scene_pkg/
  scene.json
  visual/
    splat/
      gaussians.ply              # gsplat/nerfstudio-compatible Gaussian PLY; v0 required
      train_config.yaml
      render_meta.json
    nerf/                        # optional
      checkpoint.ckpt
      config.yml
    proxy/                        # required v0: decimated textured mesh and/or point cloud
  collision/
    room_shell.obj               # meters; physics + wireframe pane
  materials/
    README.md                    # v0: visuals via splat; collision untextured
  transforms/
    world_frame.json
    capture_rdf_to_world.json    # RDF optical → export world (4x4)
  sensors_synth/
    default_rgbd_camera.json     # intrinsics template for debug streams
  provenance/
    source_session_id.txt
    tool_versions.json
    licenses.json
    capture_manifest_copy.json   # optional embed of input manifest
  qa/
    heldout_metrics.json
    mesh_stats.json
```

### B.3 `scene.json` (frozen shape)

```json
{
  "package_version": "0.1.0-draft",
  "scene_id": "string",
  "source_session_id": "uuid-from-capture-manifest",
  "units": "m",
  "world_frame": {
    "convention": "right_handed_z_up",
    "up_axis": "z",
    "floor_z": 0.0,
    "gravity_dir": [0, 0, -1],
    "capture_rdf_to_world_4x4": [
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
    ],
    "note": "Confirmed with Sim Runtime for Isaac Lab / MuJoCo / Genesis; mirror the numeric matrix from transforms/capture_rdf_to_world.json here"
  },
  "visual": {
    "primary": "3dgs",
    "splat_path": "visual/splat/gaussians.ply",
    "proxy_path": "visual/proxy/",
    "bbox_xyz": [0, 0, 0, 0, 0, 0]
  },
  "collision": {
    "mesh_path": "collision/room_shell.obj",
    "triangle_count": 0,
    "wireframe_source": "collision_mesh"
  },
  "synthetic_streams": {
    "rgb": { "source": "offline_splat_render | proxy_sim" },
    "depth": { "source": "offline_splat_render | proxy_sim", "units": "m", "encoding_hint": "float32_meters" },
    "point_cloud": { "source": "offline_splat_render | proxy_sim", "frame": "camera" },
    "wireframe": { "source": "collision_mesh" },
    "default_camera_path": "sensors_synth/default_rgbd_camera.json"
  },
  "robot_spawn": {
    "T_world_spawn": [],
    "clearance_radius_m": 0.5,
    "note": "Unitree-class first agent is Sim Runtime's call; we export meters + frame"
  },
  "qa": {
    "capture_tier": "cheap | mid | rich",
    "metrics_path": "qa/heldout_metrics.json"
  }
}
```

### B.4 Sim Runtime loader expectations

- v0 stubs (Isaac Lab / MuJoCo / Genesis) do **not** rasterize 3DGS.
- Always ship `visual/splat/gaussians.ply` as the hero for the viewer / future
  renderer; it is gsplat/nerfstudio-compatible. An optional `.splat` sidecar may
  be added later but is not required for v0.
- Always ship `collision/room_shell.obj` for physics + the wireframe pane.
- Always ship `visual/proxy/` with a decimated textured mesh and/or point cloud
  so the stub can show scene content without a Gaussian rasterizer.
- Synthetic RGB/depth/points for the **2×2 debug** come from an offline
  Reconstruct splat render (QA) or sim cameras against collision/proxy in the
  stub; wireframe comes from the collision mesh. The same numeric RDF→world 4×4
  is present in `transforms/capture_rdf_to_world.json` and mirrored in
  `scene.json` (`world_frame.capture_rdf_to_world_4x4`).
- Demo agent selection (e.g. Unitree-class) = Sim Runtime; we guarantee meters,
  the confirmed world frame, and an optional spawn hint.

### B.5 Versioning

- Capture `schema` strings are Capture-owned.
- Scene `package_version` semver; breaking layout bumps until 1.0.
- Keep `source_session_id` == Capture `session_id`.
