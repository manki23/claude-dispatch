"""Cost guard — enforces per-agent and per-job cost limits."""

from __future__ import annotations


class CostLimitExceeded(RuntimeError):
    """Raised when an agent or job exceeds its configured cost limit."""


class CostGuard:
    """Checks cost limits on every token-usage update.

    Instantiate once per Job and inject via ``Job._make_on_cost()``.
    Limits of 0 are treated as disabled (no check performed).
    """

    def __init__(self, max_per_agent: float, max_per_job: float) -> None:
        self._max_per_agent = max_per_agent
        self._max_per_job = max_per_job

    @property
    def agent_limit_enabled(self) -> bool:
        return self._max_per_agent > 0

    @property
    def job_limit_enabled(self) -> bool:
        return self._max_per_job > 0

    def check(self, agent_cost: float, job_total: float, agent_id: str) -> None:
        """Raise ``CostLimitExceeded`` if either limit is breached.

        Args:
            agent_cost: Current cost of the triggering agent (USD).
            job_total:  Aggregated cost across all agents in the job (USD).
            agent_id:   Human-readable agent identifier for the error message.
        """
        if self.agent_limit_enabled and agent_cost > self._max_per_agent:
            raise CostLimitExceeded(
                f"Agent {agent_id} exceeded per-agent limit "
                f"(${agent_cost:.4f} > ${self._max_per_agent:.2f})"
            )
        if self.job_limit_enabled and job_total > self._max_per_job:
            raise CostLimitExceeded(
                f"Job cost exceeded per-job limit (${job_total:.4f} > ${self._max_per_job:.2f})"
            )
