"""Tests for Jarvis vault context injection (issue #38)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from claude_code_sdk.types import ResultMessage

from claude_dispatch.jarvis import fetch_prior_context
from claude_dispatch.job import Job


def _result_msg(session_id: str = "sess-1") -> ResultMessage:
    return ResultMessage(
        subtype="result",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.0,
    )


# ── fetch_prior_context unit tests ────────────────────────────────────────────


def test_returns_none_when_vault_missing(tmp_path: Path) -> None:
    """Non-existent vault path → None, no exception."""
    result = fetch_prior_context("Fix MOPU-668", tmp_path / "no-such-vault")
    assert result is None


def test_returns_none_when_no_ticket_ids(tmp_path: Path) -> None:
    """Description with no Jira-style IDs → None."""
    result = fetch_prior_context("Just a plain task description", tmp_path)
    assert result is None


def test_returns_none_when_no_matching_note(tmp_path: Path) -> None:
    """Ticket ID in description but no vault file found → None."""
    result = fetch_prior_context("Fix MOPU-999", tmp_path)
    assert result is None


def test_injects_note_content(tmp_path: Path) -> None:
    """Matching vault note → context block includes ticket ID and content."""
    note = tmp_path / "MOPU-668 - My PR.md"
    note.write_text("PR #18294 IN REVIEW. Waiting for TD.")

    result = fetch_prior_context("Fix MOPU-668 regression", tmp_path)

    assert result is not None
    assert "MOPU-668" in result
    assert "PR #18294 IN REVIEW" in result
    assert "## Prior context" in result
    assert "Do NOT redo" in result


def test_deduplicates_repeated_ticket_ids(tmp_path: Path) -> None:
    """Same ticket mentioned twice → note included once."""
    note = tmp_path / "MOPU-668 - My PR.md"
    note.write_text("PR content.")

    result = fetch_prior_context("MOPU-668 and also MOPU-668 again", tmp_path)

    assert result is not None
    assert result.count("MOPU-668") == result.count("MOPU-668")  # no doubled section
    assert result.count("### MOPU-668") == 1


def test_multiple_ticket_ids(tmp_path: Path) -> None:
    """Multiple ticket IDs → all matching notes included."""
    (tmp_path / "MOPU-668 - PR.md").write_text("PR in review.")
    (tmp_path / "MOPU-670 - dogweb.md").write_text("Root fix merged.")

    result = fetch_prior_context("Work on MOPU-668 and MOPU-670", tmp_path)

    assert result is not None
    assert "MOPU-668" in result
    assert "MOPU-670" in result


def test_partial_match_ignored(tmp_path: Path) -> None:
    """Only ticket IDs present in description are injected."""
    (tmp_path / "MOPU-668 - PR.md").write_text("PR content.")
    (tmp_path / "MOPU-670 - dogweb.md").write_text("Root fix.")

    result = fetch_prior_context("Only MOPU-668 is relevant here", tmp_path)

    assert result is not None
    assert "MOPU-668" in result
    assert "MOPU-670" not in result


def test_note_truncated_at_max_chars(tmp_path: Path) -> None:
    """Notes longer than 2000 chars are truncated."""
    note = tmp_path / "MOPU-1 - Big note.md"
    note.write_text("x" * 3000)

    result = fetch_prior_context("Task for MOPU-1", tmp_path)

    assert result is not None
    assert "… (truncated)" in result


def test_glob_finds_nested_note(tmp_path: Path) -> None:
    """Note in a subdirectory is still found via glob."""
    subdir = tmp_path / "01-Work" / "Jira"
    subdir.mkdir(parents=True)
    (subdir / "MOPU-668 - PR.md").write_text("Nested note content.")

    result = fetch_prior_context("Fix MOPU-668", tmp_path)

    assert result is not None
    assert "Nested note content." in result


def test_unreadable_note_skipped(tmp_path: Path) -> None:
    """OSError on note read → that note is silently skipped, others included."""
    (tmp_path / "MOPU-668 - PR.md").write_text("Good note.")
    bad = tmp_path / "MOPU-670 - bad.md"
    bad.write_text("content")

    original_read = Path.read_text

    def patched_read(self: Path, **kwargs):  # type: ignore[override]
        if self.name.startswith("MOPU-670"):
            raise OSError("permission denied")
        return original_read(self, **kwargs)

    with patch.object(Path, "read_text", patched_read):
        result = fetch_prior_context("MOPU-668 and MOPU-670", tmp_path)

    assert result is not None
    assert "Good note." in result
    assert "MOPU-670" not in result


# ── integration: Job._fetch_prior_context ─────────────────────────────────────


def _make_job(tmp_path: Path, vault_path: str = "", enabled: bool = True) -> Job:
    from claude_dispatch.config import Config, JarvisConfig

    cfg = Config()
    cfg.jarvis = JarvisConfig(enabled=enabled, vault_path=vault_path)
    return Job(
        description="Fix MOPU-668 regression",
        config=cfg,
        db_enabled=False,
        _use_workers=False,
    )


def test_fetch_prior_context_disabled(tmp_path: Path) -> None:
    """jarvis.enabled=false → _fetch_prior_context returns None."""
    (tmp_path / "MOPU-668 - note.md").write_text("PR content.")
    job = _make_job(tmp_path, vault_path=str(tmp_path), enabled=False)
    assert job._fetch_prior_context() is None


def test_fetch_prior_context_no_vault_path(tmp_path: Path) -> None:
    """vault_path empty → _fetch_prior_context returns None."""
    job = _make_job(tmp_path, vault_path="")
    assert job._fetch_prior_context() is None


def test_fetch_prior_context_injects_note(tmp_path: Path) -> None:
    """vault_path set + matching note → context block returned."""
    (tmp_path / "MOPU-668 - PR.md").write_text("PR #18294 IN REVIEW.")
    job = _make_job(tmp_path, vault_path=str(tmp_path))
    result = job._fetch_prior_context()
    assert result is not None
    assert "PR #18294 IN REVIEW." in result


def test_fetch_prior_context_never_raises(tmp_path: Path) -> None:
    """Exception inside jarvis.fetch_prior_context → swallowed, returns None."""
    job = _make_job(tmp_path, vault_path=str(tmp_path))

    with patch("claude_dispatch.jarvis.fetch_prior_context", side_effect=RuntimeError("boom")):
        result = job._fetch_prior_context()

    assert result is None


# ── integration: context appears in plan prompt ──────────────────────────────────────────────


async def _run_plan_and_capture(tmp_path: Path, enabled: bool) -> str:
    """Helper: run plan phase with a vault note and return the captured prompt."""
    from claude_dispatch.config import Config, JarvisConfig
    from claude_dispatch.job import Job

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "MOPU-668 - PR.md").write_text("PR #18294 IN REVIEW.")

    cfg = Config()
    cfg.jarvis = JarvisConfig(enabled=enabled, vault_path=str(vault))

    job = Job(
        description="Fix MOPU-668 regression",
        config=cfg,
        db_enabled=False,
        _use_workers=False,
    )
    job._workdir = tmp_path
    captured: list[str] = []

    async def fake_query(prompt, options):  # type: ignore[no-untyped-def]
        captured.append(prompt)
        (tmp_path / "job-plan.yaml").write_text(yaml.dump({"summary": "test", "agents": []}))
        yield _result_msg()

    with patch("claude_dispatch.agent.query", fake_query):
        await job._run_plan_phase()

    return captured[0]


@pytest.mark.asyncio
async def test_plan_prompt_includes_prior_context(tmp_path: Path) -> None:
    """When vault has a matching note, plan prompt includes the context block."""
    prompt = await _run_plan_and_capture(tmp_path, enabled=True)
    assert "## Prior context" in prompt
    assert "PR #18294 IN REVIEW." in prompt
    assert "MOPU-668" in prompt


@pytest.mark.asyncio
async def test_plan_prompt_no_context_when_disabled(tmp_path: Path) -> None:
    """jarvis.enabled=false -> no prior context block in plan prompt."""
    prompt = await _run_plan_and_capture(tmp_path, enabled=False)
    assert "## Prior context" not in prompt
