from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

app = Server("n3ops")

_ALLOWED_TOOL_NAMES = [
    "alarm_get",
    "alarm_history",
    "system_status",
    "tag_find",
    "tag_describe",
    "tag_history",
    "ops_summary_daily",
    "ops_alarm_analyze_patterns",
    "ops_downtime_summarize",
    "ops_maintenance_recommend",
    "ops_performance_compare_yield",
    "ops_performance_scan_fleet",
    "ops_performance_score_assets",
    "ops_performance_trend_assets",
]
_ALLOWED_TOOL_SET = set(_ALLOWED_TOOL_NAMES)
_TOOL_CACHE: dict[str, Tool] = {}
_N3LOCAL_URL = os.getenv("N3LOCAL_URL", "http://host.docker.internal:4103/mcp")
_HTTP_TIMEOUT = float(os.getenv("N3OPS_HTTP_TIMEOUT_SECONDS", "120"))
_COMPACT_TOOL_DESCRIPTIONS = {
    "alarm_get": "List current alarms with optional path, status, and priority filters.",
    "alarm_count": "Count current alarms with optional path, status, and priority filters.",
    "alarm_history": "Get historical alarm events for an alarm or subtree in a time range.",
    "module_details": "Get runtime details for all active module instances.",
    "module_getInstances": "List active module instances with optional filtering.",
    "module_getConfigData": "Read a module configuration section by module name and config name.",
    "system_status": "Get node uptime and current CPU, RAM, and disk usage.",
    "system_info": "Get detailed node hardware and operating system information.",
    "system_audit_node": "Audit node health, tag quality, history coverage, and backup freshness.",
    "system_tags_detect_anomalies": "Detect unusual recent behavior for one or more numeric tags.",
    "tag_find": "Find tags by path pattern and metadata filters.",
    "tag_describe": "Describe tags under a path prefix, optionally with current values.",
    "tag_history": "Read historical samples or aggregates for one or more tags.",
    "ops_summary_daily": "Generate a short daily plant status summary.",
    "ops_alarm_analyze_patterns": "Rank repeated alarms, bursts, and recurring fault patterns.",
    "ops_downtime_summarize": "Explain daytime downtime, affected assets, and likely causes.",
    "ops_maintenance_recommend": "Generate prioritized maintenance actions from recent performance and alarms.",
    "ops_performance_compare_yield": "Compare actual and expected energy yield.",
    "ops_performance_scan_fleet": "Rank worst-performing stations or inverters for a period.",
    "ops_performance_score_assets": "Score stations or inverters by recent performance and alarms.",
    "ops_performance_trend_assets": "Detect degrading assets and quantify the weekly trend slope.",
}
_SCHEMA_KEYS = {"type", "properties", "required", "items", "enum", "oneOf", "anyOf"}


def _read_env_fallback(key: str) -> str | None:
    env_path = Path("/app/.env")
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name == key:
            return value.strip().strip('"').strip("'")
    return None


def _n3local_token() -> str | None:
    return os.getenv("N3LOCAL_TOKEN") or _read_env_fallback("N3LOCAL_TOKEN")


def _compact_schema(value):
    if isinstance(value, dict):
        compact = {}
        for key in _SCHEMA_KEYS:
            if key not in value:
                continue
            item = value[key]
            if key in {"properties", "items"}:
                compact[key] = _compact_schema(item)
            elif key in {"oneOf", "anyOf"} and isinstance(item, list):
                compact[key] = [_compact_schema(entry) for entry in item]
            else:
                compact[key] = item
        return compact

    if isinstance(value, list):
        return [_compact_schema(item) for item in value]

    return value


def _compact_tool(tool: Tool) -> Tool:
    payload = tool.model_dump()
    payload["description"] = _COMPACT_TOOL_DESCRIPTIONS.get(tool.name, tool.description)
    if payload.get("inputSchema"):
        payload["inputSchema"] = _compact_schema(payload["inputSchema"])
    return Tool(**payload)


def _usage_percent(values: object) -> float | None:
    if not isinstance(values, list) or len(values) != 2:
        return None

    try:
        used = float(values[0])
        total = float(values[1])
    except (TypeError, ValueError):
        return None

    if total <= 0:
        return None

    return round((used / total) * 100, 2)


def _human_uptime(milliseconds: object) -> str | None:
    try:
        total_ms = int(milliseconds)
    except (TypeError, ValueError):
        return None

    duration = timedelta(milliseconds=total_ms)
    total_seconds = int(duration.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _normalize_system_status(payload: dict) -> dict:
    n3 = payload.get("n3") if isinstance(payload.get("n3"), dict) else {}
    sys_data = payload.get("sys") if isinstance(payload.get("sys"), dict) else {}
    usage = sys_data.get("usage") if isinstance(sys_data.get("usage"), dict) else {}

    uptime_ms = sys_data.get("up", n3.get("up"))
    cpu_usage = usage.get("cpu")
    ram_usage = usage.get("ram")
    disk_usage = usage.get("disk")

    normalized = {
        "source_tool": "system_status",
        "node": n3.get("node"),
        "hostname": sys_data.get("hostname"),
        "pid": n3.get("pid"),
        "timestamp_utc_ms": sys_data.get("ts"),
        "uptime_ms": uptime_ms,
        "uptime_seconds": round(float(uptime_ms) / 1000, 3) if uptime_ms is not None else None,
        "uptime_human": _human_uptime(uptime_ms),
        "versions": n3.get("versions"),
        "tags": n3.get("tags"),
        "standby": sys_data.get("standby"),
        "cpu": {
            "used_hundredths": cpu_usage[0] if isinstance(cpu_usage, list) and len(cpu_usage) == 2 else None,
            "total_hundredths": cpu_usage[1] if isinstance(cpu_usage, list) and len(cpu_usage) == 2 else None,
            "usage_percent": _usage_percent(cpu_usage),
            "hardware": sys_data.get("cpu"),
        },
        "ram": {
            "used_bytes": ram_usage[0] if isinstance(ram_usage, list) and len(ram_usage) == 2 else None,
            "total_bytes": ram_usage[1] if isinstance(ram_usage, list) and len(ram_usage) == 2 else None,
            "usage_percent": _usage_percent(ram_usage),
        },
        "disk": {
            "used_bytes": disk_usage[0] if isinstance(disk_usage, list) and len(disk_usage) == 2 else None,
            "total_bytes": disk_usage[1] if isinstance(disk_usage, list) and len(disk_usage) == 2 else None,
            "usage_percent": _usage_percent(disk_usage),
        },
        "errors": n3.get("errors", []),
    }

    return normalized


def _extract_json_payload(result: CallToolResult) -> dict | None:
    if isinstance(result.structuredContent, dict):
        return result.structuredContent

    if not result.content:
        return None

    if len(result.content) != 1:
        return None

    text = getattr(result.content[0], "text", None)
    if not isinstance(text, str):
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


@asynccontextmanager
async def _session() -> ClientSession:
    headers = {}
    token = _n3local_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(headers=headers, timeout=_HTTP_TIMEOUT) as http_client:
        async with streamable_http_client(_N3LOCAL_URL, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            session = ClientSession(read_stream, write_stream)
            async with session:
                await session.initialize()
                yield session


async def _load_tools() -> list[Tool]:
    if _TOOL_CACHE:
        return [_TOOL_CACHE[name] for name in _ALLOWED_TOOL_NAMES if name in _TOOL_CACHE]

    async with _session() as session:
        response = await session.list_tools()

    for tool in response.tools:
        if tool.name in _ALLOWED_TOOL_SET:
            _TOOL_CACHE[tool.name] = _compact_tool(tool)

    return [_TOOL_CACHE[name] for name in _ALLOWED_TOOL_NAMES if name in _TOOL_CACHE]


def _result_to_content(name: str, result: CallToolResult) -> list[TextContent]:
    payload = _extract_json_payload(result)
    if name == "system_status" and payload is not None:
        return [TextContent(type="text", text=json.dumps(_normalize_system_status(payload), default=str))]

    if result.content:
        return result.content

    if result.structuredContent is not None:
        return [TextContent(type="text", text=json.dumps(result.structuredContent, default=str))]

    if result.isError:
        return [TextContent(type="text", text="Error: upstream N3LOCAL tool call failed")]

    return [TextContent(type="text", text="{}")]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return await _load_tools()


@app.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    if name not in _ALLOWED_TOOL_SET:
        return [TextContent(type="text", text=f"Error: tool '{name}' is not enabled in N3OPS")]

    async with _session() as session:
        result = await session.call_tool(name, arguments or {})

    return _result_to_content(name, result)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
