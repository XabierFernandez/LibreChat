"""Engram MCP Server — exposes memory tools to Claude Code and other MCP clients."""

from __future__ import annotations

import copy
import json
import os
import re

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent, Tool

from engram.autosave import AutoSave
from engram.client import Memory
from engram.config import EngramConfig
from engram.sessions import SessionManager
from mcp_server.tools import (
    AUTOSAVE_TOOL_DEFINITIONS,
    LINK_TOOL_DEFINITIONS,
    PRO_TOOL_DEFINITIONS,
    TOOL_DEFINITIONS,
)

app = Server("engram")
_TOOL_PROFILE = os.getenv("ENGRAM_TOOL_PROFILE", "full").strip().lower()
_WORKFLOW_TOOL_NAMES = {
    "memory_store",
    "memory_search",
    "memory_session_save",
    "memory_session_load",
    "memory_session_list",
    "memory_checkpoint",
}
_WORKFLOW_TOOL_OVERRIDES = {
    "memory_store": (
        "Store a compact plain-text workflow note only: checkpoint, decision, blocker, "
        "conclusion, or next action. Never store HTML, code, raw tool output, raw historian "
        "data, artifacts, or chat transcripts."
    ),
    "memory_search": "Search compact workflow notes, prior decisions, blockers, and next actions.",
    "memory_session_save": (
        "Save a concise workflow checkpoint with summary, key facts, and open tasks. "
        "Use short plain-text bullets, not raw outputs or generated code."
    ),
    "memory_session_load": "Load the latest saved workflow checkpoint for this project.",
    "memory_session_list": "List saved workflow checkpoints for this project.",
    "memory_checkpoint": (
        "Save a terse workflow checkpoint. Keep summaries short and do not include raw tool "
        "payloads, HTML, or copied report text."
    ),
}
_WORKFLOW_MAX_CHARS = int(os.getenv("ENGRAM_WORKFLOW_MAX_CHARS", "500"))
_WORKFLOW_MAX_ITEM_CHARS = int(os.getenv("ENGRAM_WORKFLOW_MAX_ITEM_CHARS", "180"))
_BLOCKED_WORKFLOW_PATTERNS = (
    "<!doctype",
    "<html",
    "</html",
    "<body",
    "<script",
    ":::artifact",
    "```",
    '"role":',
    '"tool_call',
    '"n3":',
    '"sys":',
    '"usage":',
)
_config = EngramConfig(enable_embeddings=_TOOL_PROFILE != "workflow")
_memories: dict[str, Memory] = {}
_sessions: SessionManager | None = None
_autosavers: dict[str, AutoSave] = {}


def _mem(namespace: str = "default") -> Memory:
    if namespace not in _memories:
        _memories[namespace] = Memory(config=_config, namespace=namespace)
    return _memories[namespace]


def _sess() -> SessionManager:
    global _sessions
    if _sessions is None:
        _sessions = SessionManager(db_path=_config.db_path)
    return _sessions


def _normalize_plaintext(value: str, *, field_name: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty plain text")
    if len(text) > max_chars:
        raise ValueError(
            f"{field_name} is too long for workflow memory; keep it under {max_chars} characters"
        )

    lowered = text.lower()
    if lowered.startswith("{") or lowered.startswith("["):
        raise ValueError(
            f"{field_name} must be a concise workflow summary, not raw JSON or a structured dump"
        )
    if any(pattern in lowered for pattern in _BLOCKED_WORKFLOW_PATTERNS):
        raise ValueError(
            f"{field_name} must be plain-text workflow memory only; do not store HTML, code, or raw outputs"
        )

    return text


def _normalize_items(items: list[str] | None, *, field_name: str, max_items: int = 8) -> list[str] | None:
    if items is None:
        return None

    normalized = [
        _normalize_plaintext(str(item), field_name=field_name, max_chars=_WORKFLOW_MAX_ITEM_CHARS)
        for item in items
        if str(item).strip()
    ]
    return normalized[:max_items]


def _enforce_workflow_payload(name: str, args: dict) -> dict:
    if _TOOL_PROFILE != "workflow":
        return args

    clean = dict(args)

    if name == "memory_store":
        clean["content"] = _normalize_plaintext(
            str(args["content"]),
            field_name="memory_store.content",
            max_chars=_WORKFLOW_MAX_CHARS,
        )
        clean["tags"] = _normalize_items(args.get("tags"), field_name="memory_store.tags") or []
        return clean

    if name in {"memory_session_save", "memory_checkpoint"}:
        if "summary" in clean and clean.get("summary") is not None:
            clean["summary"] = _normalize_plaintext(
                str(clean["summary"]),
                field_name=f"{name}.summary",
                max_chars=_WORKFLOW_MAX_CHARS,
            )
        clean["key_facts"] = _normalize_items(clean.get("key_facts"), field_name=f"{name}.key_facts")
        clean["open_tasks"] = _normalize_items(clean.get("open_tasks"), field_name=f"{name}.open_tasks")
        return clean

    return clean


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------


def _available_tool_definitions() -> list[dict]:
    all_tools = (
        TOOL_DEFINITIONS + PRO_TOOL_DEFINITIONS + LINK_TOOL_DEFINITIONS + AUTOSAVE_TOOL_DEFINITIONS
    )
    if _TOOL_PROFILE == "workflow":
        workflow_tools = []
        for tool in all_tools:
            if tool["name"] not in _WORKFLOW_TOOL_NAMES:
                continue
            tool_copy = copy.deepcopy(tool)
            override = _WORKFLOW_TOOL_OVERRIDES.get(tool_copy["name"])
            if override:
                tool_copy["description"] = override
            workflow_tools.append(tool_copy)
        return workflow_tools
    return all_tools


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(**td) for td in _available_tool_definitions()]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name not in {tool["name"] for tool in _available_tool_definitions()}:
            raise ValueError(f"Tool '{name}' is disabled for profile '{_TOOL_PROFILE}'")
        result = _dispatch(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]


def _dispatch(name: str, args: dict) -> dict:
    args = _enforce_workflow_payload(name, args)
    ns = args.get("namespace", "default")
    mem = _mem(ns)

    if name == "memory_store":
        mid = mem.store(
            args["content"],
            type=args.get("type", "fact"),
            importance=args.get("importance", 5),
            tags=args.get("tags", []),
            namespace=ns,
            ttl_days=args.get("ttl_days"),
        )
        return {"id": mid, "duplicate": mid is None, "status": "stored"}

    if name == "memory_search":
        results = mem.search(args["query"], limit=args.get("limit", 10), namespace=ns)
        return {
            "results": [
                {
                    "content": r.memory.content,
                    "type": r.memory.memory_type.value,
                    "importance": r.memory.importance,
                    "score": r.score,
                    "id": r.memory.id,
                }
                for r in results
            ],
            "count": len(results),
        }

    if name == "memory_recall":
        entries = mem.recall(
            limit=args.get("limit", 20),
            namespace=ns,
            min_importance=args.get("min_importance", 7),
        )
        return {
            "memories": [
                {
                    "content": e.content,
                    "type": e.memory_type.value,
                    "importance": e.importance,
                    "id": e.id,
                }
                for e in entries
            ],
            "count": len(entries),
        }

    if name == "memory_delete":
        deleted = mem.delete(args["memory_id"])
        return {"deleted": deleted, "memory_id": args["memory_id"]}

    if name == "memory_stats":
        return mem.stats(namespace=ns)

    # -- Pro Tools: Sessions --

    if name == "memory_session_save":
        return _sess().save_checkpoint(
            project=args.get("project"),
            summary=args["summary"],
            key_facts=args.get("key_facts"),
            open_tasks=args.get("open_tasks"),
            files_modified=args.get("files_modified"),
        )

    if name == "memory_session_load":
        result = _sess().load_checkpoint(
            project=args.get("project"),
            session_id=args.get("session_id"),
        )
        if result is None:
            return {
                "error": "No checkpoint found",
                "hint": "Save a checkpoint first with memory_session_save",
            }
        return result

    if name == "memory_session_list":
        sessions = _sess().list_sessions(
            project=args.get("project"),
            limit=args.get("limit", 10),
        )
        return {"sessions": sessions, "count": len(sessions)}

    # -- Pro Tools: Semantic Search --

    if name == "memory_semantic_search":
        results = mem.search(
            args["query"],
            limit=args.get("limit", 10),
            namespace=ns,
            semantic=True,
        )
        return {
            "results": [
                {
                    "content": r.memory.content,
                    "type": r.memory.memory_type.value,
                    "importance": r.memory.importance,
                    "score": r.score,
                    "id": r.memory.id,
                }
                for r in results
            ],
            "count": len(results),
            "method": "semantic",
        }

    # -- Pro Tools: Context Recovery --

    if name == "memory_recover":
        return {"recovery": _sess().recover_context(project=args.get("project"))}

    # -- Pro Tools: Backfill & Cleanup --

    if name == "memory_backfill_embeddings":
        count = mem.backfill_embeddings(namespace=ns)
        return {"backfilled": count, "status": "completed"}

    if name == "memory_cleanup_expired":
        count = mem.cleanup_expired(namespace=ns)
        return {"removed": count, "status": "completed"}

    # -- Pro Tools: Context Builder --

    if name == "memory_context":
        result = mem.context(
            args["prompt"],
            max_tokens=args.get("max_tokens", 2000),
            namespace=ns,
            min_importance=args.get("min_importance", 3),
        )
        return {
            "context": result.context,
            "memories_used": result.memories_used,
            "token_count": result.token_count,
            "truncated": result.truncated,
            "memory_ids": result.memory_ids,
        }

    # -- Pro Tools: Memory Links --

    if name == "memory_link":
        link_id = mem.link(
            args["source_id"],
            args["target_id"],
            relation=args.get("relation", "related"),
        )
        return {
            "id": link_id,
            "duplicate": link_id is None,
            "status": "linked" if link_id else "duplicate",
        }

    if name == "memory_unlink":
        deleted = mem.unlink(args["link_id"])
        return {"deleted": deleted, "link_id": args["link_id"]}

    if name == "memory_links":
        links = mem.links(
            args["memory_id"],
            direction=args.get("direction", "both"),
            relation=args.get("relation"),
        )
        return {"links": links, "count": len(links)}

    if name == "memory_graph":
        graph = mem.graph(
            args["memory_id"],
            max_depth=args.get("max_depth", 2),
            relation=args.get("relation"),
        )
        return graph

    # -- Pro Tools: Agent AutoSave --

    if name == "memory_checkpoint":
        project = args.get("project")
        key = project or "__default__"
        if key in _autosavers:
            result = _autosavers[key].checkpoint(reason=args.get("reason", "manual"))
        else:
            result = _sess().save_checkpoint(
                project=project,
                summary=args.get("summary") or f"[checkpoint:{args.get('reason', 'manual')}]",
                key_facts=args.get("key_facts"),
                open_tasks=args.get("open_tasks"),
            )
            result["reason"] = args.get("reason", "manual")
        return result

    if name == "memory_autosave_configure":
        project = args.get("project")
        key = project or "__default__"
        if key not in _autosavers:
            _autosavers[key] = AutoSave(_sess(), project=project)
        saver = _autosavers[key]
        config_args = {}
        if "enabled" in args:
            config_args["enabled"] = args["enabled"]
        if "interval_minutes" in args:
            config_args["interval_seconds"] = args["interval_minutes"] * 60
        if "message_threshold" in args:
            config_args["message_threshold"] = args["message_threshold"]
        if "ram_threshold_pct" in args:
            config_args["ram_threshold_pct"] = args["ram_threshold_pct"]
        cfg = saver.configure(**config_args)
        return {"status": "configured", "config": cfg.to_dict()}

    if name == "memory_autosave_status":
        project = args.get("project")
        key = project or "__default__"
        if key not in _autosavers:
            return {
                "status": "not_configured",
                "hint": "Use memory_autosave_configure to enable autosave",
            }
        return _autosavers[key].status()

    return {"error": f"Unknown tool: {name}"}


# ------------------------------------------------------------------
# Resources
# ------------------------------------------------------------------


@app.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="engram://memories/default",
            name="All memories (default namespace)",
            mimeType="application/json",
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    # engram://memories/{namespace}
    parts = str(uri).replace("engram://", "").split("/")
    namespace = parts[1] if len(parts) > 1 else "default"
    entries = _mem(namespace).list(limit=1000)
    data = [
        {
            "id": e.id,
            "content": e.content,
            "type": e.memory_type.value,
            "importance": e.importance,
            "tags": e.tags,
        }
        for e in entries
    ]
    return json.dumps(data, default=str)


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
