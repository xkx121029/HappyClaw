"""Harness stream → trajectory event projection."""

from happyclaw.infra.history.trajectory.projector import project_harness_chunk
from happyclaw.infra.history.trajectory.types import TrajectoryEvent, TrajectoryKind

__all__ = ["TrajectoryEvent", "TrajectoryKind", "project_harness_chunk"]
