"""ConversationScreen — tracked chat view for a single agent session."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, RichLog

from claude_dispatch.agent import Agent, ConversationThread, Turn
from claude_dispatch.job import Job


class ConversationScreen(Screen):
    """Chat-style screen for back-and-forth with one agent.

    - Shows only user/assistant turns (no tool noise) in the log.
    - A slim status bar above the input shows live tool activity while
      the agent is thinking (e.g. "[tool] Read(...)").
    - Enter sends a message; Esc pops back; reopening reuses the thread.

    Optional ``system_prompt_factory``: if provided, called before each send
    to produce a fresh system prompt (dispatcher agent — sees current job state).
    When None, routing goes through ``job.send_message``.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("end", "scroll_end", "Scroll to end", show=True),
    ]

    def __init__(
        self,
        job: Job,
        agent: Agent,
        system_prompt_factory: Callable[[], str] | None = None,
    ) -> None:
        super().__init__()
        self._system_prompt_factory = system_prompt_factory
        self._job = job
        self._agent = agent
        self._thread: ConversationThread = agent.get_or_create_conversation()
        self._prev_on_reply: Callable[[Turn], None] | None = self._thread.on_reply
        self._prev_on_agent_log: Callable[[str], None] | None = None
        self._awaiting_reply: bool = False

    def compose(self) -> ComposeResult:
        agent_type = self._agent.spec.type.value
        job_desc = self._job.description

        with Vertical():
            yield Label(
                f"[bold]{job_desc}[/bold] › [cyan]{agent_type}[/cyan]  "
                f"[dim]turns:[/dim] {len(self._thread.turns)}",
                id="conv-header",
            )
            yield RichLog(id="conv-log", highlight=False, markup=True, wrap=True)
            yield Label("", id="conv-activity")
            yield Input(placeholder="type a message… (Enter to send)", id="conv-input")
        yield Footer()

    DEFAULT_CSS = """
    #conv-activity {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        log = self.query_one("#conv-log", RichLog)

        # Render existing turns.
        for turn in self._thread.turns:
            log.write(_format_turn(turn))

        # Wire reply callback — clears activity bar and appends the turn.
        def _live_reply(turn: Turn) -> None:
            if self._prev_on_reply:
                self._prev_on_reply(turn)
            self._awaiting_reply = False
            self._set_activity("")
            self._append_turn(turn)

        self._thread.on_reply = _live_reply

        # Wire agent log callback — shows tool activity in the status bar.
        self._prev_on_agent_log = self._agent.on_log

        def _activity_log(line: str) -> None:
            if self._prev_on_agent_log:
                self._prev_on_agent_log(line)
            if self._awaiting_reply:
                self._set_activity(f"· {line}")

        self._agent.on_log = _activity_log

        # Focus input immediately.
        self.query_one("#conv-input", Input).focus()

    def on_unmount(self) -> None:
        self._thread.on_reply = self._prev_on_reply
        self._agent.on_log = self._prev_on_agent_log

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        event.input.value = ""

        self._awaiting_reply = True
        self._set_activity("· thinking…")

        # Show the user turn immediately (don't wait for _run_turn to echo it).
        user_turn = Turn(role="user", text=message)
        self._append_turn(user_turn)

        if self._system_prompt_factory is not None:
            # Dispatcher mode: run the agent directly with a fresh system prompt.
            system_prompt = self._system_prompt_factory()
            resume_id = self._agent.session_id
            self.app.run_worker(
                self._agent.run(
                    message, resume_session_id=resume_id, system_prompt=system_prompt
                ),
                exclusive=False,
            )
        else:
            # Normal mode: deliver via Job routing (handles RUNNING queue or DONE resume).
            delivered = await self._job.send_message(
                message, agent_type=self._agent.spec.type.value
            )
            if not delivered:
                self._awaiting_reply = False
                self._set_activity("")
                self.notify(
                    f"Could not deliver message to '{self._agent.spec.type.value}'",
                    severity="warning",
                )

    # ── internal helpers ───────────────────────────────────────────

    def _append_turn(self, turn: Turn) -> None:
        log = self.query_one("#conv-log", RichLog)
        at_bottom = log.scroll_y >= log.virtual_size.height - log.size.height - 1
        log.write(_format_turn(turn))
        if at_bottom:
            log.scroll_end(animate=False)

    def _set_activity(self, text: str) -> None:
        """Update the slim activity bar above the input."""
        self.query_one("#conv-activity", Label).update(text)

    # ── actions ────────────────────────────────────────────────────

    def action_dispatcher(self) -> None:
        """Open dispatcher from any conversation (unless already in dispatcher)."""
        if self._agent.spec.type.value != "dispatcher":
            self.app.open_dispatcher_conversation()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_scroll_end(self) -> None:
        self.query_one("#conv-log", RichLog).scroll_end(animate=False)


def _format_turn(turn: Turn) -> str:
    if turn.role == "user":
        return f"[bold cyan]you >[/bold cyan] {turn.text}"
    return f"[bold green]agent >[/bold green] {turn.text}"
