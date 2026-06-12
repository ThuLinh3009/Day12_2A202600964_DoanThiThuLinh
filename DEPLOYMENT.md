# Deployment Guide — Day 12 Lab

**Student:** Doan Thi Thu Linh  
**Student ID:** 2A202600964  
**Course:** VinUniversity AICB-P1 2026

---

## Production URL

**Base URL:** https://linhdoan-day12-shopping-agent.hf.space

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | None | Service info |
| `/health` | GET | None | Liveness probe |
| `/ready` | GET | None | Readiness probe |
| `/ask` | POST | X-API-Key | Ask the Shopping Assistant |
| `/metrics` | GET | X-API-Key | Operational metrics |

---

## Quick Test

```bash
# Health check
curl https://linhdoan-day12-shopping-agent.hf.space/health

# Ask the agent
curl -X POST https://linhdoan-day12-shopping-agent.hf.space/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: prod-a7f3k9m2n5p8q1r4s6t0u3v7w1x4y8z2" \
  -d '{"question": "Chính sách đổi trả hàng như thế nào?", "user_id": "test-user"}'
```

---

## Architecture

```
Internet → Render (Docker) → FastAPI → LangGraph Multi-Agent
                                          ├── Supervisor
                                          ├── Policy Worker (RAG + ChromaDB)
                                          ├── Data Worker (orders/customers)
                                          └── Response Worker (Gemini LLM)
```

## Stack

- **Runtime:** Python 3.11, FastAPI, Uvicorn
- **AI Agent:** LangGraph multi-agent (Day 09 Shopping Assistant)
- **LLM:** Google Gemini 3.1 Flash Lite
- **RAG:** ChromaDB + sentence-transformers/all-MiniLM-L6-v2
- **Security:** API Key auth, rate limiting (10 req/min), cost guard ($10/day)
- **Docker:** Multi-stage build, non-root user `agent`
- **Platform:** HuggingFace Spaces (Docker, Free tier)

## GitHub Repository

https://github.com/ThuLinh3009/Day12_2A202600964_DoanThiThuLinh

## Validation

```
20/20 checks passed (100%) — PRODUCTION READY!
```
