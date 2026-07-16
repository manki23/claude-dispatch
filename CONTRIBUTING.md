# Contributing to claude-dispatch

Thank you for your interest in contributing!

## Getting started

```bash
git clone https://github.com/manki23/claude-dispatch.git
cd claude-dispatch
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Development workflow

1. Open an [Issue](https://github.com/manki23/claude-dispatch/issues) to discuss the change
2. Fork the repo and create a branch: `git checkout -b feat/your-feature`
3. Make your changes, add tests
4. Run checks: `ruff check . && ruff format . && pytest`
5. Open a PR against `main`

## Code style

- Formatter: `ruff format`
- Linter: `ruff check`
- Type checker: `mypy claude_dispatch/`
- Line length: 100

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat: add resume command`
- `fix: handle missing config file gracefully`
- `docs: update configuration reference`
- `chore: bump textual to 0.61`

## Security

**Never include in PRs:**
- API keys, tokens, credentials of any kind
- Personal file paths (use `~` or placeholders)
- Personal usernames or org names in code (config only)
- Any real configuration from `~/.claude-dispatch/`

If you discover a security issue, please open a private [Security Advisory](https://github.com/manki23/claude-dispatch/security/advisories/new) instead of a public issue.

## Pull request checklist

- [ ] Tests added or updated
- [ ] `ruff` passes with no errors
- [ ] No credentials, tokens, or personal data in the diff
- [ ] CHANGELOG.md updated under `[Unreleased]`
