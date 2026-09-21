# open-real2sim-reconstruct

Apache-2.0 · clean-room · Reconstruction layer for open Real2Sim

Turn multi-view / RGB-D / LiDAR capture packages into ultrarealistic scene assets
(3D Gaussian Splatting, optional NeRF, meshes, textures, collision proxies) and
export packages that `open-physical-sim` can load.

Sibling projects:

| Repo | Owner | Role |
|------|-------|------|
| `open-real2sim-capture` | Capture Lead | Bag format, phone RGB-D, ROS2 importer |
| `open-real2sim-reconstruct` | **this repo** | SfM → 3DGS/NeRF → mesh/export |
| `open-physical-sim` | Physical Sim | Isaac Lab / MuJoCo loader + robot demos |
| `open-env-commons` | Env Commons | Manifest schema, local registry, attribution |

Product context (public claims only): Inverted Lambda Physical Agents SDK Real2Sim
turns robot/phone sensor data into ultrarealistic sims so policies train where they
deploy. This repo is an independent open clone of the **reconstruction** step only.
See `/workspace/invlambda/REVERSE_ENGINEER.md` for the shared reverse-engineer brief.

## Scope

**In scope**

- Ingest Capture bag v0 from `open-real2sim-capture`: `session.mcap` +
  `manifest.json` + `calibration/sensors.json` + `provenance/device.json`
  (CTO-locked; see Capture `docs/CAPTURE_BAG_v0.md` and our
  `docs/PACKAGE_CONTRACT.md` §A).
- Pose estimation / SfM (or consume poses if capture already provides them).
- Novel-view / photoreal representation: 3D Gaussian Splatting primary; NeRF
  fallback where splat training is unsuitable.
- Geometry for physics: coarse meshes, collision proxies, optional textured mesh
  bake from splat/NeRF.
- Export a **scene package** with transforms, materials, splat sidecar, and
  metadata JSON for Physical Sim.
- Benchmarks: reconstruction quality vs capture cost (device class, time, storage).

**Out of scope (non-goals)**

- Capture hardware drivers, bag writers, ROS2 bag recording (Capture Lead).
- Physics engines, robot URDFs, policy training loops (Physical Sim).
- Marketplace / token rewards (Env Commons may hold attribution hooks only).
- Cloud-only proprietary pipelines; this stack must run offline on a workstation GPU.
- Cloning or redistributing any proprietary InvLambda SDK code or private assets.

## Clean-room stance

- Base design on **public marketing claims and demo visuals only**.
- Do **not** inspect, scrape, or decompile InvLambda private SDKs, binaries, or
  non-public APIs.
- Prefer well-known OSS building blocks (COLMAP, nerfstudio, gsplat, Open3D, etc.)
  under compatible licenses; document license of every transitive dep before pin.
- License this repo **Apache-2.0**. Capture datasets remain under their own
  licenses; never ship third-party captures without clear redistribution rights.

## Docs map

| Doc | Contents |
|-----|----------|
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | End-to-end pipeline + OSS tool candidates |
| [`docs/PACKAGE_CONTRACT.md`](docs/PACKAGE_CONTRACT.md) | Input capture layout + output scene package |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Quality vs capture-cost rubric + tiers |
| [`docs/V0_MILESTONE.md`](docs/V0_MILESTONE.md) | v0 acceptance criteria |
| [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) | Decisions for Capture Lead / Physical Sim / user |

## Repo status

v0 planning. No pipeline code yet. **Capture input contract is CTO-locked.**
Scene package export is frozen with Sim Runtime.
