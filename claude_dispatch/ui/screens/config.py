"""ConfigScreen — in-app config editor (Issue #44)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, RichLog, TextArea

from claude_dispatch import hooks as hooks_mod
from claude_dispatch.config import CONFIG_FILE, HOOKS_DIR, Config
from claude_dispatch.ui.widgets.dispatch_header import DispatchHeader, key_hint

_KEY_HINTS = (
    f"  {key_hint('esc')}  Back          {key_hint('tab')}  Switch view\n"
    f"  {key_hint('e')}  Edit           {key_hint('ctrl+s')}  Save\n"
    f"  {key_hint('t')}  Test hook      {key_hint('x')}  chmod +x\n"
    f"  {key_hint('ctrl+j')}  Jarvis test    {key_hint('d')}  Chat"
)

_KNOWN_HOOKS = [
    hooks_mod.PRE_JOB_START,
    hooks_mod.POST_AGENT_DONE,
    hooks_mod.POST_JOB_DONE,
    hooks_mod.POST_JOB_FAILED,
]

_HOOK_TEMPLATE = """\
#!/usr/bin/env bash
# Hook: {name}
# Receives JSON payload on stdin.
# exit 0 = success, non-zero = warning (never blocks job).
read payload
echo "Hook {name} fired: $payload" >&2
"""


class ConfigScreen(Screen[None]):
    """In-app config editor: config YAML / hooks / jarvis views."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("tab", "next_view", "Switch", show=True),
        Binding("e", "toggle_edit", "Edit", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
        Binding("t", "test_hook", "Test hook", show=True),
        Binding("ctrl+j", "test_jarvis", "Jarvis test", show=True),
        Binding("x", "toggle_executable", "chmod +x", show=True),
        Binding("d", "dispatcher", "Chat", show=True),
        Binding("1", "goto_root", "Dispatcher", show=False),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._view: str = "config"  # "config" | "hooks" | "jarvis"
        self._edit_mode: bool = False
        self._editing_hook: str | None = None
        self._jarvis_vault_path: str = config.jarvis.vault_path

    # ── compose ────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield DispatchHeader(_KEY_HINTS)
        yield Label("", id="breadcrumb")
        yield Label("", id="config-status")

        with Vertical(id="view-config"):
            yield TextArea(id="yaml-editor", language="yaml", read_only=True)

        with Vertical(id="view-hooks"):
            yield DataTable(id="hooks-table", cursor_type="row")
            yield TextArea(id="hook-editor", read_only=True)
            yield Label("", id="hook-test-output")

        with Vertical(id="view-jarvis"):
            yield Label("", id="jarvis-info")
            yield RichLog(id="jarvis-preview", wrap=True)

        yield Footer()

    # ── on_mount ───────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.query_one("#breadcrumb", Label).update("[dim]DISPATCHER[/dim]  ›  [bold]config[/bold]")

        # Hide non-active views
        self.query_one("#view-hooks", Vertical).display = False
        self.query_one("#view-jarvis", Vertical).display = False
        self.query_one("#hook-editor", TextArea).display = False

        # Load config YAML
        yaml_editor = self.query_one("#yaml-editor", TextArea)
        if CONFIG_FILE.exists():
            yaml_editor.load_text(CONFIG_FILE.read_text())
        else:
            yaml_editor.load_text("")

        # Populate hooks table
        table = self.query_one("#hooks-table", DataTable)
        table.add_columns("name", "exists", "exec", "enabled")
        self._populate_hooks_table()

        # Jarvis info
        self._refresh_jarvis_info()

        # Status
        self._refresh_status()

    # ── internal helpers ───────────────────────────────────────────

    def _populate_hooks_table(self) -> None:
        table = self.query_one("#hooks-table", DataTable)
        table.clear()
        for name in _KNOWN_HOOKS:
            hook_path = HOOKS_DIR / name
            exists = hook_path.exists()
            if exists:
                mode = hook_path.stat().st_mode
                exec_flag = "[green]✓[/green]" if mode & 0o111 else "[red]✗[/red]"
            else:
                exec_flag = "[dim]—[/dim]"
            enabled = "[green]✓[/green]" if self._config.hooks.enabled else "[dim]—[/dim]"
            table.add_row(
                name,
                "[green]✓[/green]" if exists else "[dim]—[/dim]",
                exec_flag,
                enabled,
                key=name,
            )

    def _refresh_jarvis_info(self) -> None:
        cfg = self._config.jarvis
        vault_path = self._jarvis_vault_path or cfg.vault_path or "[dim](not set)[/dim]"
        enabled = "[green]enabled[/green]" if cfg.enabled else "[dim red]disabled[/dim red]"
        self.query_one("#jarvis-info", Label).update(
            f"[dim]enabled:[/dim] {enabled}  [dim]vault_path:[/dim] {vault_path}"
        )

    def _refresh_status(self) -> None:
        if self._view == "config":
            mode = "[green]editing[/green]" if self._edit_mode else "read-only"
            self.query_one("#config-status", Label).update(
                f"[dim]view:[/dim] config  [dim]mode:[/dim] {mode}"
            )
        elif self._view == "hooks":
            hook_name = self._editing_hook or "[dim]none[/dim]"
            self.query_one("#config-status", Label).update(
                f"[dim]view:[/dim] hooks  [dim]hook:[/dim] {hook_name}"
            )
        elif self._view == "jarvis":
            self.query_one("#config-status", Label).update("[dim]view:[/dim] jarvis")

    def _set_view(self, view: str) -> None:
        self._view = view
        self._edit_mode = False
        self._editing_hook = None

        self.query_one("#view-config", Vertical).display = view == "config"
        self.query_one("#view-hooks", Vertical).display = view == "hooks"
        self.query_one("#view-jarvis", Vertical).display = view == "jarvis"

        # Reset hook editor visibility when switching away
        if view != "hooks":
            self.query_one("#hook-editor", TextArea).display = False

        self._refresh_status()

    def _selected_hook_name(self) -> str | None:
        table = self.query_one("#hooks-table", DataTable)
        row = table.cursor_row
        if row < len(_KNOWN_HOOKS):
            return _KNOWN_HOOKS[row]
        return None

    # ── actions ────────────────────────────────────────────────────

    def action_dispatcher(self) -> None:
        self.app.open_dispatcher_conversation()  # type: ignore[attr-defined]

    def action_goto_root(self) -> None:
        self.app.pop_to_main()  # type: ignore[attr-defined]

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_next_view(self) -> None:
        order = ["config", "hooks", "jarvis"]
        idx = order.index(self._view)
        self._set_view(order[(idx + 1) % len(order)])

    def action_toggle_edit(self) -> None:
        if self._view == "config":
            self._edit_mode = not self._edit_mode
            self.query_one("#yaml-editor", TextArea).read_only = not self._edit_mode
            self._refresh_status()

        elif self._view == "hooks":
            name = self._selected_hook_name()
            if not name:
                return
            hook_path = HOOKS_DIR / name
            if hook_path.exists():
                content = hook_path.read_text()
            else:
                content = _HOOK_TEMPLATE.format(name=name)
            editor = self.query_one("#hook-editor", TextArea)
            editor.load_text(content)
            editor.read_only = False
            editor.display = True
            self._editing_hook = name
            self._refresh_status()

        elif self._view == "jarvis":
            from claude_dispatch.ui.modals.prompt import PromptModal

            current = self._jarvis_vault_path or self._config.jarvis.vault_path

            def on_dismiss(value: str | None) -> None:
                if value:
                    self._jarvis_vault_path = value
                    self._refresh_jarvis_info()

            self.app.push_screen(
                PromptModal(
                    label="vault_path >",
                    placeholder=current or "e.g. ~/Jarvis",
                ),
                callback=on_dismiss,
            )

    def action_save(self) -> None:
        if self._view == "config":
            yaml_text = self.query_one("#yaml-editor", TextArea).text
            try:
                raw: dict[str, Any] = yaml.safe_load(yaml_text) or {}
                new_config = Config(**raw)
            except (yaml.YAMLError, ValidationError) as exc:
                self.query_one("#config-status", Label).update(f"[red]Error: {exc}[/red]")
                return
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(yaml_text)
            self._config = new_config
            self.app.config = new_config  # type: ignore[attr-defined]
            self._edit_mode = False
            self.query_one("#yaml-editor", TextArea).read_only = True
            self._refresh_status()
            self.notify("Config saved")

        elif self._view == "hooks" and self._editing_hook:
            content = self.query_one("#hook-editor", TextArea).text
            HOOKS_DIR.mkdir(parents=True, exist_ok=True)
            hook_path = HOOKS_DIR / self._editing_hook
            hook_path.write_text(content)
            current_mode = hook_path.stat().st_mode
            hook_path.chmod(current_mode | 0o111)
            self._populate_hooks_table()
            self._refresh_status()
            self.notify(f"Hook saved + chmod +x: {self._editing_hook}")

        elif self._view == "jarvis":
            if not CONFIG_FILE.exists():
                self.notify("No config file to update", severity="warning")
                return
            try:
                raw = yaml.safe_load(CONFIG_FILE.read_text()) or {}
            except yaml.YAMLError as exc:
                self.notify(f"YAML parse error: {exc}", severity="error")
                return
            if "jarvis" not in raw:
                raw["jarvis"] = {}
            raw["jarvis"]["vault_path"] = self._jarvis_vault_path
            updated_config = Config(**raw)
            CONFIG_FILE.write_text(yaml.dump(raw, default_flow_style=False))
            self._config = updated_config
            self.app.config = updated_config  # type: ignore[attr-defined]
            self._refresh_jarvis_info()
            self.notify("Jarvis config saved")

    def action_test_hook(self) -> None:
        if self._view != "hooks":
            return
        name = self._selected_hook_name()
        if not name:
            return

        if name == hooks_mod.PRE_JOB_START:
            payload = hooks_mod.pre_job_start_payload("mock-job", "Test hook")
        elif name == hooks_mod.POST_AGENT_DONE:
            payload = hooks_mod.post_agent_done_payload(
                "mock-job", "code", "done", None, 0.001, "Test hook"
            )
        else:
            status = "failed" if name == hooks_mod.POST_JOB_FAILED else "done"
            payload = hooks_mod.post_job_done_payload("mock-job", "Test hook", status, 0.001, [])

        output_label = self.query_one("#hook-test-output", Label)
        output_label.update(f"[dim]Running {name}…[/dim]")

        hooks_dir = Path(self._config.hooks.directory).expanduser()

        async def _run() -> None:
            try:
                await hooks_mod.fire(
                    name,
                    payload,
                    hooks_dir=hooks_dir,
                    enabled=True,
                )
                output_label.update(f"[green]✓ {name} completed[/green]")
                self.notify(f"Hook {name} OK")
            except Exception as exc:
                output_label.update(f"[red]✗ {name}: {exc}[/red]")
                self.notify(f"Hook {name} failed: {exc}", severity="error")

        self.app.run_worker(_run(), exclusive=False)

    def action_toggle_executable(self) -> None:
        if self._view != "hooks":
            return
        name = self._selected_hook_name()
        if not name:
            return
        hook_path = HOOKS_DIR / name
        if not hook_path.exists():
            self.notify(f"Hook {name} does not exist — use <e> to create it", severity="warning")
            return
        current_mode = hook_path.stat().st_mode
        if current_mode & 0o111:
            hook_path.chmod(current_mode & ~0o111)
            self.notify(f"Removed exec bit: {name}")
        else:
            hook_path.chmod(current_mode | 0o111)
            self.notify(f"Added exec bit: {name}")
        self._populate_hooks_table()

    def action_test_jarvis(self) -> None:
        if self._view != "jarvis":
            return
        from claude_dispatch.ui.modals.prompt import PromptModal

        def on_dismiss(description: str | None) -> None:
            if not description:
                return
            vault_path_str = self._jarvis_vault_path or self._config.jarvis.vault_path
            if not vault_path_str:
                self.notify("vault_path not set — use <e> to configure", severity="warning")
                return
            vault_path = Path(vault_path_str).expanduser()
            from claude_dispatch.jarvis import fetch_prior_context

            try:
                result = fetch_prior_context(description, vault_path)
            except Exception as exc:
                self.notify(f"Jarvis search failed: {exc}", severity="error")
                return
            preview = self.query_one("#jarvis-preview", RichLog)
            preview.clear()
            preview.write(result or "No matches found.")

        self.app.push_screen(
            PromptModal(
                label="description >",
                placeholder="e.g. Fix MOPU-668",
            ),
            callback=on_dismiss,
        )
