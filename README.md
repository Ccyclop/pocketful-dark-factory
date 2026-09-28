# Pocketful, built by a dark factory

Entry for the WeAreDevelopers × BAND "AI Dark Factory" hackathon, track **pocketful**.

- **Team:** _to be filled in_
- **Factory:** five seats in BAND Desktop across three model families; see [`FACTORY.md`](FACTORY.md) and [`mandates/`](mandates/).

## How to read this repository

| Path | What it is |
|---|---|
| `FACTORY.md` | the factory: seats, flow, gates, design choices and their cost, failure handling, setup |
| `mandates/` | one standing instruction per seat, each naming its harness and model |
| `room.json` | the full BAND room of the submitted run, downloaded unchanged |
| `stage-1/` … `stage-4/` | one complete service per stage; each has a `Dockerfile` and a `RUN.md` |
| `CONTRACT.md`, `DECISIONS.md` | the planner's verbatim contract and every interpretation it made |
| `METRICS.md` | per-milestone items, REJECTs, BREAKs and wall time, written by the integrator |
| `acceptance/`, `adversary/` | the verifier's black-box tests and the adversary's attack scripts |
| `factory/` | setup scripts, dispatch briefs and the cost log |

Every commit's author is the seat that made it, and every commit message ends with a `Seat:` trailer, so the git history can be read alongside `room.json`.

## Running a stage

Follow `stage-N/RUN.md`.
