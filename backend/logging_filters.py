# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# This file is part of FontSync, a self-hosted font manager.
# FontSync is free software: you can redistribute it and/or modify it under the
# terms of the GNU Affero General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed WITHOUT ANY WARRANTY; see the GNU AGPL for details.
# You should have received a copy of the license with this program (see LICENSE),
# or at <https://www.gnu.org/licenses/>.

"""Logging filters keeping the instance token out of uvicorn's logs.

The browser WebSocket and the SSE stream may carry the token as `?token=…`,
and uvicorn logs the full path with its query string (`uvicorn.error` for
WebSocket handshakes, `uvicorn.access` for HTTP requests).
"""

import logging
import re
from urllib.parse import unquote

# `key=value` pairs as they appear in a raw (still percent-encoded) query
# string. Starlette decodes keys, so `tok%65n=…` authenticates like `token=…`:
# the key is compared after decoding.
_KEY_VALUE = re.compile(r'(?P<key>[^?&;\s"=]+)=(?P<value>"?[^&\s"]+)')
# Any literal `token=` left, even inside another pair's value (`a=1;token=…`,
# `x=%26token=…`): a misnamed key is refused, but its value may be the token.
_TOKEN_ANYWHERE = re.compile(r'(?i)(token=)"?[^&\s"]+')

# Loggers whose records may contain a request path with its query string.
REDACTED_LOGGERS = ("uvicorn.error", "uvicorn.access")


def _redact_pair(match: re.Match[str]) -> str:
    key = match.group("key")
    if unquote(key).lower().endswith("token"):
        return f"{key}=***"
    return match.group(0)


def redact_token(text: str) -> str:
    """Mask every token value in `text`.

    Masks the value of each `key=value` pair whose percent-decoded key ends with
    `token`, then any remaining literal `token=<value>` (case-insensitive).
    """
    text = _KEY_VALUE.sub(_redact_pair, text)
    return _TOKEN_ANYWHERE.sub(r"\1***", text)


class TokenRedactionFilter(logging.Filter):
    """Redact `token=` values in a record's message and string arguments.

    `record.args` keeps its shape: `uvicorn.logging.AccessFormatter` unpacks a
    5-tuple. The filter never drops a record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_token(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_token(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_token(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def install_token_redaction() -> None:
    """Attach `TokenRedactionFilter` once to each logger of `REDACTED_LOGGERS`."""
    for name in REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, TokenRedactionFilter) for f in logger.filters):
            logger.addFilter(TokenRedactionFilter())
