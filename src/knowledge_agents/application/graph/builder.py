from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from knowledge_agents.application.agents.acquisition import run_acquisition_agent
from knowledge_agents.application.agents.curation import run_curation_agent
from knowledge_agents.application.agents.validation import run_validation_agent
from knowledge_agents.application.graph.nodes import (
    GraphDependencies,
    acquire_evidence,
    flush_telemetry,
    inspect_source,
    persist_terminal,
    prepare_run,
    retrieve_vault_context,
    route_review,
    sync_index,
    validate_acquisition,
    validate_drafts,
)
from knowledge_agents.application.graph.routing import GraphRoute
from knowledge_agents.application.graph.state import RunState

GRAPH_NODE_ORDER = (
    "prepare_run",
    "inspect_source",
    "acquire_evidence",
    "agent_1",
    "validate_acquisition",
    "retrieve_vault_context",
    "agent_2",
    "validate_drafts",
    "agent_3",
    "route_review",
    "persist_terminal",
    "sync_index",
    "flush_telemetry",
)

GRAPH_ROUTES = {
    GraphRoute.REVISE.value: "agent_2",
    GraphRoute.PERSIST.value: "persist_terminal",
}

NodeCallable = Callable[[RunState, GraphDependencies], Awaitable[dict[str, Any]]]


def build_graph(dependencies: GraphDependencies) -> StateGraph:
    acquisition = _agent_subgraph("acquire", run_acquisition_agent, dependencies)
    curation = _agent_subgraph("curate", run_curation_agent, dependencies)
    validation = _agent_subgraph("validate", run_validation_agent, dependencies)

    graph = StateGraph(RunState)
    graph.add_node("prepare_run", partial(prepare_run, dependencies=dependencies))
    graph.add_node("inspect_source", partial(inspect_source, dependencies=dependencies))
    graph.add_node("acquire_evidence", partial(acquire_evidence, dependencies=dependencies))
    graph.add_node("agent_1", acquisition)
    graph.add_node(
        "validate_acquisition",
        partial(validate_acquisition, dependencies=dependencies),
    )
    graph.add_node(
        "retrieve_vault_context",
        partial(retrieve_vault_context, dependencies=dependencies),
    )
    graph.add_node("agent_2", curation)
    graph.add_node("validate_drafts", partial(validate_drafts, dependencies=dependencies))
    graph.add_node("agent_3", validation)
    graph.add_node("route_review", partial(route_review, dependencies=dependencies))
    graph.add_node(
        "persist_terminal",
        partial(persist_terminal, dependencies=dependencies),
    )
    graph.add_node("sync_index", partial(sync_index, dependencies=dependencies))
    graph.add_node(
        "flush_telemetry",
        partial(flush_telemetry, dependencies=dependencies),
    )

    graph.add_edge(START, "prepare_run")
    graph.add_edge("prepare_run", "inspect_source")
    graph.add_edge("inspect_source", "acquire_evidence")
    graph.add_edge("acquire_evidence", "agent_1")
    graph.add_edge("agent_1", "validate_acquisition")
    graph.add_edge("validate_acquisition", "retrieve_vault_context")
    graph.add_edge("retrieve_vault_context", "agent_2")
    graph.add_edge("agent_2", "validate_drafts")
    graph.add_edge("validate_drafts", "agent_3")
    graph.add_edge("agent_3", "route_review")
    graph.add_conditional_edges("route_review", _selected_route, GRAPH_ROUTES)
    graph.add_edge("persist_terminal", "sync_index")
    graph.add_edge("sync_index", "flush_telemetry")
    graph.add_edge("flush_telemetry", END)
    return graph


@asynccontextmanager
async def open_graph(
    checkpoint_path: Path,
    dependencies: GraphDependencies,
    *,
    interrupt_after: Sequence[str] = (),
) -> AsyncIterator[Any]:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(checkpoint_path)
    await connection.execute("PRAGMA journal_mode = WAL")
    await connection.execute("PRAGMA busy_timeout = 5000")
    await connection.commit()
    serializer = JsonPlusSerializer(allowed_msgpack_modules=None)
    checkpointer = AsyncSqliteSaver(connection, serde=serializer)
    await checkpointer.setup()
    compiled = build_graph(dependencies).compile(
        checkpointer=checkpointer,
        interrupt_after=list(interrupt_after) or None,
    )
    try:
        yield compiled
    finally:
        await connection.close()


def graph_manifest() -> dict[str, object]:
    return {
        "nodes": GRAPH_NODE_ORDER,
        "conditional_routes": GRAPH_ROUTES,
        "subgraphs": ("agent_1", "agent_2", "agent_3"),
        "checkpoint_mode": "async_sqlite_parent_per_invocation_subgraphs",
    }


def _agent_subgraph(
    name: str,
    node: NodeCallable,
    dependencies: GraphDependencies,
) -> Any:
    graph = StateGraph(RunState)
    graph.add_node(name, partial(node, dependencies=dependencies))
    graph.add_edge(START, name)
    graph.add_edge(name, END)
    return graph.compile(checkpointer=None)


def _selected_route(state: RunState) -> str:
    return state["route"]
