# v0 milestone — Reconstruct Eng

**One-liner:** one indoor room from phone RGB (+ optional depth/pose) → 3DGS +
coarse collision mesh + required visual proxy → scene package loadable by a
**stub** MuJoCo/Isaac path that can show synthetic RGB (+ depth/wireframe
best-effort) without in-sim Gaussian rasterization.

Apache-2.0 · clean-room · Capture bag v0 ingest.

---

## In scope

1. Ingest Capture bag v0: `manifest.json` + `session.mcap` +
   `calibration/sensors.json` + `provenance/device.json`.
2. Use Capture Lead **synthetic RGB + poses** for first end-to-end dry run
   (this week); swap to real Android session when available.
3. Poses: prefer `/or2s/pose`; else COLMAP SfM on RGB.
4. Train **3DGS** (nerfstudio splatfacto or gsplat — pick one, pin versions).
5. Build **coarse collision mesh** (Open3D TSDF if depth; else COLMAP dense /
   splat-depth voxel — noisy OK).
6. Export `scene_pkg/` per the frozen `PACKAGE_CONTRACT.md` §B:
   `visual/splat/gaussians.ply`, required `visual/proxy/`, collision mesh,
   `scene.json`, and RDF→world transform.
7. Hand package to Physical Sim stub loader; document how 2×2 debug streams map
   (offline splat render for QA or `proxy_sim` in the stub; wireframe from mesh).
   v0 stubs do not rasterize 3DGS.

## Out of scope (v0)

- Multi-device phone+robot fusion (layout-ready; implement v1).
- NeRF required path (optional only).
- Production USD authoring, convex decomposition, PBR mesh hero looks.
- Unitree (or any) robot policy — Sim Runtime owns agent choice.
- Token/marketplace features.

---

## Acceptance checklist

### Capture ingest

- [ ] `reconstruct ingest` accepts a Capture v0 session directory.
- [ ] Fails clearly if `/or2s/rgb/image` missing.
- [ ] Reads RDF optical intrinsics from `sensors.json` / camera_info.
- [ ] Honors `T_parent_sensor` parent←sensor, quat xyzw, meters.
- [ ] Dry-run succeeds on Capture **synthetic** RGB+poses bag.

### Reconstruction

- [ ] ≥1 indoor-room-like session produces a trained 3DGS artifact.
- [ ] Holdout render smoke (even if metrics soft on synthetic).
- [ ] Coarse `collision/room_shell.obj` exists, units meters, tri count recorded.
- [ ] Required `visual/proxy/` contains a decimated textured mesh and/or point cloud.
- [ ] Scale: if poses/depth give meters, package is metrically consistent;
      if RGB-only SfM, `scale_unknown` flagged in QA.

### Export / sim stub

- [ ] `scene.json` validates against draft schema fields in PACKAGE_CONTRACT.
- [ ] Physical Sim stub loads collision mesh (MuJoCo **or** Isaac path — one is
      enough for v0).
- [ ] Stub shows synthetic **RGB/depth/points** from `proxy_sim`; QA may use
      an offline splat render. No in-sim Gaussian rasterizer is required.
- [ ] Wireframe from collision mesh visible in stub debug view.
- [ ] Depth + point-cloud panes: implemented **or** explicitly stubbed with issue
      filed (best-effort in v0).

### Process / legal

- [ ] README states Apache-2.0 + clean-room stance.
- [ ] Dependency license list reviewed for COLMAP, nerfstudio/gsplat, Open3D,
      mcap stack.
- [ ] No proprietary InvLambda code or private assets in tree.

---

## Definition of done

All checklist boxes above checked, or waived in writing in OPEN_QUESTIONS with
owner + date. Demo narrative target (aspirational, not all required for code
freeze): “phone bag → twin → robot walks in stub living room” — robot agent is
Sim Runtime’s deliverable; our DoD stops at **loadable package + RGB/wireframe**.

---

## Suggested sequencing (engineering weeks)

| Week | Focus |
|------|-------|
| W0 | Contracts locked (Capture bag ✅); synthetic ingest |
| W1 | COLMAP/pose path + splatfacto train on synthetic then phone |
| W2 | Mesh export + scene_pkg writer |
| W3 | Sim stub integration + benchmark smoke + checklist sign-off |
