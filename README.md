# N3uron LibreChat v0.8.5-rc1

Slim Docker-only deployment bundle for LibreChat with:

- local Ollama inference running inside Docker
- one local model only: `gemma4:26b`
- direct connection to the host N3uron MCP server
- LibreChat summarization enabled
- LibreChat native memory disabled
- RAG enabled with the local LibreChat RAG API
- Engram wired as workflow memory over MCP
- artifacts enabled for the single ops preset

## Requirements

- Docker Desktop
- A reachable N3uron MCP server on the host machine

No extra host AI runtime is required. This bundle is intentionally Docker-only.

## Start

1. Copy `.env.local.example` to `.env`.
2. Set `N3LOCAL_TOKEN` in `.env`.
3. Start the stack:

```powershell
cd C:\Gitrepos\MyGPT\n3uron-librechat-v0.8.5-rc1
.\scripts\start-stack.ps1
```

Open `http://localhost:3085`.

## Default Preset

- `N3 O&M`: the only preset, using `gemma4:26b` with `N3LOCAL`, RAG file search, Engram workflow memory, summarization, and artifacts

## Notes

- First startup takes longer because the Ollama container pulls `gemma4:26b`.
- `N3LOCAL` is the MCP bridge used by the preset. It queries the host N3uron MCP server and normalizes some operational payloads for the model.
- LibreChat native memory is disabled. Workflow state is stored in Engram only, and only as compact checkpoints, decisions, blockers, conclusions, and next actions.
- RAG uses the local LibreChat RAG API plus the bundled pgvector database.
- Artifacts are intended to be emitted as LibreChat markdown artifact blocks.
- If you want to change the model later, do it manually in `docker-compose.yml` or through Ollama after the stack is up:

```powershell
docker exec n3uron-librechat-v085-ollama ollama pull <other-model>
```

- LibreChat is pinned to `registry.librechat.ai/danny-avila/librechat:v0.8.5-rc1`.
- This bundle intentionally avoids any host-installed LLM runtime.

## Upstream References

- LibreChat docs: https://www.librechat.ai/docs
- LibreChat repo: https://github.com/danny-avila/LibreChat
