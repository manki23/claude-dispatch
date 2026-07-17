# Configuration Reference

Full reference for `~/.claude-dispatch/config.yaml`.

## repos

Map short names to absolute paths of repos on your machine.
Used by the plan agent when deciding which worktrees to create.

```yaml
repos:
  my-repo: ~/code/my-repo
  my-other-repo: ~/code/my-other-repo
```

## worktree_pattern

Pattern for auto-created git worktree directories.

Variables: `{repo}`, `{job_id}`, `{username}`

```yaml
worktree_pattern: "{repo}-{job_id}"
# e.g. my-repo-TICKET-123
```

## branch_pattern

Pattern for auto-created git branches inside worktrees.

Variables: `{repo}`, `{job_id}`, `{slug}`, `{username}`

```yaml
branch_pattern: "{username}/{job_id}/{slug}"
# e.g. alice/TICKET-123/fix-auth
```

## defaults

```yaml
defaults:
  plan_model: claude-sonnet-4-6          # model for plan agents
  execute_model: claude-haiku-4-5-20251001  # model for execution agents
  username: your-github-username
  max_parallel_agents: 5
```

## claude

```yaml
claude:
  mcp_config: ~/.claude.json
  # Path to your Claude Code config.
  # All MCP servers configured there are inherited by all agents.
```

## limits

Optional hard cost limits. Agents or jobs exceeding these are killed automatically.

```yaml
limits:
  max_cost_per_agent: 1.00    # USD
  max_cost_per_job: 5.00      # USD
  warn_cost_dispatcher: 10.00 # USD — shows warning in TUI
```

## hooks

```yaml
hooks:
  enabled: true
  directory: ~/.claude-dispatch/hooks
```

See [examples/hooks/](../examples/hooks/README.md) for hook documentation.

## jarvis

Inject prior context from a [Jarvis](https://github.com/manki23/Jarvis) Obsidian vault
into the plan agent's prompt before it starts planning.

When a job description contains Jira-style ticket IDs (e.g. `MOPU-668`), dispatch
searches the vault for matching note files (`**/{TICKET_ID}*.md`) and prepends a
`## Prior context` block to the plan prompt. This prevents the plan agent from
re-planning or duplicating work that is already in progress or done.

```yaml
jarvis:
  enabled: true           # set false to disable entirely
  vault_path: ~/Jarvis    # path to your Obsidian vault root
```

Notes are truncated at 2000 characters. Missing vault or no matching notes → silently
skipped (never causes a job failure).
