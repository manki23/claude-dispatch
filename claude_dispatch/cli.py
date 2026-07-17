"""Entry point for the claude-dispatch CLI."""

import click

from claude_dispatch import __version__


@click.group()
@click.version_option(__version__, prog_name="claude-dispatch")
def main() -> None:
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""


@main.command()
@click.option("--mock", is_flag=True, default=False, help="Load mock jobs for UI development.")
def start(mock: bool) -> None:
    """Start the Dispatcher TUI."""
    from claude_dispatch.dispatcher import DispatcherApp

    jobs = []
    if mock:
        from claude_dispatch.mock import make_mock_jobs

        jobs = make_mock_jobs()

    app = DispatcherApp(jobs=jobs)
    app.run()


@main.command()
@click.argument("description")
def run(description: str) -> None:
    """Run a job headlessly — no TUI, logs streamed to stdout.

    DESCRIPTION is the task for the plan agent to decompose and execute.

    Exits with code 0 on success, 1 on failure.
    """
    import asyncio
    import sys

    from claude_dispatch.agent import Agent
    from claude_dispatch.config import load_config
    from claude_dispatch.job import Job, JobStatus

    config = load_config()
    # CLI headless run: in-process so logs stream live to stdout.
    job = Job(description=description, config=config, _use_workers=False)

    click.echo(f"[claude-dispatch] job {job.job_id} started: {description!r}")

    def _on_agent_ready(agent: Agent) -> None:
        """Attach a stdout log printer to every agent as soon as it is created."""
        agent_type = agent.spec.type.value

        def _log(line: str) -> None:
            click.echo(f"[{agent_type}] {line}")

        agent.on_log = _log

    job.on_agent_ready = _on_agent_ready

    try:
        asyncio.run(job.run())
    except Exception as exc:
        click.echo(f"[claude-dispatch] job {job.job_id} failed: {exc}", err=True)
        sys.exit(1)

    if job.status == JobStatus.DONE:
        click.echo(f"[claude-dispatch] job {job.job_id} done  cost=${job.cost_usd:.4f}")
    else:
        click.echo(
            f"[claude-dispatch] job {job.job_id} status={job.status.value}",
            err=True,
        )
        sys.exit(1)


@main.command()
def version() -> None:
    """Print version and exit."""
    click.echo(f"claude-dispatch {__version__}")
