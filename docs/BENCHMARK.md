# Benchmark — quality vs capture cost

Rubric for comparing reconstruction quality against how expensive the capture was
(device class, time, storage, optional streams). Aligns with demo: indoor
room-scale (bedroom / living room), photoreal twin (3DGS/NeRF), physics mesh
proxies, and sim debug streams (RGB / depth / points / wireframe).

Fixtures consume Capture bag v0 (`session.mcap` + `manifest.json`). Until real
phone/robot bags exist, use Capture Lead **synthetic RGB+poses** for pipeline
smoke only — synthetic is **out of score** for perceptual metrics.

---

## Capture tiers

| Tier | Device class | Streams (bag) | Effort | Intent |
|------|--------------|---------------|--------|--------|
| **cheap** | Mid Android phone, handheld | RGB @ ~15–30 Hz, 1–3 min walk; pose if ARCore easy; no depth/LiDAR | < 5 min capture; < 2 GB session | v0 default path |
| **mid** | Flagship phone / tablet RGB-D | RGB + aligned depth + pose; 3–8 min; good coverage | < 15 min; < 8 GB | Scale + geometry lift |
| **rich** | Phone densify **+** robot ROS2 (RGB-D and/or LiDAR) | Multi-session or multi-stream; `/or2s/lidar/points` and/or robot depth; TF | 15–40 min; tens of GB | Demo-class twin; multi-device align |

Tier is recorded in output `scene.json` → `qa.capture_tier` and in eval reports.
Promote a fixture to a higher tier only when bag streams match the table.

---

## Metrics

### A. Novel-view / appearance (hero visual = splat/NeRF)

Hold out ~10% of RGB frames (or a fixed index list in the fixture). Render from
estimated / bag poses.

| Metric | Applies | Notes |
|--------|---------|-------|
| **PSNR** ↑ | Always when GT RGB | Report mean ± std on holdout |
| **SSIM** ↑ | Same | |
| **LPIPS** ↓ | Same (Alex/VGG — pin one) | Primary perceptual score |
| Train wall-clock | Always | GPU model + VRAM in report |
| Splat/NeRF storage | Always | GB on disk for visual/ |

**v0 gate (cheap tier, real phone bag when available):** LPIPS mean ≤ 0.35 on
holdout **or** human “usable twin” checklist if metric flake — document which.
Synthetic bags: smoke only (PSNR against synthetic GT allowed but not ranked).

### B. Geometry / collision fidelity

| Metric | Method | Notes |
|--------|--------|-------|
| **Depth L1 / RMSE** (m) | Where bag has depth: render synth depth vs GT | Prefer splat depth; also report collision-raycast depth |
| **Chamfer / accuracy–completeness** | If LiDAR or dense depth GT | Room shell vs GT cloud |
| **Collision proxy error** | Sample queries: robot footprint spheres vs mesh | % penetrations on scripted path |
| Mesh tri count / bytes | Always | Budget: ≤ 50k tris room shell for v0 |

No GT mesh in cheap tier → skip Chamfer; still report tri count + visual QA.

### C. Synthetic stream usability (demo 2×2 UI)

Qualitative + light quantitative checklist for Sim Runtime stub:

| Stream | Pass criteria |
|--------|---------------|
| RGB | Photoreal from splat; no black frames on spawn camera |
| Depth | Dense, meters; holes documented; sync with RGB pose |
| Point cloud | Unproject depth; density usable for debug |
| Wireframe | Collision mesh overlays; floor visible |

### D. Cost / ops

| Metric | Definition |
|--------|------------|
| Capture time | Wall-clock human capture (minutes) |
| Session size | `session.mcap` + sidecars (GB) |
| Reconstruct wall-clock | Stage 0→4 total (minutes) on pinned GPU/CPU |
| Peak VRAM | During train |
| Export package size | `scene_pkg/` GB |

**Efficiency score (informal):** LPIPS (or geometry RMSE) vs reconstruct minutes
× session GB — for Pareto plots across tiers, not a single CI number.

---

## Fixtures (planned)

| ID | Tier | Source | Status |
|----|------|--------|--------|
| `synth_room_rgb_pose` | n/a (smoke) | Capture `write-synthetic` | Expected this week |
| `cheap_phone_bedroom` | cheap | Android RGB(+pose) | TBD Capture |
| `mid_phone_rgbd_living` | mid | RGB-D + pose | TBD |
| `rich_phone_plus_robot` | rich | Multi-device | TBD; needs align story |

Each fixture ships: bag path, holdout list, eval config YAML, golden metric
bands (filled after first real runs).

---

## Reporting format

```json
{
  "scene_id": "",
  "source_session_id": "",
  "capture_tier": "cheap",
  "hardware": { "gpu": "", "vram_gb": 0 },
  "appearance": { "psnr": 0, "ssim": 0, "lpips": 0, "n_holdout": 0 },
  "geometry": { "depth_l1_m": null, "chamfer_m": null, "collision_tris": 0 },
  "cost": {
    "capture_min": 0,
    "session_gb": 0,
    "reconstruct_min": 0,
    "package_gb": 0
  },
  "streams_qa": { "rgb": true, "depth": true, "point_cloud": true, "wireframe": true },
  "tool_versions": {}
}
```

Store under `scene_pkg/qa/heldout_metrics.json` and copy into benchmark dashboard
dir (later).

---

## Non-goals for v0 benchmark

- Cross-lab sim2real policy success rates (Physical Sim / research later).
- Marketplace contributor quality scores (Env Commons).
- Matching InvLambda private metrics (unknown; clean-room).
