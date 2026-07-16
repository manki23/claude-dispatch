"""Tests for config loading."""

from __future__ import annotations

from claude_dispatch.config import Config


def test_default_config():
    config = Config()
    assert config.defaults.plan_model == "claude-sonnet-4-6"
    assert config.defaults.execute_model == "claude-haiku-4-5-20251001"
    assert config.defaults.max_parallel_agents == 5
    assert config.repos == {}


def test_config_from_dict():
    raw = {
        "repos": {"my-repo": "~/code/my-repo"},
        "defaults": {"username": "testuser"},
    }
    config = Config(**raw)
    assert config.repos == {"my-repo": "~/code/my-repo"}
    assert config.defaults.username == "testuser"
    # Defaults still applied for unset fields
    assert config.defaults.plan_model == "claude-sonnet-4-6"


def test_cost_limits_defaults():
    config = Config()
    assert config.limits.max_cost_per_agent == 1.0
    assert config.limits.max_cost_per_job == 5.0
