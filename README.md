# Auditor Fraud Detection

Upload a zip of company books and supporting documents; stream a **ranked findings feed** for auditors (not a dashboard). Detectors are config-driven and general — they transfer to other dossiers via categories, not memorized sample IDs.

## What judges should know

| Topic | Detail |
|-------|--------|
| Runtime path | Zip upload → deterministic parse → DuckDB detectors → confidence bands → optional OpenAI narration → SSE |
| Sealed GT | [`data/UEBUNG_GROUND-TRUTH_SEALED_Muster-Verpackungen.md`](data/UEBUNG_GROUND-TRUTH_SEALED_Muster-Verpackungen.md) is a **held-out eval fixture only**. It is never read by `backend/app/` or fed to the LLM. |
| Sample zip | [`data/Uebungsdaten_Muster_Verpackungen.zip`](data/Uebungsdaten_Muster_Verpackungen.zip) is the demo upload. A different zip should still run end-to-end. |
| LLM role | Narration, quote trim, policy/threshold extract — never invents findings or confidence % |

## Quick start

### Docker Compose (preferred)

```bash
cp .env.example .env   # optional OPENAI_API_KEY
docker compose up --build
```

- UI: ue
- API: http://127.0.0.1:8000  

Compose e2e (upload + SSE):

```bash
bash backend/tests/compose_e2e.sh
```

### Dev without Docker

**Backend**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
bun install
bun run dev
```

OpenAI env (see `.env.example`): `OPENAI_API_KEY`, `OPENAI_MODEL_PRIMARY=gpt-5.6`, `OPENAI_MODEL_FAST=gpt-5.6-terra`. Without a key, template narration still runs.

## Architecture

```
ZipUpload → Parse(GDPdU/CSV/XLSX/PDF/DOCX) → DuckDB
                ↓
         Category detectors (YAML) → Stage 2 citations → Confidence bands
                ↓
         Optional LLM narrate → SSE → React findings list
```

Confidence: `clamp(0..100, base + statistical_strength + stage2_delta + multi_category_boost)`

| Band | Default | UI |
|------|---------|-----|
| Skip | `< 35%` | Hidden |
| Needs human verification | `35–65%` | Muted badge + Verify/Dismiss |
| High | `> 65%` | Ranked card |

## Adding a detector via config

1. Add parameters under a new key in [`backend/app/config/detectors.yaml`](backend/app/config/detectors.yaml) (thresholds, keyword categories, table-name substrings — **no dossier entity IDs**).
2. Implement `detect_<name>(conn, cfg)` in [`backend/app/detection/detectors.py`](backend/app/detection/detectors.py) returning `DetectorHit`s.
3. Register it in `run_all_detectors`.
4. Re-run eval (below). Prefer skip-band over noisy false positives.

## Sealed GT eval (offline, test-only)

```bash
cd backend
source .venv/bin/activate
python tests/eval_against_gt.py
```

This script alone may open the sealed GT file. Rubric matches the sealed file’s **Suggested scoring**:

| Weight | Rule |
|--------|------|
| Top marks | **F1** by *combining* sources + **F2/F3** profit-overstatement pair |
| Bonus | **F4** |
| Penalty | Accusing decoys **D1–D7** (−5 pts each on rubric, cap −30) |

Points: F1=40, F2=25, F3=25, F4=10. Do not “fix” eval by baking GT vendors/users into detectors.

## Repo layout

```
/
├── docker-compose.yml
├── docs/IMPLEMENTATION_PLAN.md
├── data/                 # sample zip + sealed GT (eval only)
├── backend/              # FastAPI + DuckDB
└── frontend/             # Bun + Vite 8 + React + TypeScript strict
```

## Smoke / regression

```bash
cd backend && source .venv/bin/activate
python tests/smoke_parse_sample.py
python tests/smoke_phase2_api.py
python tests/smoke_phase3_detectors.py
python tests/smoke_phase4_llm.py
python tests/eval_against_gt.py
```
