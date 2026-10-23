"""Phase-2 nodes as no-op stubs. Phase 5 replaces them with the real agents."""

from __future__ import annotations

from app.graph.state import Phase1State

PHASE2_PARALLEL = ("product_architect", "gtm_strategist", "financial_modeler")
PHASE2_EDITOR = "editor"
STUB_STATUS = "stub"


class Phase2Stub:
    """Records that the node ran; produces no plan content."""

    def __init__(self, name: str):
        self.name = name

    def __call__(self, state: Phase1State) -> Phase1State:
        return {"phase2": {self.name: STUB_STATUS}}
