"""The deploy preflight must fire on a broken deploy, not just pass on a good one.

`infra/deploy.sh` has never executed, so the preflight is the only thing standing
between a bad input and a failed Cloud Build six minutes in. R8 applies: every
guard ships with a vacuity test.

These tests exercise the two guards that already caught real defects during
Task 6 -- the region/location conflation and the wrong-artifact deploy -- plus
the over-broad-match bug the preflight itself had (it flagged a COMMENT
explaining why `adk deploy` is not used).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "infra" / "deploy.sh").read_text(encoding="utf-8")


def _load_preflight():
    """Load `scripts/deploy_check.py` by path — `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "unwind_deploy_check", REPO / "scripts" / "deploy_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load_preflight()


def _invokes_adk(script: str) -> bool:
    """The same rule the preflight uses: an invocation, not a mention."""
    return any(
        line.strip().startswith("adk deploy")
        for line in script.splitlines()
        if not line.lstrip().startswith("#")
    )


# ---------------------------------------------------------------------------
# the wrong-artifact guard
# ---------------------------------------------------------------------------


def test_the_real_script_does_not_invoke_adk_deploy() -> None:
    """`adk deploy` serves the ADK dev UI, not web/static. It must not be used."""
    assert not _invokes_adk(SCRIPT)


def test_the_adk_guard_is_not_vacuous() -> None:
    """VACUITY: a script that really invokes it must be caught."""
    broken = "#!/usr/bin/env bash\nadk deploy cloud_run --project x agents\n"
    assert _invokes_adk(broken)


def test_the_adk_guard_does_not_fire_on_a_comment() -> None:
    """The complement, and the bug this check actually had.

    deploy.sh explains in a comment why it does NOT use `adk deploy`. A plain
    substring match flagged that prose as the defect it was warning about --
    a guard that cries wolf trains everyone to ignore it.
    """
    commented = (
        "#!/usr/bin/env bash\n# NOT `adk deploy cloud_run` -- see below\ngcloud run deploy x\n"
    )
    assert not _invokes_adk(commented)


# ---------------------------------------------------------------------------
# ⚠ the region / Vertex-location guard — the defect most likely to kill run #1
# ---------------------------------------------------------------------------


def test_cloud_run_region_is_never_derived_from_the_vertex_location() -> None:
    """`global` is a valid Vertex location and NOT a valid Cloud Run region.

    The previous script read `--region "${UNWIND_VERTEX_LOCATION:-us-central1}"`.
    Since the verified live run exports UNWIND_VERTEX_LOCATION=global, the first
    real deploy would have passed `--region global` and failed.
    """
    assert "UNWIND_RUN_REGION" in SCRIPT, "Cloud Run region has no variable of its own"
    # The --region flag must be fed by RUN_REGION, never by the Vertex location.
    region_lines = [ln for ln in SCRIPT.splitlines() if "--region" in ln]
    assert region_lines
    for line in region_lines:
        assert "VERTEX_LOCATION" not in line, f"region derived from Vertex location: {line}"


def test_the_script_refuses_a_global_cloud_run_region() -> None:
    assert 'RUN_REGION}" == "global"' in SCRIPT or "RUN_REGION == global" in SCRIPT, (
        "deploy.sh does not explicitly reject region=global"
    )


def test_vertex_location_is_still_passed_to_the_service() -> None:
    """Rejecting `global` as a REGION must not drop it as the Vertex LOCATION."""
    assert "UNWIND_VERTEX_LOCATION=${VERTEX_LOCATION}" in SCRIPT


# ---------------------------------------------------------------------------
# least privilege
# ---------------------------------------------------------------------------


def test_runtime_roles_are_least_privilege() -> None:
    roles = set(re.findall(r"roles/[a-zA-Z.]+", SCRIPT))
    assert {"roles/aiplatform.user", "roles/datastore.user", "roles/pubsub.publisher"} <= roles
    assert not ({"roles/owner", "roles/editor"} & roles), "over-broad role granted"


# ---------------------------------------------------------------------------
# the container entrypoint Cloud Run requires
# ---------------------------------------------------------------------------


def test_procfile_is_cloud_run_shaped() -> None:
    body = (REPO / "Procfile").read_text(encoding="utf-8")
    assert "services.api.main:app" in body, "the Procfile serves the wrong app"
    assert "0.0.0.0" in body, "Cloud Run requires binding 0.0.0.0"
    assert "PORT" in body, "Cloud Run injects $PORT and the container must honour it"


def test_the_dead_nextjs_skeleton_is_excluded_from_the_build() -> None:
    ignore = (REPO / ".gcloudignore").read_text(encoding="utf-8")
    assert "web/app" in ignore, "buildpacks could detect a Node app and build the wrong thing"


# ---------------------------------------------------------------------------
# ⚠ what Cloud Run actually uploads — the defect that killed build 89b74d60
#
# `gcloud run deploy --source .` uploads the WORKING DIRECTORY and never reads
# .dockerignore. Without a .gcloudignore, exclusions fall back to .gitignore,
# so any untracked non-ignored root file is shipped to Cloud Build.
# ---------------------------------------------------------------------------

GCLOUDIGNORE = REPO / ".gcloudignore"


def test_the_source_upload_has_an_explicit_exclusion_file() -> None:
    assert GCLOUDIGNORE.is_file(), (
        ".dockerignore does not govern a source deploy; without .gcloudignore the "
        "upload set is whatever happens to be untracked in the working directory"
    )


def test_foreign_package_managers_cannot_reach_the_build() -> None:
    """poetry.lock/uv.lock outrank pyproject.toml in the buildpack's selection."""
    ignore = GCLOUDIGNORE.read_text(encoding="utf-8")
    for marker in ("poetry.lock", "Pipfile"):
        assert marker in ignore, f"{marker} would divert the buildpack off pip"


def test_poetry_lock_can_never_be_committed_either() -> None:
    assert "poetry.lock" in (REPO / ".gitignore").read_text(encoding="utf-8")


def test_the_exclusions_do_not_starve_the_running_service() -> None:
    """VACUITY, in the dangerous direction: an over-broad ignore ships a 500.

    Excluding too much is the failure mode a `.gcloudignore` invites. Each path
    below is read at request time, so its absence is a runtime error rather than
    a build error -- exactly the class this file exists to catch early.
    """
    ignore = GCLOUDIGNORE.read_text(encoding="utf-8")
    live = [ln.strip() for ln in ignore.splitlines() if ln.strip() and not ln.startswith("#")]
    for required in ("corpus/data", "web/static", "Procfile", "pyproject.toml", "evals/golden"):
        for pattern in live:
            assert not required.startswith(pattern.rstrip("/")), (
                f"{required} is read at runtime but {pattern!r} excludes it"
            )


# ---------------------------------------------------------------------------
# ⚠ the interpreter ceiling — the confirmed cause of the failed build
# ---------------------------------------------------------------------------


def _upper_bounded(pyproject: str) -> bool:
    """The same rule the preflight uses."""
    found = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
    return bool(found and "<" in found.group(1))


def test_requires_python_does_not_exclude_the_pinned_interpreter() -> None:
    """`<3.13` made pip refuse the project on the buildpack's default Python.

    ERROR: Package 'unwind' requires a different Python: 3.13.12 not in '<3.13,>=3.12'
    """
    assert not _upper_bounded((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_upper_bound_guard_is_not_vacuous() -> None:
    """VACUITY: the exact string that failed must still be caught."""
    assert _upper_bounded('requires-python = ">=3.12,<3.13"')
    assert not _upper_bounded('requires-python = ">=3.12"')


# ---------------------------------------------------------------------------
# ⚠ .python-version — the pin, and its agreement with requires-python
#
# The pin decides which interpreter Cloud Build installs. requires-python
# decides whether pip then accepts the project on it. Build 89b74d60 is what
# happens when those two disagree, so both are asserted, together.
# ---------------------------------------------------------------------------

satisfies = PREFLIGHT.python_pin_satisfies
PIN = (REPO / ".python-version").read_text(encoding="utf-8").strip()
REQUIRES = re.search(
    r'requires-python\s*=\s*"([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8")
).group(1)


def test_the_interpreter_is_pinned_in_the_source() -> None:
    """Unpinned, the buildpack takes the newest Python it supports.

    That makes the deployed runtime a moving target changed by Google's release
    schedule rather than by a commit in this repository.
    """
    assert (REPO / ".python-version").is_file()
    assert re.fullmatch(r"3\.\d+(\.\d+)?", PIN), f"unusable pin: {PIN!r}"


def test_the_pin_reaches_cloud_build() -> None:
    """A pin excluded from the upload is not a pin, and fails silently."""
    assert ".python-version" not in PREFLIGHT.gcloudignore_patterns(REPO)


def test_the_exclusion_reader_ignores_its_own_documentation(tmp_path: Path) -> None:
    """VACUITY + the complement, and the bug this check actually had.

    .gcloudignore documents what it deliberately KEEPS, so a substring search
    over the file text read ".python-version" out of the comment explaining that
    it must never be excluded -- and the preflight failed a correct repository.
    Third occurrence of this class here, so it gets a test of its own.
    """
    (tmp_path / ".gcloudignore").write_text(
        "# KEPT ON PURPOSE:\n#   .python-version   pins the interpreter\ntests/\n",
        encoding="utf-8",
    )
    patterns = PREFLIGHT.gcloudignore_patterns(tmp_path)
    assert patterns == ["tests/"]
    assert ".python-version" not in patterns  # the false positive

    (tmp_path / ".gcloudignore").write_text(".python-version\n", encoding="utf-8")
    assert ".python-version" in PREFLIGHT.gcloudignore_patterns(tmp_path)  # the real one


def test_the_pin_and_requires_python_agree() -> None:
    assert satisfies(PIN, REQUIRES), f"{PIN} is outside {REQUIRES}"


def test_the_agreement_check_is_not_vacuous() -> None:
    """VACUITY: reconstruct the exact combination that failed the build.

    A checker that returns True unconditionally would let 89b74d60 through
    again, so the failing pair must still be rejected.
    """
    assert not satisfies("3.13", ">=3.12,<3.13"), "the failed build's pair must be rejected"
    assert not satisfies("3.11", ">=3.12")
    assert satisfies("3.13", ">=3.12")
    assert satisfies("3.12", ">=3.12,<3.13")


def test_the_agreement_check_compares_on_stated_precision() -> None:
    """`3.13` vs `>=3.12` must not become (3,13) >= (3,12,0) and mis-compare."""
    assert satisfies("3.13.12", ">=3.12")
    assert satisfies("3.13", ">=3.12.5")
    assert not satisfies("3.13", "<3.13.0")


# ---------------------------------------------------------------------------
# ⚠ check #11 — the preflight asserted a build mechanism this repo does not use
#
# The deploy is `gcloud run deploy --source .`: buildpacks read the Procfile and
# there is no Dockerfile, by design. Check #11 ran `docker build` whenever the
# docker BINARY was on PATH, so on any machine with a running daemon the
# preflight failed on a correct repository. The daemon-down case had already
# been softened to a WARN, which hid the real defect: the check was keyed on
# the wrong artifact.
# ---------------------------------------------------------------------------

plan = PREFLIGHT.container_build_plan


def test_no_dockerfile_means_no_docker_build_is_attempted(tmp_path: Path) -> None:
    """A: the reported failure. Docker installed AND the daemon up, no Dockerfile.

    `docker_on_path=True` is the Codespace that failed. The plan must not be
    `build`, because there is nothing to build and the deploy does not want one.
    """
    assert plan(tmp_path, docker_on_path=True) == "no-dockerfile"


def test_the_skip_is_not_vacuous_a_real_dockerfile_is_still_built(tmp_path: Path) -> None:
    """B: VACUITY. A skip that never stops skipping is a deleted check.

    If this repository ever gains a Dockerfile, the build must be exercised
    again — otherwise the fix above is just a way of never testing the build.
    """
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    assert plan(tmp_path, docker_on_path=True) == "build"


def test_a_dockerfile_without_docker_still_warns(tmp_path: Path) -> None:
    """The pre-existing branch is preserved: buildable, but not tested here."""
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    assert plan(tmp_path, docker_on_path=False) == "no-docker"


def test_this_repository_takes_the_no_dockerfile_path_either_way() -> None:
    """The PASS message must be true of the real repo, not just of a tmp_path.

    Anchored to the actual tree: if someone adds a Dockerfile without settling
    which build mechanism wins, this fails and the contradiction gets decided
    deliberately rather than at minute six of a Cloud Build.
    """
    assert not (REPO / "Dockerfile").is_file(), "a Dockerfile appeared; deploy.sh uses buildpacks"
    assert plan(REPO, docker_on_path=True) == "no-dockerfile"
    assert plan(REPO, docker_on_path=False) == "no-dockerfile"


# ---------------------------------------------------------------------------
# Firestore: gcloud cannot do either of these
# ---------------------------------------------------------------------------


def test_gcloud_is_not_asked_to_deploy_rules_or_an_index_file() -> None:
    """Neither command exists. `infra/indexes.json` is Firebase-format."""
    assert "gcloud firestore rules" not in SCRIPT
    assert "gcloud firestore indexes create --index-file" not in SCRIPT.replace("\\\n", " ")
