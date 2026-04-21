# N3uron LibreChat Local Setup

This workspace is a clean LibreChat `v0.8.5-rc1` base configured for:

- local chat models through LM Studio on `http://127.0.0.1:1235`
- N3uron MCP through `http://host.docker.internal:4103/mcp`
- context control through LibreChat `memory` and top-level `summarization`
- local Docker deployment on `http://localhost:3085`

## Runtime choices

- Primary chat endpoint: `LocalLMStudio`
- Chat models:
  - `google/gemma-4-e2b`
  - `google/gemma-4-e4b`
  - `liquid/lfm2-24b-a2b`
  - `lfm2.5-1.2b-instruct`
- Memory/summarization model: `lfm2.5-1.2b-instruct`
- RAG embeddings: LM Studio `text-embedding-nomic-embed-text-v1.5`

## Start

```powershell
cd C:\Gitrepos\MyGPT\n3uron-librechat-v0.8.5-rc1
.\scripts\start-stack.ps1
```

Then open `http://localhost:3085`.

## Notes

- `docker-compose.override.yaml` makes container names unique so this stack can coexist with older LibreChat projects.
- `.env` is local-only and intentionally not tracked.
- `scripts/start-lmstudio-server.ps1` ensures LM Studio is listening on port `1235` before Docker starts the app.
