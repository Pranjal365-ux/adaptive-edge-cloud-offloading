"""Shared job dispatcher used by both local edge and cloud worker processes."""

from __future__ import annotations

from offloader.inspection import inspect_surface


def execute(payload: dict) -> dict:
    """Run the job-specific inspection identically on edge and cloud workers."""
    if payload.get("task_type") != "surface_defect_inspection":
        raise ValueError("task_type must be surface_defect_inspection")
    return {"task_type": "surface_defect_inspection", **inspect_surface(payload)}
