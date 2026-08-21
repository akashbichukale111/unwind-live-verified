"""Run the smoke agent once. `make smoke`.

Requires Vertex AI credentials. Without them this exits non-zero with the reason
printed -- it does not pretend to have succeeded.
"""

from __future__ import annotations

import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.smoke.agent import root_agent
from lib.config import get_config
from lib.telemetry import configure_telemetry


async def _main() -> int:
    cfg = get_config()
    exporter = configure_telemetry()
    print(f"model={cfg.gemini_model} location={cfg.vertex_location} telemetry={exporter}")

    if cfg.vertex_disabled:
        print("UNWIND_VERTEX_DISABLED=1 -- the smoke agent is T2 and cannot run.", file=sys.stderr)
        return 2

    runner = InMemoryRunner(agent=root_agent, app_name="unwind-smoke")
    session = await runner.session_service.create_session(
        app_name="unwind-smoke", user_id="smoke-user"
    )
    message = types.Content(
        role="user", parts=[types.Part(text="What is the guarantee for tier T0?")]
    )

    saw_output = False
    async for event in runner.run_async(
        user_id="smoke-user", session_id=session.id, new_message=message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    saw_output = True
                    print(part.text, end="")
    print()
    return 0 if saw_output else 1


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001
        print(f"smoke agent failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "This almost always means Vertex AI credentials are missing. "
            "Run: gcloud auth application-default login",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
