"""Tests for configurable event log output directory."""

import logging
import tempfile
import time
from pathlib import Path

import pytest

import conductor.engine.event_log as event_log_module
from conductor.config.schema import RuntimeConfig
from conductor.engine.event_log import EventLogSubscriber
from conductor.events import WorkflowEvent


def test_runtime_config_event_log_dir() -> None:
    """RuntimeConfig accepts event_log_dir field, defaults to None."""
    assert RuntimeConfig().event_log_dir is None
    assert RuntimeConfig(event_log_dir="./logs").event_log_dir == "./logs"
    assert RuntimeConfig(event_log_dir="/var/log/conductor").event_log_dir == "/var/log/conductor"


def test_runtime_config_normalizes_whitespace() -> None:
    """Empty values normalize to None and surrounding whitespace is stripped."""
    assert RuntimeConfig(event_log_dir="   ").event_log_dir is None
    assert RuntimeConfig(event_log_dir="").event_log_dir is None
    assert RuntimeConfig(event_log_dir=" ./logs ").event_log_dir == "./logs"


def test_default_writes_to_tmpdir() -> None:
    """Without event_log_dir, writes to $TMPDIR/conductor/ (existing behavior)."""
    sub = EventLogSubscriber("test_wf")
    try:
        assert sub.path.parent == Path(tempfile.gettempdir()) / "conductor"
    finally:
        sub.close()


def test_custom_event_log_dir(tmp_path: Path) -> None:
    """With event_log_dir, writes to the specified directory."""
    sub = EventLogSubscriber(
        "test_wf",
        event_log_dir=tmp_path / "logs",
    )
    try:
        assert sub.path.parent == tmp_path / "logs"
        assert sub.path.exists()

        sub.on_event(
            WorkflowEvent(
                type="test",
                timestamp=time.time(),
                data={},
            )
        )
        sub.close()

        assert sub.path.read_text().strip()
    finally:
        sub.close()


def test_existing_path_overrides_event_log_dir(tmp_path: Path) -> None:
    """On resume, existing_path takes precedence over event_log_dir."""
    existing = tmp_path / "existing.events.jsonl"
    existing.write_text("")

    sub = EventLogSubscriber(
        "test_wf",
        existing_path=existing,
        existing_run_id="abcd1234",
        event_log_dir=tmp_path / "custom",
    )

    try:
        assert sub.path == existing
    finally:
        sub.close()


def test_existing_file_event_log_dir_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A configured path that is a file falls back to the default directory."""
    default_tmpdir = tmp_path / "default-tmp"
    default_dir = default_tmpdir / "conductor"
    monkeypatch.setattr(event_log_module.tempfile, "gettempdir", lambda: str(default_tmpdir))

    custom_dir = tmp_path / "not-a-directory"
    custom_dir.write_text("file", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=event_log_module.__name__):
        sub = EventLogSubscriber("test_wf", event_log_dir=custom_dir)
    try:
        assert sub.path.parent == default_dir
        assert sub.path.exists()
    finally:
        sub.close()

    assert "Cannot use event_log_dir" in caplog.text
    assert str(custom_dir) in caplog.text
    assert "falling back to" in caplog.text
    assert str(default_dir) in caplog.text


def test_permission_error_event_log_dir_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A portable synthetic PermissionError triggers the documented fallback."""
    default_tmpdir = tmp_path / "default-tmp"
    default_dir = default_tmpdir / "conductor"
    custom_dir = tmp_path / "custom"
    real_open = open

    monkeypatch.setattr(event_log_module.tempfile, "gettempdir", lambda: str(default_tmpdir))

    def selective_open(path, mode="r", *args, **kwargs):
        if Path(path).parent == custom_dir:
            raise PermissionError("synthetic permission failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(event_log_module, "open", selective_open, raising=False)

    with caplog.at_level(logging.WARNING, logger=event_log_module.__name__):
        sub = EventLogSubscriber("test_wf", event_log_dir=custom_dir)
    try:
        assert sub.path.parent == default_dir
        assert sub.path.exists()
    finally:
        sub.close()

    assert "Cannot use event_log_dir" in caplog.text
    assert str(custom_dir) in caplog.text
    assert "synthetic permission failure" in caplog.text
    assert str(default_dir) in caplog.text


def test_fallback_directory_error_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure after custom-to-default fallback propagates without a loop."""
    default_tmpdir = tmp_path / "default-tmp"
    default_dir = default_tmpdir / "conductor"
    custom_dir = tmp_path / "custom"
    attempted_dirs: list[Path] = []

    monkeypatch.setattr(event_log_module.tempfile, "gettempdir", lambda: str(default_tmpdir))

    def failing_open(path, _mode="r", *_args, **_kwargs):
        attempted_dir = Path(path).parent
        attempted_dirs.append(attempted_dir)
        if attempted_dir == custom_dir:
            raise PermissionError("synthetic custom failure")
        if attempted_dir == default_dir:
            raise PermissionError("synthetic fallback failure")
        pytest.fail(f"Unexpected event-log directory: {attempted_dir}")

    monkeypatch.setattr(event_log_module, "open", failing_open, raising=False)

    with pytest.raises(PermissionError, match="synthetic fallback failure"):
        EventLogSubscriber("test_wf", event_log_dir=custom_dir)

    assert attempted_dirs == [custom_dir, default_dir]
