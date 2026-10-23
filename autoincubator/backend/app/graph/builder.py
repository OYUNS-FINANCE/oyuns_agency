"""Builds the Phase-1 graph: scout → analyst → skeptic → rank ⟲ → checkpoint → Phase-2 stubs."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst.node import analyst_node
from app.agents.scout.node import scout_node
from app.agents.skeptic.node import skeptic_node
from app.graph.checkpoint import checkpoint_node
from app.graph.deps import GraphDeps
from app.graph.ranking import rank_node
from app.graph.routing import route_after_rank
from app.graph.state import Phase1State
from app.graph.stubs import PHASE2_EDITOR, PHASE2_PARALLEL, Phase2Stub

type IncubatorGraph = CompiledStateGraph[Phase1State, GraphDeps, Phase1State, Phase1State]


def build_graph() -> StateGraph[Phase1State, GraphDeps, Phase1State, Phase1State]:
    g = StateGraph(Phase1State, context_schema=GraphDeps)
    g.add_node("scout", scout_node)
    g.add_node("analyst", analyst_node)
    g.add_node("skeptic", skeptic_node)
    g.add_node("rank", rank_node)
    g.add_node("checkpoint", checkpoint_node)
    for name in (*PHASE2_PARALLEL, PHASE2_EDITOR):
        g.add_node(name, Phase2Stub(name))

    g.add_edge(START, "scout")
    g.add_edge("scout", "analyst")
    g.add_edge("analyst", "skeptic")
    g.add_edge("skeptic", "rank")
    g.add_conditional_edges("rank", route_after_rank, ["scout", "checkpoint"])
    for name in PHASE2_PARALLEL:
        g.add_edge("checkpoint", name)
    g.add_edge(list(PHASE2_PARALLEL), PHASE2_EDITOR)
    g.add_edge(PHASE2_EDITOR, END)
    return g


def compile_graph(checkpointer: BaseCheckpointSaver[str]) -> IncubatorGraph:
    return build_graph().compile(checkpointer=checkpointer)
