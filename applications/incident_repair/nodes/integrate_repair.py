from __future__ import annotations

from applications.incident_repair.nodes.integrate import _integrate_pending_patches


async def integrate_repair_node(state: dict, runtime):
    return await _integrate_pending_patches(state, runtime)
