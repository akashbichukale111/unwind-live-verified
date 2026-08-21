"""One authoritative answer to "can this process authenticate to Google?"

WHY THIS MODULE EXISTS — TWO REAL DEFECTS IT FIXES
------------------------------------------------------
1. **ADC was invisible.** `lib/config.py:has_gcp_credentials` tested only
   `GOOGLE_APPLICATION_CREDENTIALS` and `GOOGLE_CLOUD_PROJECT`. After
   `gcloud auth application-default login` **neither of those is set** --
   ADC lives in a well-known JSON file under the user's config directory.
   So a correctly-authenticated operator would still have been told
   NOT_CONFIGURED, forever, with no hint why. That is a false negative in
   exactly the setup a Google Cloud project without API keys must use.

2. **An API key outranked ADC.** A stray `GOOGLE_API_KEY` in the
   environment won over a real service account. On a project where API keys
   are *disallowed by policy*, that turns a working ADC setup into a
   confusing 403. ADC now wins, and a key is used only when ADC is absent.

HOW DETECTION WORKS
----------------------
`google.auth.default()` is the authority, not a guess about environment
variables: it is the same resolver the google-genai SDK itself uses, and it
already knows every legitimate source in priority order --

    GOOGLE_APPLICATION_CREDENTIALS -> gcloud ADC file -> GCE/Cloud Run
    metadata server (the service identity a deployed revision runs as)

so asking it means this module's answer cannot disagree with what a real
call would do. That is the whole point: a status panel that is more
optimistic than the call behind it is worse than no status panel.

The lookup is cached per process because it can touch the filesystem and,
on a metadata-server host, the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: Cache. `None` means "not yet resolved"; `reset_auth_cache()` clears it so
#: tests can vary the environment without leaking state between cases.
_CACHED: AuthState | None = None


@dataclass(frozen=True)
class AuthState:
    """What this process can actually authenticate as, right now."""

    #: "adc" | "api_key" | "none"
    mode: str
    #: The project ADC resolved to, when it could determine one. Empty
    #: otherwise -- a credential without a project cannot call Vertex.
    project: str = ""
    #: Human-readable detail, always populated when mode is "none".
    reason: str = ""
    #: Which concrete source ADC came from, for the evidence record.
    source: str = ""

    @property
    def available(self) -> bool:
        return self.mode != "none"

    def as_record(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "project": self.project,
            "source": self.source,
            "reason": self.reason,
            "available": self.available,
        }


def _adc_well_known_path() -> str:
    """The path `gcloud auth application-default login` writes to.

    Reported in the "how to fix it" message so an operator can see whether
    the file they think they created is where the SDK will look.
    """
    if os.name == "nt":  # pragma: no cover -- this project deploys on Linux
        return os.path.join(
            os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json"
        )
    return os.path.join(
        os.path.expanduser("~"), ".config", "gcloud", "application_default_credentials.json"
    )


def resolve_auth(*, allow_api_key: bool = True) -> AuthState:
    """Resolve once, honestly. Never optimistic.

    `allow_api_key=False` refuses the API-key path outright, for projects
    whose organisation policy disallows API keys -- see
    `UNWIND_DISALLOW_API_KEYS` in `docs/DEPLOY.md`. On such a project a key
    that happens to be in the environment is a trap, not a fallback.
    """
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    _CACHED = _resolve(allow_api_key=allow_api_key)
    return _CACHED


def _resolve(*, allow_api_key: bool) -> AuthState:
    # 1. ADC FIRST. This is the mechanism a Google Cloud project without API
    #    keys is required to use, and the mechanism a deployed Cloud Run
    #    revision uses via its service identity.
    try:
        import google.auth  # noqa: PLC0415

        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        if credentials is not None:
            source = type(credentials).__module__.rsplit(".", 1)[-1]
            resolved_project = (
                project
                or os.environ.get("UNWIND_PROJECT_ID", "")
                or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            )
            if not resolved_project:
                return AuthState(
                    mode="none",
                    source=source,
                    reason=(
                        "ADC resolved a credential but no project. Vertex AI calls are "
                        "project-scoped, so set UNWIND_PROJECT_ID (or run "
                        "`gcloud auth application-default set-quota-project <project>`)."
                    ),
                )
            return AuthState(mode="adc", project=resolved_project, source=source)
    except Exception as exc:  # noqa: BLE001 -- absence is the normal case here
        adc_error = f"{type(exc).__name__}: {exc}"
    else:  # pragma: no cover -- google.auth returning None without raising
        adc_error = "google.auth.default() returned no credential"

    # 2. API key, only where policy permits it.
    key = (
        os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if key and allow_api_key:
        return AuthState(mode="api_key", source="env", project="")
    if key and not allow_api_key:
        return AuthState(
            mode="none",
            reason=(
                "an API key is set but this deployment disallows API keys "
                "(UNWIND_DISALLOW_API_KEYS=1), which matches a Google Cloud project "
                "whose organisation policy blocks key creation. Use Application "
                "Default Credentials instead: `gcloud auth application-default login`."
            ),
        )

    # 3. Nothing. Say precisely what to do about it.
    return AuthState(
        mode="none",
        reason=(
            "no Google credential is available. Run "
            "`gcloud auth application-default login` (writes "
            f"{_adc_well_known_path()}), or set GOOGLE_APPLICATION_CREDENTIALS to a "
            "service-account key, or deploy to Cloud Run where the service identity "
            f"supplies ADC automatically. Underlying resolver said: {adc_error}"
        ),
    )


def api_keys_disallowed() -> bool:
    """True when this deployment must not use an API key.

    Default FALSE so nothing changes for a project that permits keys; set
    `UNWIND_DISALLOW_API_KEYS=1` for a project whose org policy blocks them.
    """
    return os.environ.get("UNWIND_DISALLOW_API_KEYS", "").strip() in {"1", "true", "yes", "on"}


def reset_auth_cache() -> None:
    """Test hook. Mirrors `lib.config.reset_config_cache`."""
    global _CACHED
    _CACHED = None


__all__ = [
    "AuthState",
    "api_keys_disallowed",
    "reset_auth_cache",
    "resolve_auth",
]
