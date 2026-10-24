import json
import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.clock import SystemClock
from core.logging import JsonFormatter
from db.models import UTCDateTime


def test_structured_log_excludes_arbitrary_message_and_exception() -> None:
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "secret-password", (), None)
    record.event = "request_failed"
    record.request_id = "example-correlation-id"
    record.student_inventory = "private-item"
    result = JsonFormatter().format(record)
    assert "secret-password" not in result
    assert "private-item" not in result
    assert json.loads(result)["event"] == "request_failed"
    assert datetime.fromisoformat(json.loads(result)["timestamp"]).utcoffset() == timedelta(0)


def test_system_clock_is_aware_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="Naive"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), object())


def test_timestamp_normalized_to_utc() -> None:
    value = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=3)))
    result = UTCDateTime().process_bind_param(value, object())
    assert result == datetime(2026, 1, 1, 9, tzinfo=UTC)
