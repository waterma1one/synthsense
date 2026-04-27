# SynthSense

**Multimodal incident intelligence platform.** Paste logs, drop a dashboard screenshot, and watch a LangGraph agent pipeline triage, diagnose, remediate, and write a postmortem — live, streamed to the browser.

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![LangGraph](https://img.shields.io/badge/LangGraph-orchestration-FF6B6B)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

An on-call engineer pastes raw logs (or drops a dashboard screenshot) into SynthSense. Within seconds, a four-agent pipeline runs:

1. **Preprocess** — extracts structured entities from logs and analyzes images in parallel
2. **Triage** — zero-shot severity classification: `critical / high / medium / low`
3. **Diagnose** — RAG over past incidents + runbooks to find root cause (skipped on critical for speed)
4. **Remediate** — chain-of-thought action plan with ranked immediate steps
5. **Postmortem** — blameless summary embedded and stored so future incidents can learn from this one

Every step streams to the browser in real time via SSE. Every diagnosis is automatically scored with RAGAS + an LLM judge every 10 incidents.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT PIPELINE                               │
│                                                                     │
│  [Image / Logs / Text]                                              │
│          │                                                          │
│          ▼                                                          │
│    ┌──────────────┐                                                 │
│    │  Preprocess  │  image_processor + log_processor (parallel)    │
│    └──────┬───────┘                                                 │
│           │                                                         │
│           ▼                                                         │
│    ┌──────────────┐                                                 │
│    │    Triage    │  Zero-shot severity: critical/high/medium/low  │
│    └──────┬───────┘                                                 │
│           │                                                         │
│    ┌──────┴──────┐                                                  │
│    │             │                                                  │
│  CRITICAL      NORMAL                                               │
│    │             │                                                  │
│    │      ┌──────▼───────┐                                         │
│    │      │   Diagnose   │  RAG: past incidents + runbooks         │
│    │      └──────┬───────┘                                         │
│    │             │                                                  │
│    └──────┬──────┘                                                  │
│           │                                                         │
│           ▼                                                         │
│    ┌──────────────┐                                                 │
│    │  Remediate   │  CoT-prompted action plan (temp=0.2)           │
│    └──────┬───────┘                                                 │
│           │                                                         │
│    ┌──────┴──────┐                                                  │
│    │             │                                                  │
│  CRITICAL      NORMAL                                               │
│    │             │                                                  │
│    │      ┌──────▼───────┐                                         │
│    │      │  Postmortem  │  Blameless summary + embed + store      │
│    │      └──────┬───────┘                                         │
│    │             │                                                  │
│    └──────┬──────┘                                                  │
│           │                                                         │
│           ▼                                                         │
│    ┌──────────────┐                                                 │
│    │   Supabase   │  pgvector store for future RAG                 │
│    └──────────────┘                                                 │
│                                                                     │
│  Observability:  LangSmith traces every node                       │
│  Cache:          Upstash Redis caches image analysis (24h TTL)     │
│  Quality:        RAGAS + LLM judge scores every 10 incidents       │
└─────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

| Decision | Why |
|---|---|
| LangGraph `StateGraph` | Stateful, conditional routing (critical fast-path skips diagnosis) |
| SSE over WebSocket | Unidirectional stream is simpler; no reconnect logic on server side |
| `fetch` streaming (not `EventSource`) | Allows POST body — needed to send base64 images without URL length limits |
| pgvector in Supabase | Zero infrastructure: vector search + relational joins in one free-tier DB |
| Local sentence-transformers embeddings | No API cost or latency for 384-dim BAAI/bge-small-en |
| Tenacity retry on every LLM call | HuggingFace free-tier models cold-start with 503; Groq can rate-limit |

---

## Tech stack

| Layer | Tool | Cost |
|---|---|---|
| LLM | Groq llama-3.1-8b-instant | Free tier |
| Vision | HuggingFace llava-1.5-7b-hf | Free tier |
| Embeddings | BAAI/bge-small-en (sentence-transformers) | Local, free |
| Vector DB | Supabase pgvector | Free tier |
| Cache | Upstash Redis (REST) | Free tier |
| Orchestration | LangGraph + LlamaIndex | Open source |
| Quality | RAGAS + LLM judge | Open source |
| Observability | LangSmith | Free tier |
| Backend | FastAPI (async) | Open source |
| Frontend | React + Tailwind + Recharts | Open source |

**Total monthly cost to run: $0** (all free tiers)

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/waterma1one/synthsense.git
cd synthsense
cp .env.example .env
# Fill in your API keys — see table below
```

### 2. Get API keys (all free)

| Service | Where to get it | Key format |
|---|---|---|
| [Groq](https://console.groq.com) | Console → API Keys | `gsk_...` |
| [HuggingFace](https://huggingface.co/settings/tokens) | Settings → Tokens | `hf_...` |
| [Supabase](https://supabase.com) | New Project → Settings → API | URL + `service_role` key |
| [Upstash](https://upstash.com) | New Redis DB → REST API | REST URL + token |
| [LangSmith](https://smith.langchain.com) | Settings → API Keys | `lsv2_pt_...` |

### 3. Set up Supabase vector table

Run this SQL once in your [Supabase SQL editor](https://supabase.com/dashboard/project/_/sql):

```sql
create extension if not exists vector;

create table if not exists incidents (
  id          uuid primary key default gen_random_uuid(),
  title       text,
  raw_input   text,
  image_description text,
  severity    text,
  diagnosis   text,
  remediation text,
  postmortem  text,
  embedding   vector(384),
  created_at  timestamptz default now()
);

create index if not exists incidents_embedding_idx
  on incidents using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create table if not exists runbook_chunks (
  id        uuid primary key default gen_random_uuid(),
  source    text,
  content   text,
  embedding vector(384),
  created_at timestamptz default now()
);

create index if not exists runbook_chunks_embedding_idx
  on runbook_chunks using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);
```

### 4. Run with Docker Compose (recommended)

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000)

### 5. Or run locally

```bash
# Terminal 1 — backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

---

## Usage

### Submit an incident

Paste raw logs (or describe the issue) in the form. Optionally attach a dashboard screenshot. Click **Analyze Incident** — the agent timeline streams live as each node completes.

```bash
# Or via curl
curl -X POST http://localhost:8000/incidents \
  -F "description=2024-01-15T14:23:01Z ERROR api-gateway Connection refused to payment-service:8080
2024-01-15T14:23:02Z ERROR api-gateway Retry 1/3 failed: dial tcp 10.0.1.45:8080
2024-01-15T14:23:05Z CRIT  payment-service Pod CrashLoopBackOff: exit code 137 (OOM)"
```

### Upload a runbook

Drop a PDF on the **Runbooks** page (or via curl). It gets chunked and indexed into the vector store so the Diagnose agent can cite it.

```bash
curl -X POST http://localhost:8000/runbooks/upload \
  -F "file=@./runbooks/database-recovery.pdf"
```

### Stream live agent progress

The React frontend uses this automatically. You can also consume it directly:

```bash
curl -N "http://localhost:8000/incidents/{incident_id}/stream?description=your+logs"
```

Each SSE event has the shape:
```json
{
  "incident_id": "uuid",
  "agent": "triage",
  "status": "completed",
  "output": { "severity": "high", "confidence": 0.92, ... }
}
```

### Browse history

The **History** page lists all past incidents from Supabase. Click any row to view the full agent timeline and remediation plan.

---

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/incidents` | Submit and run pipeline synchronously |
| `GET` | `/incidents/{id}` | Fetch stored incident record |
| `GET` | `/incidents` | List last N incidents (default 20) |
| `GET` | `/incidents/{id}/stream` | SSE stream via GET (curl-friendly) |
| `POST` | `/incidents/{id}/stream` | SSE stream via POST (supports image payload) |
| `POST` | `/runbooks/upload` | Ingest a runbook PDF into the vector store |
| `GET` | `/evals/latest` | Latest RAGAS + LLM judge scores |
| `GET` | `/evals/all` | All historical scores for trend charts |
| `GET` | `/health` | Liveness probe |
| `GET` | `/docs` | Swagger UI |

---

## Eval / quality

SynthSense scores itself automatically every 10 incidents using two complementary approaches:

### RAGAS (retrieval quality)

Measures the RAG pipeline in the Diagnose agent:
- **Faithfulness** — does the diagnosis stay grounded in retrieved context?
- **Answer relevancy** — is the diagnosis relevant to the question?
- **Context recall** — does retrieved context contain the ground truth?

### LLM judge (generation quality)

Groq-as-judge scores each diagnosis on:
- **Accuracy** — correct root cause identified?
- **Completeness** — all contributing factors covered?
- **Actionability** — are remediation steps executable?
- **Specificity** — are service names and error codes cited from evidence?

Both scores appear in the **RAG Quality** dashboard with trend charts.

### Run evals manually

```bash
cd backend

# Generate 20 synthetic test incidents first (uses Groq)
python -m eval.synthetic_data generate

# Run RAGAS + LLM judge assessment
python -m eval.ragas_eval run
```

Expected output:
```json
{
  "timestamp": "2024-01-15T14:30:00+00:00",
  "sample_size": 5,
  "scores": {
    "faithfulness": 0.8124,
    "answer_relevancy": 0.7653,
    "context_recall": 0.6891,
    "judge": {
      "accuracy": 0.82,
      "completeness": 0.79,
      "actionability": 0.91,
      "specificity": 0.75,
      "overall": 0.82
    }
  }
}
```

---

## Project structure

```
synthsense/
├── backend/
│   ├── agents/
│   │   ├── graph.py              # LangGraph StateGraph — pipeline wiring + routing
│   │   ├── triage_agent.py       # Zero-shot severity classification
│   │   ├── diagnosis_agent.py    # RAG root-cause analysis
│   │   ├── remediation_agent.py  # CoT action plan generation
│   │   └── postmortem_agent.py   # Blameless summary + Supabase persistence
│   ├── api/
│   │   ├── incidents.py          # POST/GET/SSE endpoints
│   │   ├── runbooks.py           # PDF upload + ingestion
│   │   └── evals.py              # RAGAS + judge score endpoints
│   ├── eval/
│   │   ├── ragas_eval.py         # RAGAS assessment pipeline
│   │   ├── llm_judge.py          # Groq-as-judge scoring
│   │   └── synthetic_data.py     # Synthetic incident generator
│   ├── ingestion/
│   │   ├── image_processor.py    # LLaVA vision analysis + Redis cache
│   │   ├── log_processor.py      # Structured entity extraction from logs
│   │   └── pdf_processor.py      # PDF chunking + embedding
│   ├── memory/
│   │   ├── vector_store.py       # Supabase pgvector read/write
│   │   └── redis_cache.py        # Upstash Redis REST client
│   ├── config.py                 # Pydantic Settings — all env vars
│   └── main.py                   # FastAPI app + middleware
├── frontend/
│   └── src/
│       ├── api/client.js         # Axios + fetch SSE streaming
│       └── components/
│           ├── IncidentForm.jsx  # Log/image submission
│           ├── AgentTimeline.jsx # Live streaming view + history read view
│           ├── RemediationCard.jsx # Interactive checklist
│           ├── IncidentList.jsx  # History browser
│           ├── RunbookUpload.jsx # PDF drag-and-drop upload
│           └── EvalDashboard.jsx # RAGAS + judge gauges + trend lines
├── docker-compose.yml
└── .env.example
```

---

## Development

### Backend

```bash
cd backend
source venv/bin/activate

# Type check
mypy . --ignore-missing-imports

# Lint
ruff check .

# Run with auto-reload
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

# Dev server with HMR
npm run dev

# Type check (if using TypeScript)
npm run build   # catches JSX errors
```

### Environment variables

All config lives in `backend/config.py` as a Pydantic `BaseSettings` model. Every setting has a typed field with validation. Add new settings there — never import from `os.environ` directly.

---

## Production upgrade path

SynthSense is built on free tiers to be zero-cost. These are the first swaps for a real deployment:

| Component | Free version | Production version | Why |
|---|---|---|---|
| LLM | Groq llama-3.1-8b | GPT-4o / Claude Sonnet | Better reasoning, JSON reliability |
| Vision | llava-1.5-7b (HuggingFace) | GPT-4o Vision / Claude Vision | Much better dashboard interpretation |
| Vector DB | Supabase pgvector (shared) | Dedicated pgvector or Pinecone | SLA, connection pooling, autoscaling |
| Cache | Upstash Redis (REST) | ElastiCache / Redis Cluster | Lower latency, TCP connections |
| Embeddings | BAAI/bge-small-en local | text-embedding-3-large | Higher accuracy, larger dimension |
| Observability | LangSmith free | LangSmith Enterprise / Datadog | Full retention, alerting, SLO tracking |
| Async workers | asyncio tasks | Celery + Redis | Durable job queues, retries, DLQ |
| Auth | None | Auth0 / Okta | Multi-tenant, RBAC for incident data |
| Deployment | Docker Compose | Kubernetes + Helm | Auto-scaling, rolling deploys |

---

## License

MIT
