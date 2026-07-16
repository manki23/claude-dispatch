# Changelog

All notable changes to claude-dispatch will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Initial project skeleton
- Dispatcher / Job / Agent architecture
- Textual TUI with Jobs, Agents, and Logs views
- Plan agent (Sonnet) + execution agents (Haiku)
- Lifecycle hooks system (`~/.claude-dispatch/hooks/`)
- SQLite session index for history and resume
- Per-agent cost tracking
- `bypassPermissions` + `allowedTools` + `cwd` security model
