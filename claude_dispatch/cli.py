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
def version() -> None:
    """Print version and exit."""
    click.echo(f"claude-dispatch {__version__}")
