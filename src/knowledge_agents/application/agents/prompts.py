from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.hashing import canonical_json

PROMPT_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    agent: AgentRole
    name: str
    version: str
    instructions: str

    def messages(self, payload: Any) -> tuple[dict[str, Any], ...]:
        untrusted = canonical_json(payload)
        return (
            {"role": "developer", "content": self.instructions},
            {
                "role": "user",
                "content": f"<UNTRUSTED_DATA>\n{untrusted}\n</UNTRUSTED_DATA>",
            },
        )


def load_prompt(agent: AgentRole, *, revision: bool = False) -> PromptSpec:
    name = {
        AgentRole.ACQUISITION: "agent_1",
        AgentRole.CURATION: "agent_2_revision" if revision else "agent_2",
        AgentRole.VALIDATION: "agent_3",
    }[agent]
    resource = files("knowledge_agents.prompts").joinpath(name, f"{PROMPT_VERSION}.md")
    instructions = resource.read_text(encoding="utf-8").strip()
    return PromptSpec(agent=agent, name=name, version=PROMPT_VERSION, instructions=instructions)
