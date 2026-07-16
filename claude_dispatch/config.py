"""Configuration loader for ~/.claude-dispatch/config.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(os.environ.get("CLAUDE_DISPATCH_CONFIG_DIR", "~/.claude-dispatch")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
HOOKS_DIR = CONFIG_DIR / "hooks"
DB_FILE = CONFIG_DIR / "dispatcher.db"


class CostLimits(BaseModel):
    max_cost_per_agent: float = 1.0
    max_cost_per_job: float = 5.0
    warn_cost_dispatcher: float = 10.0


class Defaults(BaseModel):
    plan_model: str = "claude-sonnet-4-6"
    execute_model: str = "claude-haiku-4-5-20251001"
    username: str = ""
    max_parallel_agents: int = 5
    plan_timeout_s: int = 300  # seconds before plan phase is aborted


class ClaudeConfig(BaseModel):
    mcp_config: str = "~/.claude.json"


class HooksConfig(BaseModel):
    enabled: bool = True
    directory: str = str(HOOKS_DIR)


class Config(BaseModel):
    repos: dict[str, str] = Field(default_factory=dict)
    worktree_pattern: str = "{repo}-{job_id}"
    branch_pattern: str = "{username}/{job_id}/{slug}"
    defaults: Defaults = Field(default_factory=Defaults)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    limits: CostLimits = Field(default_factory=CostLimits)
    hooks: HooksConfig = Field(default_factory=HooksConfig)


def load_config() -> Config:
    """Load config from ~/.claude-dispatch/config.yaml, falling back to defaults."""
    if not CONFIG_FILE.exists():
        return Config()
    with CONFIG_FILE.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    return Config(**raw)
