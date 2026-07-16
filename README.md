# claude-dispatch

> k9s-style TUI for orchestrating parallel Claude Code sessions.

Run multiple Claude agents in parallel — one per task — while staying in full control from a single terminal interface. Switch between sessions, track costs, inject context, and resume past work without losing history.

---

## What it solves

Running multiple Claude Code sessions today is painful:
- Manually juggling terminal tabs → no coordination, no shared context
- Context compaction kills history in long sessions
- Knowledge from one session never reaches another
- Scribe work (notes, docs, tickets) is scattered across sessions

claude-dispatch gives each task its own focused agent hierarchy, routes context between them, and lets you navigate everything from one place.

---

## Architecture

```
Dispatcher  (you — control plane, k9s-style TUI)
│
├── Job: TICKET-123          (1 per task: Jira ticket, doc writing, investigation...)
│     ├── plan  agent        sonnet — reads context, produces execution plan
│     ├── code  agent        haiku  — executes code changes in isolated worktree
│     ├── jira  agent        haiku  — updates ticket, posts PR comments
│     └── test  agent        haiku  — runs tests, staging calls, CI checks
│
└── Job: write-confluence-doc
      ├── plan    agent      sonnet — plans research + writing steps
      ├── ingest  agent ×N   haiku  — parallel ingestion (Confluence, GDocs, metrics)
      └── draft   agent      sonnet — aggregates into final document
```

- **Dispatcher** = control plane. Navigate jobs and agents with keyboard shortcuts. Send messages to jobs. Check costs.
- **Job** = one human task. Self-organizing: the `plan` agent decides what agents and worktrees are needed.
- **Agent** = scoped Claude session. Runs with `bypassPermissions`, locked to its `cwd` and `allowedTools`.

---

## Security model

Each agent runs inside a hard boundary:

| Layer | Mechanism | Effect |
|---|---|---|
| `cwd` lock | SDK working directory | Agent cannot touch files outside its assigned directory |
| `allowedTools` | Per-agent whitelist | Code agent cannot call Slack MCP; Jira agent cannot run Bash |
| `bypassPermissions` | No confirmation prompts | Removes friction within the boundary |

This is more restrictive than default Claude Code (which has full filesystem access).

---

## TUI overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ claude-dispatch                          Jobs: 3 | Cost: $0.14 | ●  │
├─────────────────────────────────────────────────────────────────────┤
│  NAME              STATUS    PHASE      AGENTS   COST    AGE        │
│  TICKET-123      ● running   execute    4/4      $0.09   23m        │
│▶ write-doc       ● running   plan       1/1      $0.03   4m         │
│  TICKET-456      ✓ done      —          0/3      $0.02   2h         │
├─────────────────────────────────────────────────────────────────────┤
│ [n] new   [enter] drill in   [m] message job   [k] kill   [?] help  │
└─────────────────────────────────────────────────────────────────────┘
```

| Key | Action |
|---|---|
| `↑↓` | Navigate list |
| `Enter` | Drill into Job or Agent |
| `Esc` | Go back one level |
| `n` | New Job (opens prompt bar) |
| `m` | Message selected Job |
| `k` | Kill selected Job or Agent |
| `r` | Resume Job from history |
| `c` | Cost breakdown |
| `?` | Help / keybindings |

---

## Installation

```bash
pip install claude-dispatch
```

Requires:
- Python 3.10+
- Claude Code installed (`npm install -g @anthropic-ai/claude-code`)
- `ANTHROPIC_API_KEY` set in your environment

---

## Configuration

Create `~/.claude-dispatch/config.yaml`:

```yaml
# See examples/config.yaml for full reference

repos:
  my-repo: ~/code/my-repo
  my-other-repo: ~/code/my-other-repo

worktree_pattern: "{repo}-{job_id}"
branch_pattern: "{username}/{job_id}/{slug}"

defaults:
  plan_model: claude-sonnet-4-6
  execute_model: claude-haiku-4-5-20251001
  username: your-github-username

claude:
  mcp_config: ~/.claude.json  # inherits your existing Claude Code MCP setup
```

This file lives at `~/.claude-dispatch/config.yaml` — **never commit it** (it contains personal paths and usernames).

---

## Lifecycle hooks

claude-dispatch fires hooks at key events. Place executable scripts in `~/.claude-dispatch/hooks/`:

```
~/.claude-dispatch/hooks/
├── post_session_end      # runs when Dispatcher closes
├── post_job_complete     # runs when a Job finishes
└── daily_standup         # runs on :standup command
```

Hooks receive event data as JSON via stdin. See [`examples/hooks/`](examples/hooks/) for reference implementations.

This lets you connect claude-dispatch to your own tooling (notes, wikis, notification systems) without any private configuration in this repository.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
