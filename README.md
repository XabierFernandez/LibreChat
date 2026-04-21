# N3uron LibreChat v0.8.5-rc1

Slim Docker-only deployment bundle for LibreChat with:

- local Ollama inference running inside Docker
- `gemma4:e2b` for tool-backed N3uron operations
- `gemma4:e2b` for general local chat
- `LiquidAI/lfm2.5-1.2b-instruct:latest` for fast plain chat
- optional `gemma4:26b` pull for a heavier local model
- direct connection to the host N3uron MCP server
- LibreChat summarization configured to control context growth

## Requirements

- Docker Desktop
- A reachable N3uron MCP server on the host machine

No extra host AI runtime is required.

## Start

1. Copy `.env.local.example` to `.env`.
2. Set `N3LOCAL_TOKEN` in `.env`.
3. Start the stack:

```powershell
cd C:\Gitrepos\MyGPT\n3uron-librechat-v0.8.5-rc1
.\scripts\start-stack.ps1
```

Open `http://localhost:3085`.

## Default Profiles

- `N3uron Ops`: default profile, auto-enables `N3LOCAL` MCP tools and uses `gemma4:e2b`
- `Gemma 4 E2B`: plain local chat without MCP tools
- `LFM 2.5 Fast`: faster plain local chat without MCP tools

## Notes

- First startup takes longer because the Ollama container pulls the required models.
- `N3LOCAL` points directly to the host N3uron MCP server. Tool availability is determined by that server and the user’s choices, not by a hardcoded proxy layer in this repo.
- The built-in LibreChat MemoryAgent is disabled in this deployment because the local tool workflow is handled by the model spec plus summarization. This avoids tool-compatibility failures with smaller local models.
- To add the larger Gemma model later:

```powershell
docker exec n3uron-librechat-v085-ollama ollama pull gemma4:26b
```

- LibreChat is pinned to `registry.librechat.ai/danny-avila/librechat:v0.8.5-rc1`.
- This bundle intentionally avoids any host-installed LLM runtime.

## Upstream References

- LibreChat docs: https://www.librechat.ai/docs
- LibreChat repo: https://github.com/danny-avila/LibreChat
