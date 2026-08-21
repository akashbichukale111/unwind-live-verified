"""`make deploy-check` — everything that can be wrong BEFORE spending a deploy.

Runs with no credentials and no network. It exists because `infra/deploy.sh`
has never executed, and the cheapest way to find a broken deploy is to check its
preconditions rather than to watch it fail six minutes into a build.

It fails loudly and specifically. Every check names the file and the fix.

⚠ IT CANNOT PROVE THE DEPLOY WORKS. It proves the inputs are consistent. The
only thing that proves a deploy works is `make deploy-verify URL=...` against a
live service, which asserts the deployed thing COMPUTES and not merely renders.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Windows' default console codepage (cp1252) cannot encode the checkmarks
# and warning glyphs used below; Linux/CI's UTF-8 locale is unaffected, so
# this is a no-op there. Without it, this script crashes on Windows instead
# of reporting a preflight result.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

FAIL: list[str] = []
WARN: list[str] = []


def fail(check: str, problem: str, fix: str) -> None:
    FAIL.append(f"{check}\n      problem: {problem}\n      fix:     {fix}")


def warn(check: str, note: str) -> None:
    WARN.append(f"{check}: {note}")


def ok(check: str, detail: str = "") -> None:
    print(f"  PASS  {check}" + (f"  ({detail})" if detail else ""))


def container_build_plan(repo: Path, docker_on_path: bool) -> str:
    """What check #11 should do: `no-dockerfile`, `no-docker`, or `build`.

    ⚠ THIS REPOSITORY HAS NO DOCKERFILE ON PURPOSE. `infra/deploy.sh` runs
    `gcloud run deploy --source .`, which builds with buildpacks from the
    `Procfile`. Running `docker build` here asserted a build mechanism the
    deployment does not use, so the preflight failed on a correct repository.

    Pure, so the vacuity test can drive every branch without a Docker daemon.
    """
    if not (repo / "Dockerfile").is_file():
        return "no-dockerfile"
    if not docker_on_path:
        return "no-docker"
    return "build"


def gcloudignore_patterns(repo: Path) -> list[str]:
    """The ACTIVE exclusion patterns, ignoring comments and blanks.

    A plain substring search over the file text is wrong twice over: the file
    documents what it deliberately KEEPS, so `".python-version" in text` matched
    the prose explaining that .python-version must never be excluded. That is
    the third time this preflight has cried wolf at its own documentation.
    """
    path = repo / ".gcloudignore"
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def python_pin_satisfies(pin: str, requires: str) -> bool:
    """Does the `.python-version` pin fall inside `requires-python`?

    ⚠ THIS PAIR IS THE FAILED BUILD. `.python-version` decides which interpreter
    Cloud Build installs; `requires-python` decides whether pip will then accept
    the project on it. Agreeing separately is not enough -- they must agree with
    EACH OTHER, and build 89b74d60 is what disagreement costs.

    Deliberately small: handles the `>=`/`>`/`<=`/`<` clauses this project uses
    rather than pulling `packaging` in, because the preflight must run on a bare
    interpreter with no dependencies installed.
    """

    def parts(text: str) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", text)[:3])

    got = parts(pin)
    if not got:
        return False
    for clause in (c.strip() for c in requires.split(",") if c.strip()):
        found = re.match(r"(>=|<=|==|!=|>|<)\s*(.+)", clause)
        if not found:
            continue
        op, want = found.group(1), parts(found.group(2))
        if not want:
            continue
        # Compare on the digits both sides actually state: `3.13` vs `>=3.12`
        # must compare as (3,13) >= (3,12), not (3,13) >= (3,12,0).
        width = min(len(got), len(want))
        left, right = got[:width], want[:width]
        if op == ">=" and not left >= right:
            return False
        if op == ">" and not left > right:
            return False
        if op == "<=" and not left <= right:
            return False
        if op == "<" and not left < right:
            return False
        if op == "==" and left != right:
            return False
        if op == "!=" and left == right:
            return False
    return True


def main() -> int:
    print("=" * 70)
    print("UNWIND — deploy preflight (no credentials required)")
    print("=" * 70)

    deploy = REPO / "infra" / "deploy.sh"
    script = deploy.read_text(encoding="utf-8") if deploy.is_file() else ""

    # ---- 1. the script exists and parses -------------------------------
    if not script:
        fail("deploy.sh present", "infra/deploy.sh is missing", "restore it from git")
    else:
        # Piped over stdin, not passed as a path argument: which POSIX
        # mount convention (`/c/...` vs `/mnt/c/...`) a given `bash.exe`
        # expects for a Windows path varies by install and cannot be
        # guessed reliably, but `bash -n` reading from stdin needs no path
        # translation at all -- and it is exactly as portable on Linux.
        #
        # `input` is raw bytes, not `text=True`: a text-mode pipe write on
        # Windows translates `\n` to `os.linesep` (`\r\n`), which turns
        # every `\`-continued line in the script into a syntax error the
        # instant that `\r` lands between the backslash and the newline it
        # was supposed to escape. Bytes in, bytes out, decoded by hand.
        result = subprocess.run(
            ["bash", "-n"], input=script.encode("utf-8"), capture_output=True, check=False
        )
        if result.returncode != 0:
            fail(
                "deploy.sh parses",
                result.stderr.decode("utf-8", errors="replace").strip(),
                "fix the shell syntax",
            )
        else:
            ok("deploy.sh parses")

    # ---- 2. ⚠ region vs Vertex location --------------------------------
    # The defect this check exists for: `global` is a valid VERTEX location and
    # is NOT a valid Cloud Run region. Passing one where the other belongs is
    # the single most likely way the first real deploy dies.
    from lib.config import VERTEX_LOCATION

    run_region = os.environ.get("UNWIND_RUN_REGION", "us-central1")
    if run_region == "global":
        fail(
            "Cloud Run region is a real region",
            "UNWIND_RUN_REGION=global — Cloud Run has no 'global' region",
            "unset it or set a region such as us-central1; Vertex stays 'global'",
        )
    else:
        ok("Cloud Run region is a real region", run_region)

    if VERTEX_LOCATION != "global":
        warn(
            "Vertex location",
            f"lib/config.py pins {VERTEX_LOCATION!r}, but the verified live run used "
            "'global'. Confirm this is intended.",
        )
    else:
        ok("Vertex location matches the verified live run", VERTEX_LOCATION)

    if script and "--region" in script and "UNWIND_RUN_REGION" not in script:
        fail(
            "deploy.sh separates region from Vertex location",
            "deploy.sh derives --region from the Vertex location",
            "use UNWIND_RUN_REGION for Cloud Run and UNWIND_VERTEX_LOCATION for Vertex",
        )
    elif script:
        ok("deploy.sh separates region from Vertex location")

    # ---- 3. the deployed artifact is the FastAPI app, not the ADK UI ----
    # Match an INVOCATION, not a mention: deploy.sh explains in a comment why it
    # does not use `adk deploy`, and a plain substring check flagged that prose
    # as the very defect it was warning about. Look for a line that actually
    # runs it -- not indented under a comment marker.
    invokes_adk = any(
        line.strip().startswith("adk deploy")
        for line in script.splitlines()
        if not line.lstrip().startswith("#")
    )
    if invokes_adk:
        fail(
            "deploys the product surface",
            "deploy.sh uses `adk deploy`, which serves the ADK API server / dev UI "
            "and would not serve web/static at all",
            "use `gcloud run deploy --source .` against services/api/main.py",
        )
    elif script and "gcloud run deploy" in script:
        ok("deploys the product surface", "gcloud run deploy --source .")

    # ---- 4. buildpack entrypoint ---------------------------------------
    procfile = REPO / "Procfile"
    if not procfile.is_file():
        fail(
            "Procfile present",
            "gcloud run deploy --source . uses buildpacks and needs an entrypoint",
            "create a Procfile with: web: uvicorn services.api.main:app "
            "--host 0.0.0.0 --port ${PORT:-8080}",
        )
    else:
        body = procfile.read_text(encoding="utf-8")
        if "services.api.main:app" not in body:
            fail(
                "Procfile serves the right app",
                f"Procfile does not reference services.api.main:app: {body.strip()!r}",
                "point it at services.api.main:app",
            )
        elif "0.0.0.0" not in body:
            fail(
                "Procfile binds 0.0.0.0",
                "Cloud Run requires binding 0.0.0.0, not 127.0.0.1",
                "use --host 0.0.0.0",
            )
        elif "PORT" not in body:
            fail(
                "Procfile honours $PORT",
                "Cloud Run injects $PORT and the container must listen on it",
                "use --port ${PORT:-8080}",
            )
        else:
            ok("Procfile binds 0.0.0.0 and honours $PORT")

    # ---- 5. one origin: the UI is actually served by the API ------------
    api = (REPO / "services" / "api" / "main.py").read_text(encoding="utf-8")
    static_dir = REPO / "web" / "static"
    needed = ["index.html", "app.js", "style.css"]
    missing = [f for f in needed if not (static_dir / f).is_file()]
    if missing:
        fail("UI files present", f"missing from web/static: {missing}", "restore them")
    elif "StaticFiles" not in api or "FileResponse" not in api:
        fail(
            "API serves the UI from one origin",
            "services/api/main.py does not mount web/static",
            "mount StaticFiles and serve index.html at /",
        )
    else:
        ok("API serves the UI from one origin", "3 static files + FastAPI")

    if (REPO / "web" / "package.json").is_file() and "next" in (
        REPO / "web" / "package.json"
    ).read_text(encoding="utf-8"):
        # ⚠ .gcloudignore, NOT .dockerignore. `gcloud run deploy --source .`
        # never reads .dockerignore, so checking that file was false assurance:
        # it passed while web/app was being uploaded on every deploy.
        if not (REPO / ".gcloudignore").is_file():
            fail(
                "the dead Next.js skeleton is excluded from the build",
                "web/app exists and there is no .gcloudignore, so gcloud falls back "
                "to .gitignore and uploads it -- buildpacks may then detect a Node app",
                "add .gcloudignore excluding web/app/",
            )
        else:
            ignore = (REPO / ".gcloudignore").read_text(encoding="utf-8")
            if "web/app" not in ignore:
                fail(
                    "the dead Next.js skeleton is excluded from the build",
                    ".gcloudignore does not exclude web/app/",
                    "add 'web/app/' to .gcloudignore",
                )
            else:
                ok("the dead Next.js skeleton is excluded from the build")

    # ---- 5b. ⚠ nothing in the UPLOAD may divert the buildpack ------------
    # The build that failed was fed the working directory, not the repository.
    # Google's Python buildpack treats poetry.lock and uv.lock as
    # high-precedence package-manager markers and switches away from
    # pip-from-pyproject the moment it sees one.
    patterns = gcloudignore_patterns(REPO)
    for marker in ("poetry.lock", "uv.lock", "Pipfile"):
        present = (REPO / marker).is_file()
        excluded = marker in patterns
        if present and not excluded:
            fail(
                "no foreign package manager reaches the build",
                f"{marker} is in the working directory and .gcloudignore does not "
                f"exclude it, so Cloud Build will receive it",
                f"delete {marker} (this project uses PEP 621 + hatchling), or exclude it",
            )
            break
    else:
        ok("no foreign package manager reaches the build", "pip reads pyproject.toml")

    # ---- 5c. ⚠ THE INTERPRETER. Both halves, or the build is a lottery. ---
    # Left unpinned, the buildpack takes the newest Python it supports, so the
    # deployed runtime moves under you whenever Google's default moves. Build
    # 89b74d60 died of exactly that: the default had passed the `<3.13` ceiling
    # in requires-python and pip refused the project outright.
    #
    # Two facts must therefore hold together, and neither is sufficient alone:
    #   (i)  .python-version pins the interpreter, so the deploy is reproducible
    #   (ii) requires-python ADMITS that pin, so pip does not refuse it
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    spec = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
    requires = spec.group(1) if spec else ""

    pin_file = REPO / ".python-version"
    if not pin_file.is_file():
        fail(
            "the buildpack's Python is pinned",
            "no .python-version, so the buildpack picks the newest Python it supports "
            "and the deployed runtime changes without a commit",
            "add a .python-version at the repo root (e.g. 3.13)",
        )
    else:
        pin = pin_file.read_text(encoding="utf-8").strip()
        if ".python-version" in patterns:
            fail(
                "the buildpack's Python is pinned",
                ".gcloudignore excludes .python-version, so the pin never reaches the build",
                "remove .python-version from .gcloudignore",
            )
        elif not python_pin_satisfies(pin, requires):
            fail(
                "the pinned Python satisfies requires-python",
                f".python-version pins {pin!r} but pyproject requires {requires!r}; "
                "pip will refuse the project on the interpreter the buildpack installs",
                "widen requires-python or move the pin inside it",
            )
        else:
            ok("the buildpack's Python is pinned", f".python-version {pin} ⊆ {requires}")

    # ---- 6. required env vars are named, not assumed --------------------
    for var in ("UNWIND_PROJECT_ID",):
        if script and var not in script:
            fail(f"{var} handled", f"deploy.sh never reads {var}", "read and validate it")
    if script and "Refusing to guess a project" in script:
        ok("refuses to guess a project")

    # ---- 7. IAM roles are least-privilege and named ---------------------
    expected_roles = {"roles/aiplatform.user", "roles/datastore.user", "roles/pubsub.publisher"}
    found = set(re.findall(r"roles/[a-zA-Z.]+", script))
    if not expected_roles <= found:
        fail(
            "runtime roles listed",
            f"deploy.sh is missing {sorted(expected_roles - found)}",
            "bind exactly those three roles to the runtime service account",
        )
    else:
        ok("runtime roles listed", ", ".join(sorted(expected_roles)))
    over = {r for r in found if r in {"roles/owner", "roles/editor"}}
    if over:
        fail("no over-broad roles", f"deploy.sh grants {sorted(over)}", "remove them")
    else:
        ok("no over-broad roles (no Owner/Editor)")

    # ---- 8. API enablement -----------------------------------------------
    needed_apis = {
        "aiplatform.googleapis.com",
        "firestore.googleapis.com",
        "pubsub.googleapis.com",
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
    }
    missing_apis = {a for a in needed_apis if a not in script}
    if missing_apis:
        fail(
            "APIs enabled",
            f"deploy.sh does not enable {sorted(missing_apis)}",
            "add them to the gcloud services enable list",
        )
    else:
        ok("APIs enabled", f"{len(needed_apis)} services")

    # ---- 9. Pub/Sub wire names match lib/pubsub.py ------------------------
    from lib.config import ALL_TOPICS

    wire = {t.replace(".", "-") for t in ALL_TOPICS}
    missing_topics = {t for t in wire if t not in script}
    if missing_topics:
        fail(
            "Pub/Sub topics match lib/config.py",
            f"deploy.sh does not create {sorted(missing_topics)}",
            "topic ids are the config names with dots replaced by hyphens",
        )
    else:
        ok("Pub/Sub topics match lib/config.py", f"{len(wire)} topics")

    # ---- 10. Firestore: gcloud cannot deploy rules or an index FILE -------
    # `gcloud firestore indexes create --index-file=` and `gcloud firestore
    # rules release` are not gcloud commands. infra/indexes.json is in Firebase
    # format, so the Firebase CLI is the correct tool.
    if "gcloud firestore rules" in script:
        fail(
            "Firestore rules use the right tool",
            "`gcloud firestore rules release` is not a gcloud command",
            "deploy rules with the Firebase CLI: firebase deploy --only firestore:rules",
        )
    else:
        ok("Firestore rules are not deployed by gcloud")

    if "gcloud firestore indexes create --index-file" in script.replace("\\\n", " "):
        fail(
            "Firestore indexes use the right tool",
            "`gcloud firestore indexes create --index-file=` is not a gcloud flag",
            "deploy indexes with: firebase deploy --only firestore:indexes",
        )
    else:
        ok("Firestore indexes are not deployed by gcloud")

    idx = REPO / "infra" / "indexes.json"
    if idx.is_file():
        import json

        try:
            parsed = json.loads(
                "\n".join(line for line in idx.read_text(encoding="utf-8").splitlines())
            )
        except json.JSONDecodeError as exc:
            fail("indexes.json parses", str(exc), "fix the JSON")
        else:
            if "indexes" not in parsed:
                fail("indexes.json shape", "no top-level 'indexes' key", "use Firebase format")
            else:
                ok("indexes.json parses", f"{len(parsed['indexes'])} composite indexes")

    # ---- 11. container builds locally, if there is a container to build ---
    plan = container_build_plan(REPO, bool(shutil.which("docker")))
    if plan == "no-dockerfile":
        ok("container build", "no Dockerfile — buildpacks + Procfile, as designed")
    elif plan == "build":
        print("  ....  docker found; attempting a local build (this is slow)")
        build = subprocess.run(
            ["docker", "build", "-q", "-t", "unwind-preflight", "."],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        stderr = build.stderr.strip()
        daemon_down = (
            "docker.sock" in stderr
            or "Cannot connect to the Docker daemon" in stderr
            or "daemon is running" in stderr
        )
        if build.returncode != 0 and daemon_down:
            # The binary exists but nothing is listening. That is an environment
            # fact, not a defect in this repository, and failing on it would
            # train everyone to ignore the preflight.
            warn(
                "container build",
                "docker binary present but the daemon is not running, so the "
                "build was NOT tested. Cloud Build will be the first to try it.",
            )
        elif build.returncode != 0:
            fail(
                "container builds locally",
                stderr[-400:],
                "fix the build before spending a Cloud Build minute",
            )
        else:
            ok("container builds locally")
    else:
        warn(
            "container build",
            "docker not available here, so the build was NOT tested. Cloud Build "
            "will be the first thing to try it.",
        )

    # ---- 12. the app imports without credentials --------------------------
    env = {**os.environ, "UNWIND_VERTEX_DISABLED": "1", "UNWIND_OTEL_CONSOLE": "0"}
    imp = subprocess.run(
        [sys.executable, "-c", "import services.api.main; print('ok')"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if imp.returncode != 0 or "ok" not in imp.stdout:
        fail(
            "the app imports with no credentials",
            imp.stderr.strip()[-400:],
            "the container starts before any credential exists; imports must not need one",
        )
    else:
        ok("the app imports with no credentials")

    # ---- report -----------------------------------------------------------
    print("")
    for note in WARN:
        print(f"  WARN  {note}")
    if FAIL:
        print("")
        print("=" * 70, file=sys.stderr)
        print(f"DEPLOY PREFLIGHT FAILED — {len(FAIL)} problem(s)", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for problem in FAIL:
            print(f"  FAIL  {problem}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Nothing was deployed.", file=sys.stderr)
        return 1

    print("")
    print("Preflight passed. This checks INPUTS, not the deploy itself.")
    print("Deploy with ./infra/deploy.sh, then prove it computes:")
    print("    make deploy-verify URL=https://...")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
