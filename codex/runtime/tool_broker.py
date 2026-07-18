from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ToolCallResult, ToolDescriptor, utc_now


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
MAX_MCP_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass
class ToolHealthState:
    successes: int = 0
    failures: int = 0
    semantic_failures: int = 0
    consecutive_failures: int = 0
    average_latency_ms: float = 0.0
    cooldown_until: float = 0.0
    last_error: str = ""

CAPABILITY_MARKERS: dict[str, frozenset[str]] = {
    "page_fetch": frozenset({"fetch", "http", "request", "curl", "webfetch", "web", "url", "uri"}),
    "browser_automation": frozenset({"browser", "playwright", "navigate", "click", "dom", "screenshot"}),
    "dns_resolve": frozenset({"dns", "resolve", "dig", "host"}),
    "subdomain_enum": frozenset({"subdomain", "subfinder", "amass"}),
    "port_scan": frozenset({"nmap", "masscan", "port", "scan"}),
    "http_fingerprint": frozenset({"fingerprint", "wappalyzer", "httpx", "technology"}),
    "cve_search": frozenset({"cve", "vulnerability", "nvd"}),
    "binary_reverse": frozenset({"ida", "ghidra", "radare", "rizin", "disassemble", "decompile", "binary"}),
    "apk_decompile": frozenset({"jadx", "apk", "android", "decompile"}),
    "android_static_analysis": frozenset({"jadx", "apk", "android", "manifest"}),
    "code_analysis": frozenset({"code", "source", "repository", "audit", "search"}),
    "source_inventory": frozenset({"source", "repository", "tree", "files"}),
    "code_generation": frozenset({"codex", "agent", "generate", "code", "harness"}),
    "test_harness": frozenset({"test", "harness", "runner"}),
    "reasoning": frozenset({"codex", "agent", "reason", "analyze", "planner"}),
    "controlled_validation": frozenset({"validate", "reproduce", "exploit", "execute", "runner"}),
    "impact_analysis": frozenset({"impact", "analyze", "reason", "verify"}),
    "coverage_analysis": frozenset({"coverage", "review", "analyze", "reason"}),
    "cleanup": frozenset({"cleanup", "remove", "restore", "rollback"}),
    "rollback": frozenset({"rollback", "restore", "cleanup"}),
    "report_generation": frozenset({"report", "write", "generate", "codex", "agent"}),
    "model_probe": frozenset({"model", "prompt", "chat", "completion"}),
    "prompt_evaluation": frozenset({"prompt", "evaluation", "eval", "model"}),
    "evaluation_analysis": frozenset({"evaluation", "metrics", "analyze"}),
    "identity_inventory": frozenset({"identity", "directory", "ldap", "principal", "kerberos"}),
    "cloud_inventory": frozenset({"cloud", "aws", "azure", "gcp", "iam"}),
    "directory_inventory": frozenset({"directory", "ldap", "active", "inventory"}),
    "identity_validation": frozenset({"identity", "permission", "role", "validate"}),
    "graph_analysis": frozenset({"graph", "path", "analyze"}),
    "environment_inventory": frozenset({"environment", "inventory", "asset", "host"}),
    "technique_execution": frozenset({"atomic", "technique", "execute", "attack"}),
    "attack_mapping": frozenset({"attack", "mitre", "technique", "mapping"}),
    "telemetry_analysis": frozenset({"telemetry", "log", "event", "detection"}),
    "target_intake": frozenset({"target", "inspect", "inventory", "fetch", "analyze"}),
}

CAPABILITY_ALIASES: dict[str, frozenset[str]] = {
    "page_fetch": frozenset({"page_fetch", "content_extract", "http_fetch"}),
    "browser_automation": frozenset({"browser_automation", "dom_snapshot", "screenshot"}),
    "binary_reverse": frozenset({"binary_reverse", "protocol_analysis", "decompile", "disassemble"}),
    "apk_decompile": frozenset({"apk_decompile", "android_static_analysis"}),
    "reasoning": frozenset({"reasoning", "code_generation", "ai_coding"}),
    "report_generation": frozenset({"report_generation", "reasoning", "code_generation"}),
    "impact_analysis": frozenset({"impact_analysis", "reasoning"}),
    "coverage_analysis": frozenset({"coverage_analysis", "reasoning"}),
    "cleanup": frozenset({"cleanup", "rollback"}),
}


class StdioMcpClient:
    def __init__(self, server_name: str, command: str, args: Sequence[str], env: Mapping[str, str] | None = None) -> None:
        self.server_name = server_name
        environment = dict(os.environ)
        environment.update({str(key): str(value) for key, value in dict(env or {}).items()})
        self.process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        self._next_id = 1
        self._responses: dict[int, Mapping[str, Any]] = {}
        self._abandoned: set[int] = set()
        self._condition = threading.Condition()
        self._stderr: queue.Queue[str] = queue.Queue(maxsize=128)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._error_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._error_reader.start()
        self._initialize()

    def _read_stdout(self) -> None:
        if self.process.stdout is None:
            return
        for line in self.process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            response_id = payload.get("id") if isinstance(payload, Mapping) else None
            if isinstance(response_id, int):
                with self._condition:
                    if response_id in self._abandoned:
                        self._abandoned.discard(response_id)
                    else:
                        self._responses[response_id] = payload
                    self._condition.notify_all()

    def _read_stderr(self) -> None:
        if self.process.stderr is None:
            return
        for line in self.process.stderr:
            try:
                self._stderr.put_nowait(line.rstrip())
            except queue.Full:
                try:
                    self._stderr.get_nowait()
                    self._stderr.put_nowait(line.rstrip())
                except queue.Empty:
                    pass

    def _send(self, payload: Mapping[str, Any]) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(f"mcp_server_exited:{self.server_name}:{self.process.returncode}")
        if self.process.stdin is None:
            raise RuntimeError(f"mcp_server_stdin_missing:{self.server_name}")
        self.process.stdin.write(json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 30.0) -> Mapping[str, Any]:
        with self._condition:
            request_id = self._next_id
            self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params or {})})
        deadline = time.monotonic() + max(0.1, timeout)
        with self._condition:
            while request_id not in self._responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._abandoned.add(request_id)
                    if len(self._abandoned) > 1024:
                        self._abandoned.pop()
                    try:
                        self.notify(
                            "notifications/cancelled",
                            {"requestId": request_id, "reason": f"timeout:{method}"},
                        )
                    except Exception:
                        pass
                    raise TimeoutError(f"mcp_request_timeout:{self.server_name}:{method}")
                self._condition.wait(timeout=min(remaining, 0.25))
                if self.process.poll() is not None and request_id not in self._responses:
                    raise RuntimeError(f"mcp_server_exited:{self.server_name}:{self.process.returncode}")
            response = self._responses.pop(request_id)
        if "error" in response:
            raise RuntimeError(f"mcp_error:{self.server_name}:{method}:{response['error']}")
        result = response.get("result")
        return result if isinstance(result, Mapping) else {"value": result}

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": dict(params or {})})

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "codex-redteam-runtime", "version": "1"},
            },
            timeout=20.0,
        )
        self.notify("notifications/initialized")

    def list_tools(self) -> Sequence[Mapping[str, Any]]:
        collected: list[Mapping[str, Any]] = []
        cursor = ""
        for _ in range(100):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=30.0)
            tools = result.get("tools")
            if isinstance(tools, list):
                collected.extend(item for item in tools if isinstance(item, Mapping))
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return tuple(collected)

    def call_tool(self, name: str, arguments: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3.0)


class HttpMcpClient:
    def __init__(self, server_name: str, url: str, headers: Mapping[str, str] | None = None) -> None:
        self.server_name = server_name
        self.url = url
        self.headers = {str(key): str(value) for key, value in dict(headers or {}).items()}
        self.session_id = ""
        self._next_id = 1
        self._initialize()

    def _decode_response(self, response: Any) -> Mapping[str, Any]:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_MCP_RESPONSE_BYTES:
            raise ValueError(f"mcp_http_response_too_large:{self.server_name}")
        encoded = response.read(MAX_MCP_RESPONSE_BYTES + 1)
        if len(encoded) > MAX_MCP_RESPONSE_BYTES:
            raise ValueError(f"mcp_http_response_too_large:{self.server_name}")
        raw = encoded.decode("utf-8", errors="replace")
        content_type = str(response.headers.get("Content-Type") or "").casefold()
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self.session_id = str(session_id)
        if "text/event-stream" in content_type or raw.lstrip().startswith("event:"):
            data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
            if not data_lines:
                raise ValueError(f"mcp_sse_data_missing:{self.server_name}")
            raw = data_lines[-1]
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError(f"mcp_http_invalid_response:{self.server_name}")
        return payload

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float = 30.0) -> Mapping[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params or {})},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=max(0.1, timeout)) as response:
                payload = self._decode_response(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"mcp_http_error:{self.server_name}:{exc.code}:{detail}") from exc
        if payload.get("id") != request_id:
            raise ValueError(f"mcp_http_response_id_mismatch:{self.server_name}")
        if "error" in payload:
            raise RuntimeError(f"mcp_error:{self.server_name}:{method}:{payload['error']}")
        result = payload.get("result")
        return result if isinstance(result, Mapping) else {"value": result}

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        body = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": dict(params or {})},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10.0):
                return
        except urllib.error.HTTPError as exc:
            if exc.code not in {202, 204}:
                raise

    def _initialize(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "codex-redteam-runtime", "version": "1"},
            },
            timeout=20.0,
        )
        self.notify("notifications/initialized")

    def list_tools(self) -> Sequence[Mapping[str, Any]]:
        collected: list[Mapping[str, Any]] = []
        cursor = ""
        for _ in range(100):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=30.0)
            tools = result.get("tools")
            if isinstance(tools, list):
                collected.extend(item for item in tools if isinstance(item, Mapping))
            next_cursor = result.get("nextCursor")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return tuple(collected)

    def call_tool(self, name: str, arguments: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)}, timeout=timeout)

    def close(self) -> None:
        return


Adapter = Callable[[Mapping[str, Any]], Any]


class ToolBroker:
    def __init__(self, *, tool_priority: Sequence[str] = ()) -> None:
        self.tool_priority = tuple(
            (re.sub(r"[^a-z0-9]+", "", name.casefold()), index)
            for index, name in enumerate(tool_priority)
            if str(name).strip()
        )
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._adapters: dict[str, Adapter] = {}
        self._clients: dict[str, StdioMcpClient | HttpMcpClient] = {}
        self._server_configs: dict[str, tuple[str, tuple[Any, ...]]] = {}
        self._config_paths: list[Path] = []
        self._last_refresh = 0.0
        self._lifecycle_lock = threading.RLock()
        self._active_calls = 0
        self._health: dict[str, ToolHealthState] = {}
        self._discovery_errors: list[str] = []
        self._capability_overrides: dict[str, tuple[str, ...]] = {}

    @property
    def discovery_errors(self) -> tuple[str, ...]:
        return tuple(self._discovery_errors)

    def health_snapshot(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        return {
            name: {**asdict(state), "cooling_down": state.cooldown_until > now}
            for name, state in self._health.items()
        }

    def _health_for(self, qualified_name: str) -> ToolHealthState:
        return self._health.setdefault(qualified_name, ToolHealthState())

    def _record_result(self, qualified_name: str, *, success: bool, latency_ms: float, error: str = "") -> None:
        state = self._health_for(qualified_name)
        total = state.successes + state.failures
        state.average_latency_ms = ((state.average_latency_ms * total) + latency_ms) / (total + 1)
        if success:
            state.successes += 1
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            state.last_error = ""
            return
        state.failures += 1
        state.consecutive_failures += 1
        state.last_error = error
        if state.consecutive_failures >= 3:
            state.cooldown_until = time.monotonic() + min(300.0, 15.0 * state.consecutive_failures)

    def record_semantic_failure(self, descriptor: ToolDescriptor, reason: str) -> None:
        state = self._health_for(descriptor.qualified_name)
        state.semantic_failures += 1
        state.consecutive_failures += 1
        state.last_error = reason
        if state.consecutive_failures >= 3:
            state.cooldown_until = time.monotonic() + min(300.0, 15.0 * state.consecutive_failures)

    def record_semantic_success(self, descriptor: ToolDescriptor) -> None:
        state = self._health_for(descriptor.qualified_name)
        state.consecutive_failures = 0
        state.semantic_failures = max(0, state.semantic_failures - 1)
        state.cooldown_until = 0.0

    def _priority_for(self, *names: str) -> int:
        candidates = tuple(re.sub(r"[^a-z0-9]+", "", name.casefold()) for name in names if name)
        for preferred, priority in self.tool_priority:
            if any(preferred == candidate or preferred in candidate or candidate in preferred for candidate in candidates):
                return priority
        return 100

    @staticmethod
    def infer_capabilities(name: str, description: str = "", schema: Mapping[str, Any] | None = None) -> tuple[str, ...]:
        explicit = (schema or {}).get("x-capabilities")
        if isinstance(explicit, list) and explicit:
            return tuple(dict.fromkeys(str(item).strip().casefold().replace("-", "_") for item in explicit if str(item).strip()))
        schema_text = json.dumps(schema or {}, ensure_ascii=False, default=str)
        tokens = set(TOKEN_RE.findall(f"{name} {description} {schema_text}".casefold()))
        capabilities: list[str] = []
        for capability, markers in CAPABILITY_MARKERS.items():
            if tokens & markers:
                capabilities.append(capability)
        return tuple(capabilities)

    def _capabilities_for(
        self,
        server_name: str,
        name: str,
        description: str,
        schema: Mapping[str, Any],
    ) -> tuple[str, ...]:
        for key in (f"{server_name}:{name}", name, server_name):
            override = self._capability_overrides.get(key.casefold())
            if override:
                return override
        return self.infer_capabilities(name, description, schema)

    def register_adapter(
        self,
        *,
        name: str,
        capabilities: Sequence[str],
        adapter: Adapter,
        description: str = "",
        server: str = "builtin",
        priority: int = 10,
        input_schema: Mapping[str, Any] | None = None,
    ) -> ToolDescriptor:
        descriptor = ToolDescriptor(
            server=server,
            name=name,
            description=description,
            input_schema=dict(input_schema or {"type": "object"}),
            capabilities=tuple(dict.fromkeys(str(item) for item in capabilities)),
            source="registered-adapter",
            healthy=True,
            priority=priority,
        )
        self._descriptors[descriptor.qualified_name] = descriptor
        self._adapters[descriptor.qualified_name] = adapter
        return descriptor

    def discover_from_configs(self, paths: Sequence[Path]) -> tuple[ToolDescriptor, ...]:
        for path in paths:
            resolved_path = path.expanduser().resolve(strict=False)
            if resolved_path not in self._config_paths:
                self._config_paths.append(resolved_path)
            if not path.is_file():
                continue
            try:
                config = tomllib.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                self._discovery_errors.append(f"config:{path}:{exc}")
                continue
            automation = config.get("automation") if isinstance(config.get("automation"), Mapping) else {}
            raw_overrides = automation.get("tool_capabilities")
            if isinstance(raw_overrides, Mapping):
                for tool_name, raw_capabilities in raw_overrides.items():
                    if not isinstance(raw_capabilities, list):
                        continue
                    capabilities = tuple(
                        dict.fromkeys(
                            str(item).strip().casefold().replace("-", "_")
                            for item in raw_capabilities
                            if str(item).strip()
                        )
                    )
                    if capabilities:
                        self._capability_overrides.setdefault(str(tool_name).casefold(), capabilities)
            servers = config.get("mcp_servers") or config.get("mcpServers") or {}
            if not isinstance(servers, Mapping):
                continue
            for server_name, raw_server in servers.items():
                if not isinstance(raw_server, Mapping) or raw_server.get("enabled") is False or raw_server.get("disabled") is True:
                    continue
                if str(server_name).casefold() in {"codex-redteam-orchestrator", "codex-redteam-runtime"}:
                    continue
                command = raw_server.get("command")
                url = raw_server.get("url") or raw_server.get("http_url")
                if isinstance(command, str) and command.strip():
                    raw_args = raw_server.get("args", ())
                    args = tuple(str(item) for item in raw_args) if isinstance(raw_args, list) else tuple(shlex.split(str(raw_args)))
                    raw_env = raw_server.get("env", {})
                    env = {str(key): str(value) for key, value in raw_env.items()} if isinstance(raw_env, Mapping) else {}
                    self._server_configs[str(server_name)] = ("stdio", (command, args, env))
                    self._discover_stdio(str(server_name), command, args, env)
                elif isinstance(url, str) and url.strip():
                    raw_headers = raw_server.get("headers", {})
                    headers = {str(key): str(value) for key, value in raw_headers.items()} if isinstance(raw_headers, Mapping) else {}
                    token_env = str(raw_server.get("bearer_token_env_var") or "").strip()
                    if token_env and os.environ.get(token_env):
                        headers.setdefault("Authorization", f"Bearer {os.environ[token_env]}")
                    self._server_configs[str(server_name)] = ("http", (url.strip(), headers))
                    self._discover_http(str(server_name), url.strip(), headers)
                else:
                    self._discovery_errors.append(f"server:{server_name}:unsupported_transport")
        return self.descriptors()

    def refresh(self, *, force: bool = False) -> tuple[ToolDescriptor, ...]:
        with self._lifecycle_lock:
            now = time.monotonic()
            if self._active_calls or (not force and now - self._last_refresh < 10.0):
                return self.descriptors()
            self._last_refresh = now
            for client in self._clients.values():
                client.close()
            self._clients.clear()
            self._server_configs.clear()
            self._capability_overrides.clear()
            self._discovery_errors.clear()
            for qualified in [
                name
                for name, descriptor in self._descriptors.items()
                if descriptor.source.startswith("live-mcp")
            ]:
                self._descriptors.pop(qualified, None)
            return self.discover_from_configs(tuple(self._config_paths))

    def _discover_stdio(self, server_name: str, command: str, args: Sequence[str], env: Mapping[str, str]) -> None:
        existing = self._clients.get(server_name)
        if isinstance(existing, StdioMcpClient) and existing.process.poll() is None:
            return
        if existing is not None:
            existing.close()
            self._clients.pop(server_name, None)
        try:
            client = StdioMcpClient(server_name, command, args, env)
            tools = client.list_tools()
        except Exception as exc:
            self._discovery_errors.append(f"server:{server_name}:{exc}")
            return
        self._clients[server_name] = client
        for item in tools:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = str(item.get("description") or "")
            schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), Mapping) else {"type": "object"}
            capabilities = self._capabilities_for(server_name, name, description, schema)
            descriptor = ToolDescriptor(
                server=server_name,
                name=name,
                description=description,
                input_schema=dict(schema),
                capabilities=capabilities,
                source="live-mcp",
                healthy=True,
                priority=self._priority_for(server_name, name, f"{server_name}:{name}"),
            )
            self._descriptors[descriptor.qualified_name] = descriptor

    def _discover_http(self, server_name: str, url: str, headers: Mapping[str, str]) -> None:
        if server_name in self._clients:
            return
        try:
            client = HttpMcpClient(server_name, url, headers)
            tools = client.list_tools()
        except Exception as exc:
            self._discovery_errors.append(f"server:{server_name}:{exc}")
            return
        self._clients[server_name] = client
        for item in tools:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = str(item.get("description") or "")
            schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), Mapping) else {"type": "object"}
            descriptor = ToolDescriptor(
                server=server_name,
                name=name,
                description=description,
                input_schema=dict(schema),
                capabilities=self._capabilities_for(server_name, name, description, schema),
                source="live-mcp-http",
                healthy=True,
                priority=self._priority_for(server_name, name, f"{server_name}:{name}"),
            )
            self._descriptors[descriptor.qualified_name] = descriptor

    def _restart_server(self, server_name: str) -> None:
        config = self._server_configs.get(server_name)
        if config is None:
            return
        client = self._clients.pop(server_name, None)
        if client is not None:
            client.close()
        for qualified in [name for name, item in self._descriptors.items() if item.server == server_name]:
            self._descriptors.pop(qualified, None)
        transport, values = config
        if transport == "stdio":
            command, args, env = values
            self._discover_stdio(server_name, command, args, env)
        else:
            url, headers = values
            self._discover_http(server_name, url, headers)

    def descriptors(self) -> tuple[ToolDescriptor, ...]:
        return tuple(sorted(self._descriptors.values(), key=lambda item: (item.priority, item.qualified_name.casefold())))

    @staticmethod
    def _supports(descriptor: ToolDescriptor, capability: str) -> bool:
        normalized = capability.casefold().replace("-", "_")
        accepted = CAPABILITY_ALIASES.get(normalized, frozenset({normalized})) | frozenset({normalized})
        offered = {item.casefold().replace("-", "_") for item in descriptor.capabilities}
        return bool(accepted & offered)

    @classmethod
    def _schema_error(cls, schema: Mapping[str, Any], value: Any, path: str = "arguments") -> str:
        expected_type = schema.get("type")
        type_checks = {
            "object": lambda item: isinstance(item, Mapping),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        if isinstance(expected_type, str) and expected_type in type_checks and not type_checks[expected_type](value):
            return f"{path}:expected_{expected_type}"
        if "enum" in schema and isinstance(schema["enum"], list) and value not in schema["enum"]:
            return f"{path}:enum"
        if isinstance(value, Mapping):
            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            missing = [str(item) for item in required if str(item) not in value]
            if missing:
                return f"tool_schema_required_missing:{','.join(missing)}"
            properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
            if schema.get("additionalProperties") is False:
                unknown = [str(key) for key in value if key not in properties]
                if unknown:
                    return f"{path}:additional_properties:{','.join(unknown)}"
            for key, item in value.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, Mapping):
                    error = cls._schema_error(child_schema, item, f"{path}.{key}")
                    if error:
                        return error
        if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
            for index, item in enumerate(value):
                error = cls._schema_error(schema["items"], item, f"{path}[{index}]")
                if error:
                    return error
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if schema.get("minimum") is not None and value < schema["minimum"]:
                return f"{path}:minimum"
            if schema.get("maximum") is not None and value > schema["maximum"]:
                return f"{path}:maximum"
        if isinstance(value, str):
            if schema.get("minLength") is not None and len(value) < int(schema["minLength"]):
                return f"{path}:minLength"
            if schema.get("maxLength") is not None and len(value) > int(schema["maxLength"]):
                return f"{path}:maxLength"
        return ""

    def select(self, capabilities: Sequence[str], *, exclude: Sequence[str] = ()) -> ToolDescriptor | None:
        excluded = set(exclude)
        candidates: list[tuple[int, int, str, ToolDescriptor]] = []
        for descriptor in self.descriptors():
            if descriptor.qualified_name in excluded or not descriptor.healthy:
                continue
            health = self._health_for(descriptor.qualified_name)
            if health.cooldown_until > time.monotonic():
                continue
            for capability_index, capability in enumerate(capabilities):
                if self._supports(descriptor, capability):
                    health_penalty = health.consecutive_failures * 25 + health.semantic_failures * 5
                    latency_penalty = min(100, int(health.average_latency_ms / 100))
                    candidates.append((capability_index, descriptor.priority + health_penalty + latency_penalty, descriptor.qualified_name, descriptor))
                    break
        candidates.sort(key=lambda item: (item[0], item[1], item[2].casefold()))
        return candidates[0][3] if candidates else None

    def explain_selection(self, capabilities: Sequence[str], *, exclude: Sequence[str] = ()) -> dict[str, Any]:
        excluded = set(exclude)
        candidates: list[dict[str, Any]] = []
        for descriptor in self.descriptors():
            matches = [capability for capability in capabilities if self._supports(descriptor, capability)]
            if not matches:
                continue
            health = self._health_for(descriptor.qualified_name)
            candidates.append(
                {
                    "tool": descriptor.qualified_name,
                    "capability_match": matches,
                    "source": descriptor.source,
                    "priority": descriptor.priority,
                    "excluded": descriptor.qualified_name in excluded,
                    "cooling_down": health.cooldown_until > time.monotonic(),
                    "consecutive_failures": health.consecutive_failures,
                    "average_latency_ms": round(health.average_latency_ms, 2),
                }
            )
        selected = self.select(capabilities, exclude=exclude)
        return {
            "selected_tool": selected.qualified_name if selected else "",
            "required_capabilities": list(capabilities),
            "fallback_reason": "prior_tool_failed" if excluded and selected else "",
            "candidates": candidates,
        }

    def call(self, descriptor: ToolDescriptor, arguments: Mapping[str, Any], *, timeout: float = 60.0) -> ToolCallResult:
        started_at = utc_now()
        started_clock = time.monotonic()
        qualified = descriptor.qualified_name
        schema_error = self._schema_error(descriptor.input_schema, arguments)
        if schema_error:
            return ToolCallResult(
                status="failed",
                error=schema_error,
                tool=qualified,
                started_at=started_at,
                retryable=False,
            )
        with self._lifecycle_lock:
            self._active_calls += 1
        try:
            if qualified in self._adapters:
                output = self._adapters[qualified](dict(arguments))
            else:
                client = self._clients.get(descriptor.server)
                if isinstance(client, StdioMcpClient) and client.process.poll() is not None:
                    self._restart_server(descriptor.server)
                    client = self._clients.get(descriptor.server)
                if client is None:
                    raise RuntimeError(f"mcp_client_missing:{descriptor.server}")
                output = client.call_tool(descriptor.name, arguments, timeout=timeout)
            if isinstance(output, Mapping) and output.get("isError") is True:
                self._record_result(qualified, success=False, latency_ms=(time.monotonic() - started_clock) * 1000, error="mcp_tool_error")
                return ToolCallResult(
                    status="failed",
                    output=output,
                    error="mcp_tool_error",
                    tool=qualified,
                    started_at=started_at,
                    retryable=False,
                )
            self._record_result(qualified, success=True, latency_ms=(time.monotonic() - started_clock) * 1000)
            return ToolCallResult(status="success", output=output, tool=qualified, started_at=started_at)
        except (TimeoutError, OSError, ConnectionError, BrokenPipeError) as exc:
            self._record_result(qualified, success=False, latency_ms=(time.monotonic() - started_clock) * 1000, error=str(exc))
            return ToolCallResult(
                status="failed",
                error=str(exc),
                tool=qualified,
                started_at=started_at,
                retryable=True,
            )
        except Exception as exc:
            self._record_result(qualified, success=False, latency_ms=(time.monotonic() - started_clock) * 1000, error=str(exc))
            return ToolCallResult(
                status="failed",
                error=str(exc),
                tool=qualified,
                started_at=started_at,
                retryable=False,
            )
        finally:
            with self._lifecycle_lock:
                self._active_calls = max(0, self._active_calls - 1)

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def __enter__(self) -> "ToolBroker":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
