"""Entry point for the claude-dispatch CLI."""

import click

from claude_dispatch import __version__


@click.group()
@click.version_option(__version__, prog_name="claude-dispatch")
def main() -> None:
    """k9s-style TUI for orchestrating parallel Claude Code sessions."""


@main.command()
def start() -> None:
    """Start the Dispatcher TUI."""
    from claude_dispatch.dispatcher import DispatcherApp

    app = DispatcherApp()
    app.run()


@main.command()
def version() -> None:
    """Print version and exit."""
    click.echo(f"claude-dispatch {__version__}")
