import contextlib
import json
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount


UPSTREAM_URL = os.environ.get("N3LOCAL_UPSTREAM_URL", "http://host.docker.internal:4103/mcp")
UPSTREAM_TOKEN = os.environ.get("N3LOCAL_TOKEN", "")
REQUEST_TIMEOUT = float(os.environ.get("N3LOCAL_PROXY_TIMEOUT_SECONDS", "120"))

mcp = FastMCP(
    "N3uron Core Ops",
    instructions=(
        "Use these tools for core N3uron operational status checks. "
        "This server intentionally exposes only a small curated subset of the upstream tools "
        "to keep local-model tool context manageable."
    ),
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
)


def _auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if UPSTREAM_TOKEN:
        headers["Authorization"] = f"Bearer {UPSTREAM_TOKEN}"
    return headers


def _coerce_content(result: Any) -> Any:
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent

    text_chunks: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            text_chunks.append(text)

    if not text_chunks:
        return {"ok": True, "content": []}

    if len(text_chunks) == 1:
        text = text_chunks[0]
        with contextlib.suppress(json.JSONDecodeError):
            return json.loads(text)
        return text

    return "\n\n".join(text_chunks)


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _safe_div_pct(used: float | int | None, total: float | int | None, *, scale: float = 1.0) -> float | None:
    if used is None or total in (None, 0):
        return None
    return round((float(used) / float(total)) * 100 / scale, 2)


def _usage_pair(value: Any) -> tuple[float | int | None, float | int | None]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return value[0], value[1]
    return None, None


def _compact_alarm_items(items: list[Any], limit: int = 10) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "path": item.get("path") or item.get("fullPath"),
                "priority": item.get("priority"),
                "status": item.get("status"),
                "text": item.get("text") or item.get("description") or item.get("name"),
                "timestamp": item.get("timestamp") or item.get("activeTs") or item.get("ts"),
            }
        )
    return compact


def _compact_module_items(items: list[Any], limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "name": item.get("name") or item.get("moduleName"),
                "type": item.get("type") or item.get("moduleType"),
                "status": item.get("status") or item.get("state"),
                "enabled": item.get("enabled"),
            }
        )
    return compact


def _compact_link_items(items: list[Any], limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "remoteNode": item.get("remoteNode") or item.get("name"),
                "status": item.get("status") or item.get("state"),
                "mode": item.get("mode"),
                "quality": item.get("quality"),
            }
        )
    return compact


def _compact_system_status(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw

    n3 = _first_mapping(raw.get("n3"))
    sys_map = _first_mapping(raw.get("sys"), raw.get("system"), raw.get("status"), raw)
    usage = _first_mapping(sys_map.get("usage"), sys_map)
    cpu_used, cpu_total = _usage_pair(usage.get("cpu") or sys_map.get("cpuUsage"))
    ram_used, ram_total = _usage_pair(usage.get("ram") or usage.get("memory") or sys_map.get("ramUsage"))
    disk_used, disk_total = _usage_pair(usage.get("disk") or sys_map.get("diskUsage"))
    uptime_ms = n3.get("up") if isinstance(n3.get("up"), (int, float)) else sys_map.get("up")
    errors = n3.get("errors")
    if not isinstance(errors, list):
        errors = raw.get("errors") if isinstance(raw.get("errors"), list) else []

    summary = {
        "node": n3.get("node") or sys_map.get("hostname"),
        "hostname": sys_map.get("hostname"),
        "versions": n3.get("versions"),
        "healthy": len(errors) == 0,
        "errorCount": len(errors),
        "tags": n3.get("tags"),
        "uptimeMs": uptime_ms,
        "uptimeHours": round(float(uptime_ms) / 3_600_000, 2) if isinstance(uptime_ms, (int, float)) else None,
        "cpuPercent": _safe_div_pct(cpu_used, cpu_total),
        "ramPercent": _safe_div_pct(ram_used, ram_total),
        "diskPercent": _safe_div_pct(disk_used, disk_total),
        "standby": sys_map.get("standby"),
        "cpuModel": sys_map.get("cpu")[0] if isinstance(sys_map.get("cpu"), list) and sys_map.get("cpu") else None,
        "cpuRaw": [cpu_used, cpu_total] if cpu_used is not None else None,
        "ramBytes": {"used": ram_used, "total": ram_total} if ram_used is not None else None,
        "diskBytes": {"used": disk_used, "total": disk_total} if disk_used is not None else None,
    }
    if summary["node"] or summary["cpuPercent"] is not None or summary["uptimeMs"] is not None:
        return summary
    return raw


def _compact_system_info(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw

    memory = _first_mapping(raw.get("memory"))
    swap = _first_mapping(raw.get("swap"))
    disks = raw.get("disks") if isinstance(raw.get("disks"), list) else []
    first_disk = disks[0] if disks and isinstance(disks[0], dict) else {}
    cpu = raw.get("cpu") if isinstance(raw.get("cpu"), list) else []

    summary = {
        "hostname": raw.get("hostname"),
        "os": _first_mapping(raw.get("os")),
        "uptimeSeconds": raw.get("uptime"),
        "cpuUsagePercent": raw.get("cpuUsage"),
        "coreCount": raw.get("coreCount"),
        "memoryBytes": {
            "used": memory.get("used"),
            "total": memory.get("total"),
            "available": memory.get("available"),
        }
        if memory
        else None,
        "swapBytes": {"used": swap.get("used"), "total": swap.get("total")} if swap else None,
        "primaryDisk": {
            "filesystem": first_disk.get("filesystem"),
            "mount": first_disk.get("mount"),
            "capacity": first_disk.get("capacity"),
            "usage": first_disk.get("usage"),
        }
        if first_disk
        else None,
        "cpuModel": cpu[0].get("brand") if cpu and isinstance(cpu[0], dict) else None,
    }
    if summary["hostname"] or summary["cpuUsagePercent"] is not None:
        return summary
    return raw


def _compact_alarm_get(raw: Any) -> Any:
    if isinstance(raw, list):
        return {
            "count": len(raw),
            "alarms": _compact_alarm_items(raw),
        }
    return raw


def _compact_module_details(raw: Any) -> Any:
    if isinstance(raw, list):
        by_status: dict[str, int] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or item.get("state") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "count": len(raw),
            "byStatus": by_status,
            "modules": _compact_module_items(raw),
        }
    return raw


def _compact_link_get(raw: Any) -> Any:
    if isinstance(raw, list):
        return {
            "count": len(raw),
            "links": _compact_link_items(raw),
        }
    return raw


def _compact_result(tool_name: str, raw: Any) -> Any:
    compactors = {
        "system_status": _compact_system_status,
        "system_info": _compact_system_info,
        "alarm_get": _compact_alarm_get,
        "module_details": _compact_module_details,
        "link_get": _compact_link_get,
    }
    compact = compactors.get(tool_name)
    return compact(raw) if compact else raw


async def call_upstream_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    async with httpx.AsyncClient(headers=_auth_headers(), timeout=timeout, follow_redirects=True) as client:
        async with streamable_http_client(UPSTREAM_URL, http_client=client) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments or {})
                return _compact_result(name, _coerce_content(result))


@mcp.tool()
async def system_status() -> Any:
    """Get node health, uptime, CPU, RAM, and disk usage."""
    return await call_upstream_tool("system_status")


@mcp.tool()
async def system_info() -> Any:
    """Get host hardware, OS, memory, storage, and realtime metrics."""
    return await call_upstream_tool("system_info")


@mcp.tool()
async def system_error_count() -> Any:
    """Get current counts of errors and warnings on the N3uron node."""
    return await call_upstream_tool("system_errorCount")


@mcp.tool()
async def module_details() -> Any:
    """Get details for all instantiated modules running on the node."""
    return await call_upstream_tool("module_details")


@mcp.tool()
async def alarm_get(
    path: str = "/",
    recurrent: bool = True,
    min_priority: int | None = 2,
    max_priority: int | None = None,
) -> Any:
    """Retrieve alarms, optionally filtered by path and priority."""
    args: dict[str, Any] = {
        "path": path,
        "options_recurrent": recurrent,
    }
    if min_priority is not None:
        args["options_filter_minPriority"] = min_priority
    if max_priority is not None:
        args["options_filter_maxPriority"] = max_priority
    return await call_upstream_tool("alarm_get", args)


@mcp.tool()
async def link_get() -> Any:
    """Get current link state and health for distributed-node connections."""
    return await call_upstream_tool("link_get")


@mcp.tool()
async def ops_summary_daily(path: str | None = None, include_forecast: bool = False) -> Any:
    """Generate a short daily operations summary with alarms, KPIs, and node health."""
    args: dict[str, Any] = {"include_forecast": include_forecast}
    if path:
        args["path"] = path
    return await call_upstream_tool("ops_summary_daily", args)


@mcp.tool()
async def system_audit_node(path: str | None = None, max_backup_age_hours: int | None = None) -> Any:
    """Audit node health, tag quality, and backup freshness."""
    args: dict[str, Any] = {}
    if path:
        args["path"] = path
    if max_backup_age_hours is not None:
        args["max_backup_age_hours"] = max_backup_age_hours
    return await call_upstream_tool("system_audit_node", args)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[Mount("/", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)
