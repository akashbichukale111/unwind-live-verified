"""One real Vertex call. Prints the raw response or the exact failure.

The single artifact that proves the mandatory hackathon requirement is met.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("UNWIND_OTEL_CONSOLE", "0")

from lib.config import get_config
from lib.vertex import configure_vertex_backend, get_vertex_client, materialise_credentials

# Materialise BEFORE resolving config: a service-account key names its own
# project, and `get_config()` is cached for the process. Resolving first would
# print -- and then use -- the no-account default `unwind-local`.
materialise_credentials()
cfg = get_config()
print(f"model     : {cfg.model_fast}")
print(f"project   : {cfg.project_id}")
print(f"location  : {cfg.vertex_location}")
print(
    f"auth      : {'access token' if os.environ.get('UNWIND_VERTEX_ACCESS_TOKEN') else 'ADC / key file'}"
)
print(
    f"backend   : {configure_vertex_backend()['GOOGLE_GENAI_USE_ENTERPRISE']} (enterprise=Vertex)"
)
print("-" * 60)
try:
    text = get_vertex_client().generate_text(
        "In one sentence: what does cache invalidation have to do with "
        "decisions that rest on facts which later change?"
    )
    print("RAW RESPONSE:")
    print(text)
    print("-" * 60)
    print("RESULT: Vertex AI reachable. Requirement satisfied.")
except Exception as exc:
    print(f"RESULT: FAILED -- {type(exc).__name__}: {exc}")
    sys.exit(1)
