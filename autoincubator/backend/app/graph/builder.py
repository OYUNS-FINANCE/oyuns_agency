"""Builds the graph: scout → analyst → skeptic → rank ⟲ → checkpoint → Phase 2.

Phase 2 fans out to the Product Architect, GTM Strategist and Financial Modeler in
parallel, then fans in to the Editor.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst.node import analyst_node
from app.agents.editor.node import editor_node
from app.agents.financial_modeler.node import financial_modeler_node
from app.agents.gtm_strategist.node import gtm_strategist_node
from app.agents.product_architect.node import product_architect_node
from app.agents.scout.node import scout_node
from app.agents.skeptic.node import skeptic_node
from app.core.telemetry import traced_node
from app.graph.checkpoint import checkpoint_node
from app.graph.deps import GraphDeps
from app.graph.ranking import rank_node
from app.graph.routing import route_after_rank
from app.graph.state import Phase1State

PHASE2_PARALLEL = ("product_architect", "gtm_strategist", "financial_modeler")
PHASE2_EDITOR = "editor"

type IncubatorGraph = CompiledStateGraph[Phase1State, GraphDeps, Phase1State, Phase1State]


def build_graph() -> StateGraph[Phase1State, GraphDeps, Phase1State, Phase1State]:
    g = StateGraph(Phase1State, context_schema=GraphDeps)
    g.add_node("scout", traced_node("scout", scout_node))
    g.add_node("analyst", traced_node("analyst", analyst_node))
    g.add_node("skeptic", traced_node("skeptic", skeptic_node))
    g.add_node("rank", traced_node("rank", rank_node))
    g.add_node("checkpoint", checkpoint_node)  # sync, no runtime: not wrapped
    g.add_node("product_architect", traced_node("product_architect", product_architect_node))
    g.add_node("gtm_strategist", traced_node("gtm_strategist", gtm_strategist_node))
    g.add_node("financial_modeler", traced_node("financial_modeler", financial_modeler_node))
    g.add_node(PHASE2_EDITOR, traced_node(PHASE2_EDITOR, editor_node))

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
