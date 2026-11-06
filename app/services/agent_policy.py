from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any


class AgentPolicyViolation(RuntimeError):
    """A runtime or model output crossed a declared safety boundary."""


@dataclass(frozen=True)
class AgentRunPolicy:
    """Explicit harness contract for one user turn.

    The policy is provider-agnostic: local Ollama, OpenAI-compatible APIs and
    the mock provider all run under the same input, output and budget rules.
    """

    max_input_chars: int = 12_000
    max_output_chars: int = 8_000
    max_steps: int = 32
    timeout_seconds: float = 45.0
    allowed_tools: frozenset[str] = frozenset({
        "llm.intent", "llm.risk", "llm.response", "rules.high_risk",
        "redis.memory", "mysql.messages", "rag.retrieve", "skills.read",
        "response.review", "report.enqueue", "llm.response_plan",
        "taskboard.write", "blackboard.accept",
    })


@dataclass
class AgentRunBudget:
    policy: AgentRunPolicy
    started_at: float = field(default_factory=monotonic)
    steps: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def validate_input(self, value: str) -> None:
        if len(value) > self.policy.max_input_chars:
            raise AgentPolicyViolation(f"输入超过单轮上限 {self.policy.max_input_chars} 字符")

    def step(self, agent: str, action: str, **metadata: Any) -> None:
        self.steps += 1
        elapsed = monotonic() - self.started_at
        if self.steps > self.policy.max_steps:
            raise AgentPolicyViolation(f"Agent step budget exhausted: {self.policy.max_steps}")
        if elapsed > self.policy.timeout_seconds:
            raise AgentPolicyViolation(f"Agent run timeout: {self.policy.timeout_seconds}s")
        self.events.append({
            "step": self.steps,
            "agent": agent,
            "action": action,
            "elapsedMs": round(elapsed * 1000, 2),
            **metadata,
        })

    def authorize_tool(self, agent: str, tool: str) -> None:
        if tool not in self.policy.allowed_tools:
            self.events.append({"agent": agent, "action": "tool.denied", "tool": tool})
            raise AgentPolicyViolation(f"{agent} 无权调用工具 {tool}")
        self.step(agent, "tool.authorized", tool=tool)

    def validate_output(self, text: str) -> str:
        if len(text) <= self.policy.max_output_chars:
            return text
        self.events.append({"action": "output.truncated", "originalChars": len(text)})
        return text[: self.policy.max_output_chars].rstrip() + "\n\n[输出已按运行时预算截断]"


def policy_from_settings(settings: Any) -> AgentRunPolicy:
    return AgentRunPolicy(
        max_input_chars=int(getattr(settings, "agent_max_input_chars", 12000)),
        max_output_chars=int(getattr(settings, "agent_max_output_chars", 8000)),
        max_steps=int(getattr(settings, "agent_max_steps", 32)),
        timeout_seconds=float(getattr(settings, "agent_timeout_seconds", 45.0)),
    )
