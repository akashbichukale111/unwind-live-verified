"""The single Vertex AI client.

One module owns model access so that "T0 and T1 survive a total Vertex outage"
is enforceable rather than aspirational: there is exactly one place a model call
can originate, and `UNWIND_VERTEX_DISABLED=1` closes it. Task 2 runs the whole
cascade with that flag set, and any code path that reaches for a model raises
`VertexDisabledError` loudly instead of degrading quietly.

The model string is not defined here. It lives in lib/config.py and nowhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from lib.config import Config, get_config
from lib.telemetry import model_call_span


def materialise_credentials() -> str | None:
    """Turn a credential SECRET into something google.auth can actually read.

    A secret store holds values, but `google.auth` looks for a FILE PATH in
    `GOOGLE_APPLICATION_CREDENTIALS`. That mismatch is the whole reason a
    correctly-configured secret can still produce `DefaultCredentialsError`.

    So: if `GOOGLE_APPLICATION_CREDENTIALS_JSON` holds a service-account key,
    write it to a file with owner-only permissions and point the standard
    variable at it. The file lives in the container's temp directory, never in
    the repository, and dies with the container.

    Returns the path written, or None when there was nothing to materialise.
    """
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not raw or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return None

    import json  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VertexUnavailableError(
            "GOOGLE_APPLICATION_CREDENTIALS_JSON is set but is not valid JSON "
            f"({exc}). It should hold the full contents of a service-account "
            "key file."
        ) from exc

    path = os.path.join(tempfile.gettempdir(), "unwind-gcp-key.json")
    # Owner-only: a credential readable by anything else on the box is not a
    # credential, it is a published secret.
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

    # A key file names its own project, so the caller need not set it twice.
    if parsed.get("project_id") and not os.environ.get("UNWIND_PROJECT_ID"):
        os.environ["UNWIND_PROJECT_ID"] = parsed["project_id"]
        # `get_config()` is cached for the process. Any caller that resolved it
        # BEFORE the key was materialised is holding the no-account default
        # `unwind-local`, and would build a client against a project that does
        # not exist -- failing with a confusing 403 rather than the real cause.
        # Drop the cache so the project the key actually belongs to wins.
        from lib.config import reset_config_cache  # noqa: PLC0415

        reset_config_cache()
    return path


def configure_vertex_backend() -> dict[str, str]:
    """Pin the google-genai backend to Vertex AI, from config, before any client.

    WITHOUT THIS, ADK SILENTLY USES THE BARE GEMINI API. `Agent(model="gemini-...")`
    resolves its backend from the environment, and with nothing set it falls
    through to the developer API and asks for an API key. Vertex is a hard
    requirement, so it is set from `lib.config` rather than left to whatever the
    shell happens to export.

    The flag is `GOOGLE_GENAI_USE_ENTERPRISE`. `GOOGLE_GENAI_USE_VERTEXAI` is the
    older name and is deprecated in google-adk 2.6.3 / google-genai 2.17.0 --
    setting it still works but emits a DeprecationWarning, so it is not set here.

    Returns the environment it applied, so callers can report it rather than
    assume it.
    """
    materialise_credentials()
    cfg = get_config()
    applied = {
        "GOOGLE_GENAI_USE_ENTERPRISE": "true",
        "GOOGLE_CLOUD_PROJECT": cfg.project_id,
        "GOOGLE_CLOUD_LOCATION": cfg.vertex_location,
    }
    for key, value in applied.items():
        os.environ[key] = value
    return applied


class VertexDisabledError(RuntimeError):
    """Raised when a model call is attempted while Vertex is disabled.

    This is the failure mode we WANT: a T0/T1 path that quietly acquired a model
    dependency fails the outage test instead of passing it by accident.
    """


class VertexUnavailableError(RuntimeError):
    """Raised when credentials or the endpoint are genuinely unreachable."""


@dataclass
class VertexClient:
    """Wraps google-genai in Vertex mode.

    `google-genai` is already a transitive dependency of ADK 2.6.3, so this adds
    no new service to the stack -- it is the same client ADK itself uses.
    """

    config: Config

    def __post_init__(self) -> None:
        if self.config.vertex_disabled:
            raise VertexDisabledError(
                "UNWIND_VERTEX_DISABLED=1: a model call was attempted on a path "
                "that must be model-free. This is the tiered-degradation guard, "
                "not a misconfiguration."
            )
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from google import genai  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover
                raise VertexUnavailableError("google-genai is not installed") from exc
            configure_vertex_backend()
            # Re-resolve AFTER materialising: the key may have supplied the
            # project, in which case `self.config` predates it.
            cfg = get_config()
            self.config = cfg

            kwargs: dict[str, Any] = {
                # Vertex AI, not the developer Gemini API.
                "enterprise": True,
                "project": cfg.project_id,
                "location": cfg.vertex_location,
            }

            # A short-lived OAuth token is the cheapest way to reach Vertex from
            # a machine that has no gcloud install and no ADC file -- which is
            # the normal situation for a remote build container. Authenticating
            # on a laptop does not carry credentials onto a different host, so
            # this accepts a token minted there and pasted here. It expires in
            # about an hour, which makes it far safer to move around than a
            # service-account key.
            token = os.environ.get("UNWIND_VERTEX_ACCESS_TOKEN")
            if token:
                from google.oauth2.credentials import Credentials  # noqa: PLC0415

                kwargs["credentials"] = Credentials(token=token)

            self._client = genai.Client(**kwargs)
        return self._client

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        """Single-shot generation. T2 only, and traced as such.

        [VERIFIED] Executed against live Vertex on 2026-08-13 by
        `make verify-live`: call OK, 0 model errors. See
        `docs/LIVE-VERIFICATION.md` and README "What has actually been run".
        """
        model = self.config.gemini_model
        with model_call_span(model, prompt_chars=len(prompt)) as span:
            client = self._ensure_client()
            response = client.models.generate_content(model=model, contents=prompt, **kwargs)
            text = getattr(response, "text", "") or ""
            span.set_attribute("unwind.response_chars", len(text))
            return text


_CLIENT: VertexClient | None = None


def get_vertex_client() -> VertexClient:
    """Process-wide Vertex client. Raises if Vertex is disabled."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = VertexClient(config=get_config())
    return _CLIENT


def reset_vertex_client() -> None:
    """Test hook."""
    global _CLIENT
    _CLIENT = None


def vertex_available() -> bool:
    """Whether a model call is permitted right now. Never guesses about network."""
    return not get_config().vertex_disabled
