"""The instance token passed as `?token=` never reaches uvicorn's logs in clear.

Importing `backend.main` installs a filter on `uvicorn.error` (WebSocket
handshake lines) and `uvicorn.access` (request lines, 5-tuple args unpacked by
`uvicorn.logging.AccessFormatter`).
"""

from __future__ import annotations

import logging

import pytest
from uvicorn.logging import AccessFormatter

import backend.main  # noqa: F401  (installs the redaction filters)

TOKEN = "s3cr3t+tok/en=="
TOKEN_URLENCODED = "s3cr3t%2Btok%2Fen%3D%3D"


def _emit(logger_name: str, msg: str, args: tuple[object, ...]) -> logging.LogRecord:
    """Build a record as uvicorn would and run it through the logger's filters."""
    logger = logging.getLogger(logger_name)
    record = logger.makeRecord(logger_name, logging.INFO, __file__, 0, msg, args, None)
    assert logger.filter(record), "redaction filter must never drop a record"
    return record


@pytest.mark.parametrize("token", [TOKEN_URLENCODED, TOKEN, "plain-token_123"])
def test_websocket_handshake_line_is_redacted(token: str) -> None:
    record = _emit(
        "uvicorn.error",
        '%s - "WebSocket %s" [accepted]',
        (("127.0.0.1", 50000), f"/ws/client?token={token}"),
    )
    line = record.getMessage()
    assert token not in line
    assert "token=***" in line
    assert line.startswith("('127.0.0.1', 50000) - \"WebSocket /ws/client?")


def test_token_in_the_middle_of_the_query_is_redacted() -> None:
    record = _emit(
        "uvicorn.error",
        '%s - "WebSocket %s" 403',
        (("10.0.0.2", 1), f"/ws/client?a=1&token={TOKEN_URLENCODED}&b=2"),
    )
    assert record.getMessage().endswith('"WebSocket /ws/client?a=1&token=***&b=2" 403')


@pytest.mark.parametrize("key", ["tok%65n", "%74oken", "%74%6F%6B%65%6E", "TOKEN"])
def test_percent_encoded_token_key_is_redacted(key: str) -> None:
    """Starlette decodes query keys: `tok%65n=` authenticates like `token=`."""
    record = _emit(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1",
            "GET",
            f"/api/agent/d/events?{key}={TOKEN_URLENCODED}",
            "1.1",
            200,
        ),
    )
    message = record.getMessage()
    assert TOKEN_URLENCODED not in message
    assert f"?{key}=*** HTTP/1.1" in message


@pytest.mark.parametrize(
    "query",
    [
        f"a=1;token={TOKEN_URLENCODED}",
        f"a=b?token={TOKEN_URLENCODED}",
        f"x=%26token={TOKEN_URLENCODED}",
        f'token="{TOKEN_URLENCODED}',
    ],
)
def test_token_hidden_inside_another_value_is_redacted(query: str) -> None:
    """A misnamed key is refused (401), but its value may still be the token."""
    record = _emit(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"/api/agent/d/events?{query}", "1.1", 401),
    )
    assert TOKEN_URLENCODED not in record.getMessage()


def test_every_token_pair_is_redacted() -> None:
    """Starlette authenticates with the last `token` value: all must be masked."""
    record = _emit(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1",
            "GET",
            f"/api/agent/d/events?token=decoy&token={TOKEN_URLENCODED}",
            "1.1",
            200,
        ),
    )
    message = record.getMessage()
    assert "decoy" not in message
    assert TOKEN_URLENCODED not in message


def test_other_query_values_are_kept() -> None:
    record = _emit(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/x?page=2&tokens_left=3&q=token", "1.1", 200),
    )
    assert record.getMessage().endswith(
        '"GET /x?page=2&tokens_left=3&q=token HTTP/1.1" 200'
    )


def test_access_line_keeps_its_five_tuple_and_is_redacted() -> None:
    record = _emit(
        "uvicorn.access",
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:50001",
            "GET",
            f"/api/agent/events?token={TOKEN_URLENCODED}",
            "1.1",
            200,
        ),
    )
    assert isinstance(record.args, tuple) and len(record.args) == 5
    formatter = AccessFormatter(
        fmt='%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    )
    line = formatter.format(record)
    assert TOKEN_URLENCODED not in line
    assert "/api/agent/events?token=*** HTTP/1.1" in line
    assert "200" in line


def test_line_without_token_is_untouched() -> None:
    args = (("127.0.0.1", 50002), "/ws/client?foo=bar")
    record = _emit("uvicorn.error", '%s - "WebSocket %s" [accepted]', args)
    assert record.args == args
    assert (
        record.getMessage()
        == "('127.0.0.1', 50002) - \"WebSocket /ws/client?foo=bar\" [accepted]"
    )


def test_token_in_message_text_is_redacted() -> None:
    record = _emit("uvicorn.error", f"Invalid HTTP request /x?token={TOKEN}", ())
    assert TOKEN not in record.getMessage()
