"""Useful production stack locations without messages, request data or secrets."""

import logging
from pathlib import Path
import re


def exception_summary(error):
    """Never stringify exceptions: database errors can include connection details."""
    parts = [type(error).__name__]
    seen = set()
    current = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        state = getattr(current, "sqlstate", None)

        if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state):
            parts.append("sqlstate=" + state)
            break

        current = current.__cause__

    return " ".join(parts)


class SafeExceptionFormatter(logging.Formatter):
    def format(self, record):
        # Do not format record.msg/args, request, stack_info or cached exc_text.
        status = getattr(record, "status_code", None)
        lines = [f"{record.levelname} {record.name}"]

        if isinstance(status, int):
            lines[0] += f" status={status}"

        if record.exc_info and record.exc_info[1] is not None:
            lines.append(exception_summary(record.exc_info[1]))
            tb = record.exc_info[2]

            while tb is not None:
                code = tb.tb_frame.f_code
                lines.append(
                    f"  {Path(code.co_filename).name}:{tb.tb_lineno}"
                    f" in {code.co_name}"
                )
                tb = tb.tb_next

        return "\n".join(lines)