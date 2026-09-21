# Open questions

Decisions needed from **user / CTO**, **Capture Lead**, and **Physical Sim /
Sim Runtime**. Capture bag layout itself is **CTO-locked**
(`CAPTURE_BAG_v0.md`) — do not re-litigate MCAP primary, RGB-required topics,
RDF optical, or `T_parent_sensor` parent←sensor / xyzw / meters.

---

## For Capture Lead

| ID | Question | Notes | Blocking v0? |
|----|----------|-------|--------------|
| C1 | ETA + schema freeze for **synthetic RGB+poses** writer? | Reconstruct dry-run depends on it this week | **Yes** for e2e |
| C2 | Confirm foxglove vs ROS 2 CDR encodings in MCAP for v0 topics | We pin matching readers | Soft |
| C3 | Default depth unit when Android present (`mm_uint16` preferred in bag doc)? | Declare always in manifest | No |
| C4 | Multi-device demo (phone + robot densify): one session vs multiple sessions + merge API? | Demo showed both; bag is single-session today | No (v1) |
| C5 | Will `/or2s/pose` be present on synthetic and Android paths? | Strongly preferred for scale/speed | Soft |

---

## For Physical Sim / Sim Runtime

| ID | Question | Notes | Blocking v0? |
|----|----------|-------|--------------|
| S1 | **CLOSED — splat sidecar vs baked mesh** | **Sim Runtime freeze:** `visual/splat/gaussians.ply` is the gsplat/nerfstudio-compatible hero; optional `.splat` later, not required for v0. | **CLOSED** |
| S2 | **CLOSED — world frame** | **Sim Runtime freeze:** right-handed Z-up meters, floor_z ≈ 0, gravity `[0,0,-1]`; explicit RDF→world 4×4 in `transforms/capture_rdf_to_world.json` and mirrored in `scene.json`; no Y-up package. | **CLOSED** |
| S3 | **CLOSED — splat file format** | **Sim Runtime freeze:** ship `visual/splat/gaussians.ply`, gsplat/nerfstudio-compatible; optional `.splat` later, not required for v0. | **CLOSED** |
| S4 | Synthetic depth/points: future runtime rasterization vs prebaked streams? | **v0 frozen:** no in-sim Gaussian rasterization; use offline splat render (QA) or proxy/collision sim cameras. Future implementation choice remains soft. | Soft |
| S5 | First demo agent = Unitree-class? | Their call; we only export meters/spawn hint | No |
| S6 | MuJoCo-first vs Isaac-first stub for scene package load? | One path enough for Reconstruct acceptance | Soft |

---

## For user / CTO

| ID | Question | Notes | Blocking v0? |
|----|----------|-------|--------------|
| U1 | ~~Pin training stack~~ **CLOSED: nerfstudio splatfacto** for week 1 | User deferred; Reconstruct Eng chose batteries-included path; revisit if CI too heavy | Closed |
| U2 | Accept noisy RGB-only meshes for cheap tier, or require depth for any “physics” claim? | Honesty in README | Soft |
| U3 | Repo name publish: `open-real2sim-reconstruct` vs `real2sim-reconstruct`? | Folder today is `/workspace/real2sim-reconstruct/` | No |
| U4 | GPL/copyleft deps (if any mesh tools) — forbid or isolate? | Default: Apache/MIT/BSD only | Soft |

---

## Cross-cutting (demo implications)

1. **Multi-device alignment** into one frame — Capture session model + Reconstruct
   co-registration; not in v0 acceptance.
2. **Volumetric primary visual** — package + Sim must not treat collision mesh as
   the look.
3. **Synthetic RGB+depth+LiDAR-like streams** — package declares capabilities;
   runtime implements 2×2 debug.
4. **Unitree-class demo** — Sim Runtime agent choice; Reconstruct exports metric
   world they need (S2).

---

## Closed (do not reopen without CTO)

**Sim Runtime freeze (S1–S3):** v0 stubs do not rasterize 3DGS. Always ship the
Gaussian PLY hero, `collision/room_shell.obj`, and required `visual/proxy/`
(decimated textured mesh and/or point cloud). Synthetic RGB/depth/points come
from an offline Reconstruct splat render (QA) or stub sim cameras against the
collision/proxy.

- Capture primary format = **MCAP** (+ manifest/calibration/provenance sidecars).
- RGB topics `/or2s/rgb/image` + `/or2s/rgb/camera_info` required; depth/IMU/LiDAR
  optional; pose recommended.
- Camera optical **RDF**; `T_parent_sensor` parent←sensor; quat **xyzw**; **meters**.
- Sim/mesh/splat export formats = Reconstruct + Sim Runtime, not Capture.
- Clean-room Apache-2.0; no InvLambda private SDK inspection.
