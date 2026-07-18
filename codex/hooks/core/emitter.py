from __future__ import annotations

import json


def emit_hook_json(
    event: str,
    context: str,
) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        },
        ensure_ascii=True,
    )
