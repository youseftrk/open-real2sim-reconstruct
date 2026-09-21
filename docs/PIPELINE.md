# Pipeline — ingest → reconstruct → export

Target flow for `open-real2sim-reconstruct`:

```
capture session (MCAP + manifest, Capture Lead)
        │
        ▼
  [0] validate + normalize
        │
        ▼
  [1] SfM / poses (+ optional depth fusion)
        │
        ├──────────────────┐
        ▼                  ▼
  [2a] 3DGS train    [2b] NeRF train (fallback)
        │                  │
        └────────┬─────────┘
                 ▼
  [3] mesh / collision proxies + textures
                 │
                 ▼
  [4] sim export package (Physical Sim contract)
                 │
                 ▼
  [5] eval harness (BENCHMARK.md metrics)
```

Each stage writes intermediate artifacts under `work/<run_id>/` so stages are
restartable. Final deliverable is the scene package described in
`PACKAGE_CONTRACT.md`.

---

## Stage 0 — Validate + normalize (Capture bag v0)

**Input:** CTO-locked capture session — `manifest.json` + `session.mcap` (+
`calibration/sensors.json`, `provenance/device.json`). Authoritative:
`open-real2sim-capture/docs/CAPTURE_BAG_v0.md`. Full field copy in
`PACKAGE_CONTRACT.md` §A.

Until real bags exist: ingest Capture Lead **synthetic RGB + poses** sessions
(`or2s write-synthetic`).

**Jobs**

1. Prefer `or2s_capture.validate` / `read_session` when available; else parse
   `manifest.json` and open MCAP directly.
2. Require topics `/or2s/rgb/image` + `/or2s/rgb/camera_info` (or intrinsics in
   `sensors.json`). Warn if `/or2s/pose` or depth missing; fail if no RGB.
3. Read calibration: RDF optical; `T_parent_sensor` = parent←sensor; quat xyzw;
   meters. Copy provenance into run metadata.
4. Extract frames to `normalized/`: `frames/000001.jpg`, optional
   `depth/000001.png`, `meta/timestamps_unix_ns.csv`, `meta/poses.csv` if present.
5. Color: decode to RGB; record encoding (`rgb8`|`jpeg`) from manifest.

**Candidate tools**

| Tool | Role | Why |
|------|------|-----|
| `or2s_capture` (Capture SDK) | validate / read_session | Canonical bag API |
| `mcap` + foxglove/ROS CDR decoders | Raw topic read | Fallback if SDK incomplete |
| OpenCV / Pillow | Image decode + resize | Standard |
| Custom checks | Schema + required topics | Gate CI fixtures |

**Exit criteria:** validate OK; ≥ 40 RGB frames (synthetic may use fewer for
smoke — document); poses recommended; depth/LiDAR optional.

---

## Stage 1 — SfM / poses

**Goal:** camera poses `T_world_cam` + intrinsics for every used frame; sparse
point cloud for init / scale.

**Paths**

- **A (preferred when `/or2s/pose` present):** trust bag poses (convert RDF
  optical → COLMAP/OpenCV as needed); run COLMAP sparse only for QA / scale
  check if depth/LiDAR absent.
- **B (phone RGB-only default for v0):** full SfM.

**Candidate tools**

| Tool | License (typical) | Role | Rationale |
|------|-------------------|------|-----------|
| **COLMAP** | BSD | Feature extract, match, mapper, undistort | Industry default SfM; nerfstudio/gsplat all speak COLMAP |
| **hloc** (Hierarchical Localization) | Apache-2.0 | Better matching on texture-poor rooms | Optional upgrade when COLMAP fails indoors |
| **OpenMVG** | MPL-2.0 | Alternate SfM | Backup if COLMAP packaging pain |
| **Open3D** | MIT | RGB-D odometry / TSDF if depth present | Cheap dense init when phone depth exists |
| **GTSAM** / g2o | BSD / BSD | Pose-graph refine with IMU (later) | Not v0 |

**v0 choice:** COLMAP sequential matcher for phone video-like stills; Open3D
RGB-D odometry branch if depth stream present (optional).

**Outputs**

- `poses/cameras.txt`, `images.txt`, `points3D.txt` (COLMAP text) **or**
  `poses/transforms.json` (nerfstudio-style).
- `sparse/cloud.ply`
- `qa/pose_coverage.json` (fraction of frames registered)

**Failure modes:** low texture walls → hloc SuperPoint+SuperGlue; motion blur →
reject frames by Laplacian variance; scale ambiguity (RGB-only) → mark
`scale_unknown: true` and require Physical Sim user scale or one depth
measurement (open question).

---

## Stage 2 — Photoreal representation

### 2a — 3D Gaussian Splatting (primary)

**Why primary:** fast train/infer on consumer GPU; good for indoor Real2Sim
novel views; easy sidecar for viz; mesh extract pathways exist (SuGaR,
2DGS, etc.).

**Candidate tools**

| Tool | Notes |
|------|-------|
| **gsplat** (nerfstudio / GraphDeco lineage) | Apache-2.0 friendly CUDA kernels; actively maintained |
| **nerfstudio** `splatfacto` | Batteries-included training CLI; COLMAP ingest |
| **Inria / GraphDeco original 3DGS** | Reference; check license before shipping weights/code |
| **2DGS / SuGaR** (later) | Better surface for meshing |

**v0 choice:** nerfstudio `splatfacto` **or** bare `gsplat` train script driven by
COLMAP; pick one in implementation week 1 and pin versions.

**Outputs:** `visual/splat/gaussians.ply` (gsplat/nerfstudio-compatible
Gaussian PLY), `splat/cfg.yaml`, and a train log with held-out PSNR. An optional
`.splat` sidecar is later-only and not required for v0.

### 2b — NeRF (fallback)

Use when splat underperforms (specular rooms, extreme sparse views) or when
Physical Sim wants volume density for something splat cannot give.

| Tool | Notes |
|------|-------|
| **nerfstudio** `nerfacto` | Same ingest as splatfacto |
| **Instant-NGP** (via nerfstudio) | Fast; license check (NVIDIA) before bundling |

**v0:** NeRF optional; not required for acceptance if 3DGS meets visual bar.

---

## Stage 3 — Mesh / collision / textures

Physics sims need **collision geometry**, not 50M Gaussians.

**Jobs**

1. Extract or fuse coarse collision mesh (room shell + large furniture blobs).
2. Decimate to collision LOD (v0 target: ≤ 50k tris for room shell).
3. Emit required `visual/proxy/`: a decimated textured mesh and/or point cloud
   for non-splat stub viewers.
4. Emit simplified primitives (boxes/planes) where mesh is noisy — later tier.

**Candidate tools**

| Tool | Role | Rationale |
|------|------|-----------|
| **Open3D** | TSDF fusion from RGB-D; Poisson; decimate | Mature; MIT |
| **trimesh** | Repair, watertight check, export GLB/OBJ | Apache-2.0 |
| **PyMeshLab** / MeshLab | Quadric decimation, cleanup | Strong mesh ops |
| **SuGaR / 2DGS** (post-v0) | Mesh from Gaussians | Better visual-collision alignment |
| **Blender** (headless, optional) | UV unwrap / bake | Heavy; optional CI path |

**v0 path (phone RGB, optional depth):**

- If depth: Open3D TSDF → mesh → decimate → `collision/room_shell.obj`
  plus the required `visual/proxy/` output.
- If RGB-only: COLMAP dense (PatchMatch) **or** splat-derived depth on a voxel
  grid → coarse collision mesh + required proxy. Accept noisy walls for v0;
  document known issues.

**Textures:** the v0 proxy is a decimated textured mesh and/or point cloud; the
collision mesh may remain untextured. The Gaussian PLY remains the hero visual
for viewers/future renderers (recommended split: **visual = splat + proxy**,
**physics = coarse mesh**).

---

## Stage 4 — Sim export package

Assemble folder per `PACKAGE_CONTRACT.md`:

- `scene.json` metadata
- `visual/splat/gaussians.ply`
- `visual/proxy/` (required v0 decimated textured mesh and/or point cloud)
- `collision/room_shell.obj` (+ optional convex decomposition later)
- `materials/` (stub PBR or “use splat”)
- `transforms/` (world frame, floor plane estimate)
- `provenance/` (capture id, tool versions, licenses)

Hand off to `open-physical-sim` loaders (MuJoCo MJCF/USD stub, Isaac Lab USD).

**Ownership:** sim export formats (splat sidecar, collision mesh, `scene.json`)
are Reconstruct Eng + Sim Runtime — **not** Capture Lead.

**Coordinate frames (frozen with Sim Runtime):**

- **Capture (locked):** camera optical **RDF** (x right, y down, z forward);
  `T_parent_sensor` parent←sensor; quat xyzw; meters.
- **Export:** right-handed **Z-up**, meters, floor at `z≈0`, gravity
  `[0,0,-1]`. Write the explicit RDF→world 4×4 in
  `transforms/capture_rdf_to_world.json` and mirror it in `scene.json`. Do not
  use Y-up for the package.
- **Stub rendering:** Isaac Lab / MuJoCo / Genesis v0 stubs do not rasterize
  3DGS; use offline splat renders for QA or sim cameras against collision/proxy.

---

## Stage 5 — Eval harness

Run `docs/BENCHMARK.md` suite on fixed capture fixtures. Gate CI on “smoke”
metrics only; full perceptual metrics on GPU nightly.

---

## Suggested CLI (future)

```bash
reconstruct ingest   ./capture_pkg --out ./work/run001
reconstruct poses    ./work/run001 --backend colmap
reconstruct train    ./work/run001 --method splatfacto --gpus 1
reconstruct mesh     ./work/run001 --backend open3d-tsdf   # or colmap-dense
reconstruct export   ./work/run001 --out ./scenes/room_v0
reconstruct eval     ./scenes/room_v0 --fixture cheap_phone_room
```

Stages should be independently invocable for debugging.

---

## Compute assumptions (v0)

| Stage | Typical hardware | Rough wall-clock (one indoor room) |
|-------|------------------|------------------------------------|
| Validate | CPU | minutes |
| COLMAP SfM | 8–16 CPU threads | 10–60 min |
| splatfacto | 1× 24GB GPU | 20–90 min |
| TSDF/mesh | CPU or GPU | 5–30 min |
| Export | CPU | < 5 min |

Exact numbers land in BENCHMARK once fixtures exist.

---

## License checklist before first code commit

Confirm redistribution terms for: COLMAP, nerfstudio, gsplat, Open3D, trimesh,
any pretrained feature weights (SuperPoint etc.). Prefer Apache-2.0 / MIT / BSD.
Do not vendor copyleft that would force GPL on the Apache-2.0 package without an
explicit project decision.
