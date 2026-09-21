# open-real2sim-reconstruct

I built a tool that turns a room recording into a 3D twin sims can load.

Phone or robot film (from `open-real2sim-capture`) goes in. A photoreal-ish splat, a simple collision shell, and a textured proxy mesh come out as a `scene_pkg/` that Physical Sim / MuJoCo can load.

Apache-2.0 · clean-room · draft

> Inspired by public Real2Sim product demos only. No affiliation with any closed SDK.

## Why this exists

Capture sessions are observations. Robots need a twin of the place they will work — something that looks right and something physics can bump into. This repo is that middle hop.

## Quickstart

```bash
cd /workspace/real2sim-reconstruct
source .venv/bin/activate   # or: python -m venv .venv && pip install -e .
reconstruct ingest /workspace/open-real2sim-capture/_demo_session_30s --out _runs/demo_30s_ingest
```

Reference package (v0 plumbing, CPU splat stub): `_runs/demo_30s_scene_pkg/`

## How it fits

```
open-real2sim-capture → open-real2sim-reconstruct → open-physical-sim
                              ↘                ↕
                               open-env-commons
```

## Docs

| Doc | What |
|-----|------|
| [`docs/PIPELINE.md`](docs/PIPELINE.md) | End-to-end pipeline |
| [`docs/PACKAGE_CONTRACT.md`](docs/PACKAGE_CONTRACT.md) | Capture bag in + scene_pkg out (frozen) |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Quality vs capture cost |
| [`docs/V0_MILESTONE.md`](docs/V0_MILESTONE.md) | Acceptance checklist |
| [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) | Open decisions |

## Status

- Ingest + scene_pkg export: working on Capture synthetic 30s bag
- Real 3DGS (nerfstudio splatfacto): waiting on CUDA GPU
- Publish: single-repo spaced push only (founder policy)

## License

Apache-2.0. See SECURITY / CONTRIBUTING when published.
