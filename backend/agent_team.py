"""PydanticAI agent team connected to the Campus Customs MCP server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.toolsets import FilteredToolset

from .audit import AuditTrail
from .models import AgentRole, AgentWorkReport, TicketRunResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MCP_SERVER_SCRIPT = PROJECT_ROOT / "mcp_server" / "server.py"
AUDIT_PATH = Path(
    os.environ.get(
        "CAMPUS_CUSTOMS_AUDIT_PATH",
        PROJECT_ROOT / "output" / "audit_trail.jsonl",
    )
).resolve()
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

MAX_AGENT_STEPS = 10
MAX_DELEGATION_DEPTH = 3
MAX_REQUESTS_PER_STEP = 4
MAX_BOSS_REQUESTS_PER_STEP = 8
MAX_TOOL_CALLS_PER_STEP = 6
MAX_INPUT_TOKENS_PER_STEP = 5_000
MAX_BOSS_INPUT_TOKENS_PER_STEP = 14_000
MAX_OUTPUT_TOKENS_PER_STEP = 1_000
MAX_BOSS_OUTPUT_TOKENS_PER_STEP = 1_200

# Keep tool definitions relevant to each role. Besides reducing model input,
# this prevents a specialist from reaching for unrelated shop records.
ROLE_TOOLS: dict[AgentRole, set[str]] = {
    AgentRole.BOSS: {"list_open_tickets"},
    AgentRole.INVENTORY: {
        "get_customer_order_context",
        "get_bulk_discount_context",
        "get_restock_context",
    },
    AgentRole.ACCOUNTING: {
        "get_accounting_context",
        "get_bulk_discount_context",
    },
    AgentRole.FACILITIES: {"get_rent_notice_context"},
    AgentRole.CUSTOMER_SERVICE: {
        "get_customer_order_context",
        "get_rent_notice_context",
        "get_bulk_discount_context",
    },
}


@dataclass
class AgentDeps:
    state: "TicketRunState"
    role: AgentRole
    depth: int
    parent_role: AgentRole | None


class TicketRunState:
    def __init__(
        self,
        team: "AgentTeam",
        mcp_server: MCPServerStdio,
        ticket_id: int,
        run_id: str,
    ) -> None:
        self.team = team
        self.mcp_server = mcp_server
        self.ticket_id = ticket_id
        self.run_id = run_id
        self.audit = team.audit
        self.steps = 0
        self._step_lock = asyncio.Lock()

    def _append_limit_event(
        self,
        *,
        role: AgentRole,
        task: str,
        depth: int,
        parent_role: AgentRole | None,
        reason: str,
    ) -> None:
        self.audit.append(
            {
                "event": "agent_step_blocked",
                "run_id": self.run_id,
                "ticket_id": self.ticket_id,
                "agent_role": role.value,
                "parent_role": parent_role.value if parent_role else None,
                "depth": depth,
                "task": task,
                "reason": reason,
            }
        )

    async def invoke(
        self,
        role: AgentRole,
        task: str,
        *,
        depth: int,
        parent_role: AgentRole | None,
    ) -> AgentWorkReport:
        if depth > MAX_DELEGATION_DEPTH:
            self._append_limit_event(
                role=role,
                task=task,
                depth=depth,
                parent_role=parent_role,
                reason=f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) reached.",
            )
            return AgentWorkReport(
                summary="This delegation was stopped by the configured depth limit.",
                unresolved_questions=["A human should review the remaining work."],
            )

        async with self._step_lock:
            if self.steps >= MAX_AGENT_STEPS:
                self._append_limit_event(
                    role=role,
                    task=task,
                    depth=depth,
                    parent_role=parent_role,
                    reason=f"Maximum agent steps ({MAX_AGENT_STEPS}) reached.",
                )
                return AgentWorkReport(
                    summary="This delegation was stopped by the configured step limit.",
                    unresolved_questions=["A human should review the remaining work."],
                )
            self.steps += 1
            step_number = self.steps

        started_at = datetime.now(timezone.utc)
        common_event = {
            "run_id": self.run_id,
            "step_number": step_number,
            "ticket_id": self.ticket_id,
            "agent_role": role.value,
            "parent_role": parent_role.value if parent_role else None,
            "depth": depth,
            "model": MODEL_NAME,
            "task": task,
        }
        self.audit.append({"event": "agent_step_started", **common_event})

        agent = self.team.agents[role]
        dependencies = AgentDeps(
            state=self,
            role=role,
            depth=depth,
            parent_role=parent_role,
        )
        try:
            result = await agent.run(
                task,
                deps=dependencies,
                toolsets=[
                    FilteredToolset(
                        self.mcp_server,
                        lambda _ctx, tool, allowed=ROLE_TOOLS[role]: tool.name in allowed,
                    )
                ],
                usage_limits=UsageLimits(
                    request_limit=(
                        MAX_BOSS_REQUESTS_PER_STEP
                        if role == AgentRole.BOSS
                        else MAX_REQUESTS_PER_STEP
                    ),
                    tool_calls_limit=MAX_TOOL_CALLS_PER_STEP,
                    input_tokens_limit=(
                        MAX_BOSS_INPUT_TOKENS_PER_STEP
                        if role == AgentRole.BOSS
                        else MAX_INPUT_TOKENS_PER_STEP
                    ),
                    output_tokens_limit=(
                        MAX_BOSS_OUTPUT_TOKENS_PER_STEP
                        if role == AgentRole.BOSS
                        else MAX_OUTPUT_TOKENS_PER_STEP
                    ),
                ),
            )
        except Exception as exc:
            failure_event = {
                "event": "agent_step_failed",
                **common_event,
                "started_at": started_at.isoformat(),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error_detail": "See backend logs; exception text is omitted to protect credentials.",
            }
            if type(exc).__name__ == "UsageLimitExceeded":
                failure_event["limit_detail"] = str(exc)[:500]
            self.audit.append(failure_event)
            raise

        finished_at = datetime.now(timezone.utc)
        usage = result.usage
        report = result.output
        self.audit.append(
            {
                "event": "agent_step_completed",
                **common_event,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_ms": round((finished_at - started_at).total_seconds() * 1000),
                "output": report,
                "messages": result.all_messages(),
                "usage": usage,
            }
        )
        return report


async def delegate_to_agent(
    ctx: RunContext[AgentDeps],
    target_role: AgentRole,
    task: str,
) -> str:
    """Ask any other team role to help with a ticket-specific subtask."""
    current_role = ctx.deps.role
    state = ctx.deps.state
    if target_role == current_role:
        state._append_limit_event(
            role=target_role,
            task=task,
            depth=ctx.deps.depth,
            parent_role=current_role,
            reason="An agent cannot delegate to itself.",
        )
        return "Delegation stopped: select a different team role."
    if len(task) > 2_000:
        state._append_limit_event(
            role=target_role,
            task=task[:2_000],
            depth=ctx.deps.depth + 1,
            parent_role=current_role,
            reason="Delegated task exceeded the 2,000-character limit.",
        )
        return "Delegation stopped: subtask exceeds the 2,000-character limit."

    report = await state.invoke(
        target_role,
        task,
        depth=ctx.deps.depth + 1,
        parent_role=current_role,
    )
    return json.dumps(report.model_dump(mode="json"), ensure_ascii=False)


class AgentTeam:
    def __init__(self, *, openai_client: AsyncOpenAI, audit: AuditTrail) -> None:
        self.openai_client = openai_client
        self.audit = audit
        provider = OpenAIProvider(openai_client=openai_client)
        self.model = OpenAIChatModel(MODEL_NAME, provider=provider)
        self.agents: dict[AgentRole, Agent[Any, AgentWorkReport]] = {}

        for role in AgentRole:
            prompt_path = PROMPTS_DIR / f"{role.value}.md"
            prompt = prompt_path.read_text(encoding="utf-8")
            agent = Agent(
                self.model,
                name=role.value,
                deps_type=AgentDeps,
                output_type=AgentWorkReport,
                instructions=prompt,
                model_settings={
                    "max_tokens": (
                        MAX_BOSS_OUTPUT_TOKENS_PER_STEP
                        if role == AgentRole.BOSS
                        else MAX_OUTPUT_TOKENS_PER_STEP
                    ),
                    # Portkey's gpt-6-luna Chat Completions route supports
                    # function tools when reasoning effort is explicitly off.
                    "openai_reasoning_effort": "none",
                },
            )
            agent.tool(delegate_to_agent)
            self.agents[role] = agent

    @classmethod
    def from_environment(cls) -> "AgentTeam":
        for env_path in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"):
            if env_path.is_file():
                load_dotenv(env_path, override=False)
        portkey_api_key = os.getenv("PORTKEY_API_KEY")
        if not portkey_api_key:
            raise RuntimeError("PORTKEY_API_KEY is missing from the project-root .env or environment.")

        openai_client = AsyncOpenAI(
            api_key=portkey_api_key,
            base_url=PORTKEY_BASE_URL,
            default_headers={"x-portkey-api-key": portkey_api_key},
        )
        return cls(openai_client=openai_client, audit=AuditTrail(AUDIT_PATH))

    async def run_ticket(self, ticket_id: int) -> TicketRunResult:
        if ticket_id <= 0:
            raise ValueError("ticket_id must be a positive integer.")

        run_id = str(uuid4())
        mcp_server = MCPServerStdio(
            command=sys.executable,
            args=[str(MCP_SERVER_SCRIPT)],
            cwd=str(PROJECT_ROOT),
        )
        state: TicketRunState | None = None
        async with mcp_server:
            state = TicketRunState(self, mcp_server, ticket_id, run_id)
            report = await state.invoke(
                AgentRole.BOSS,
                (
                    f"Review open ticket {ticket_id} using the MCP tools. Start by checking "
                    "the open-ticket board and shop date, delegate to the relevant specialists, "
                    "and return a fact-grounded report with any human approval requests or "
                    "message drafts. Do not make changes or contact anyone."
                ),
                depth=0,
                parent_role=None,
            )

        if report.approval_requests:
            status = "human_approval_required"
        elif report.unresolved_questions:
            status = "needs_human_review"
        else:
            status = "analysis_complete"
        return TicketRunResult(
            run_id=run_id,
            ticket_id=ticket_id,
            status=status,
            model=MODEL_NAME,
            agent_steps=state.steps if state else 0,
            report=report,
        )

    async def close(self) -> None:
        await self.openai_client.close()
