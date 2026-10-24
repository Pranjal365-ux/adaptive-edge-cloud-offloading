"""Backward-compatible command-line entry point for the OffloadOps simulator."""

from offloader.simulator import (
    POLICIES,
    SCENARIOS,
    Resource,
    Scenario,
    Simulation,
    Task,
    generate_tasks,
    main,
    percentile,
    tune_threshold,
    write_csv,
)

__all__ = [
    "POLICIES",
    "SCENARIOS",
    "Resource",
    "Scenario",
    "Simulation",
    "Task",
    "generate_tasks",
    "percentile",
    "tune_threshold",
    "write_csv",
    "main",
]

if __name__ == "__main__":
    main()
