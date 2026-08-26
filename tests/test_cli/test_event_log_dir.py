"""Tests for event log directory path resolution."""

from pathlib import Path

import pytest

from conductor.cli.run import _resolve_event_log_dir


def test_relative_event_log_dir_is_resolved_from_workflow_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative paths use the workflow file directory, not process CWD."""
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    workflow_path = workflow_dir / "workflow.yaml"
    workflow_path.write_text("", encoding="utf-8")

    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    result = _resolve_event_log_dir("./logs", workflow_path)

    assert result == (workflow_dir / "logs").resolve()
    assert result != (other_cwd / "logs").resolve()


def test_parent_relative_event_log_dir_is_workflow_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent components are evaluated from the workflow directory."""
    workflow_dir = tmp_path / "project" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_path = workflow_dir / "workflow.yaml"
    workflow_path.write_text("", encoding="utf-8")

    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    result = _resolve_event_log_dir("../logs", workflow_path)

    assert result == (workflow_dir.parent / "logs").resolve()


def test_absolute_event_log_dir_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absolute paths do not depend on workflow location or process CWD."""
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    workflow_path = workflow_dir / "workflow.yaml"
    workflow_path.write_text("", encoding="utf-8")

    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    absolute_dir = tmp_path / "absolute-logs"

    assert _resolve_event_log_dir(str(absolute_dir), workflow_path) == absolute_dir


def test_absolute_event_log_dir_is_not_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absolute configured paths are normalized without following symlinks."""
    workflow_path = tmp_path / "workflow.yaml"
    absolute_dir = tmp_path / "symlink-alias"

    def fail_resolve(_path: Path, _strict: bool = False) -> Path:
        pytest.fail("Path.resolve() must not be called for an absolute event_log_dir")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", fail_resolve)
        result = _resolve_event_log_dir(str(absolute_dir), workflow_path)

    assert result == absolute_dir


def test_event_log_dir_expands_user_home(tmp_path: Path) -> None:
    """A leading tilde is expanded before the configured path is returned."""
    result = _resolve_event_log_dir("~/conductor-logs", tmp_path / "workflow.yaml")

    assert result == Path.home() / "conductor-logs"
    assert "~" not in str(result)


@pytest.mark.parametrize("value", [None, ""])
def test_missing_event_log_dir_remains_unset(
    tmp_path: Path,
    value: str | None,
) -> None:
    """Omitted and empty values retain the default TMPDIR behavior."""
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("", encoding="utf-8")

    assert _resolve_event_log_dir(value, workflow_path) is None
