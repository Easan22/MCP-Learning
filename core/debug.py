import json
import os
from typing import Any


def debug_enabled() -> bool:
    return os.getenv("MCP_CHAT_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def debug_log(label: str, payload: Any | None = None):
    if not debug_enabled():
        return

    print(f"[debug] {label}")
    if payload is None:
        return

    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return

    print(payload)
