# Lifecycle Hooks

claude-dispatch calls executable scripts in `~/.claude-dispatch/hooks/` at key events.

Hooks receive a JSON payload via stdin. They can be shell scripts, Python scripts,
or any executable — claude-dispatch just calls them and passes data.

## Available hooks

| Hook file | When it fires | Payload fields |
|---|---|---|
| `pre_session_start` | Before Dispatcher TUI opens | `version`, `timestamp` |
| `post_session_end` | After Dispatcher TUI closes | `total_cost`, `jobs_completed`, `timestamp` |
| `pre_job_create` | Before a Job is spawned | `job_id`, `description` |
| `post_job_complete` | After a Job finishes | `job_id`, `description`, `status`, `cost`, `duration_s` |
| `daily_standup` | On `:standup` command in Dispatcher | `timestamp`, `jobs_today` |

## Example: shell hook

```bash
#!/bin/bash
# ~/.claude-dispatch/hooks/post_job_complete
# Called after every Job finishes. Reads JSON from stdin.

set -euo pipefail

payload=$(cat)
job_id=$(echo "$payload" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
status=$(echo "$payload"  | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")

echo "Job $job_id finished with status: $status"
# Add your own logic here — update notes, send notifications, etc.
```

Make the hook executable:
```bash
chmod +x ~/.claude-dispatch/hooks/post_job_complete
```

## Security note

Hook scripts run with your user permissions. Never put credentials or tokens
directly in hook scripts — use environment variables or a secrets manager instead.
