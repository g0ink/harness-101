"""Preflight check: can this machine run the lab, and what is missing?

Run: ``./bin/doctor.sh``

Checks, in the order a newcomer hits them:

1. Python version and the two dependencies
2. a token (from the environment or ``.env``)
3. the model server: reachable, accepting the token, and offering the model we ask for
4. a one-line verdict with the exact next command

It never raises on a failed check: a newcomer needs the diagnosis, not a traceback.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from harness.llm import BASE_URL, ENV_FILE, MODEL, MissingToken, load_token  # noqa: E402

OK = "  ok   "
WARN = " warn  "
FAIL = " fail  "

problems: list[str] = []
hints: list[str] = []


def report(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def describe(token: str) -> str:
    """Never echo the token itself -- this output ends up in bug reports."""
    return f"{len(token)} characters"


def check_python() -> None:
    version = sys.version_info
    report(OK if version >= (3, 11) else FAIL, f"python {version.major}.{version.minor}.{version.micro}")
    if version < (3, 11):
        problems.append("python 3.11+ is required")
        hints.append("create the environment: ./bin/setup.sh")


def check_dependencies() -> None:
    for module in ("openai", "yaml"):
        try:
            __import__(module)
            report(OK, f"dependency {module} importable")
        except ImportError:
            report(FAIL, f"dependency {module} missing")
            problems.append(f"{module} is not installed")
            hints.append("install dependencies: ./bin/setup.sh")


def check_token() -> str | None:
    try:
        token = load_token()
    except MissingToken:
        report(FAIL, "no LM_API_TOKEN found")
        problems.append("no token")
        hints.append(f"copy .env.example to .env and fill LM_API_TOKEN (see {ENV_FILE.name})")
        return None
    source = "environment" if os.environ.get("LM_API_TOKEN") else ENV_FILE.name
    report(OK, f"token found in {source} ({describe(token)})")
    return token


def fetch_models(token: str) -> list[str] | None:
    request = urllib.request.Request(
        f"{BASE_URL.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            report(FAIL, f"{BASE_URL} rejected the token (HTTP {error.code})")
            problems.append("token rejected")
            hints.append("create a new token: LM Studio -> Developer -> Server Settings -> Manage Tokens")
        else:
            report(FAIL, f"{BASE_URL} returned HTTP {error.code}")
            problems.append("server error")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        report(FAIL, f"cannot reach {BASE_URL} ({error})")
        problems.append("server unreachable")
        hints.append("start the server: lms server start  (or point HARNESS_BASE_URL elsewhere)")
        return None

    models = [item.get("id", "") for item in payload.get("data", [])]
    report(OK, f"{BASE_URL} reachable, {len(models)} model(s) available")
    return models


def check_model(models: list[str]) -> None:
    if not models:
        report(WARN, "server is up but has no model loaded")
        hints.append(f"load a model, then set HARNESS_MODEL (currently {MODEL!r})")
        return
    if MODEL in models:
        report(OK, f"model {MODEL!r} is available")
        return
    report(WARN, f"model {MODEL!r} is not loaded; server offers: {', '.join(models[:5])}")
    hints.append(f"set HARNESS_MODEL={models[0]} in .env, or load {MODEL!r}")


def main() -> int:
    print(f"lab root : {LAB}")
    print(f"base url : {BASE_URL}")
    print(f"model    : {MODEL}\n")

    check_python()
    check_dependencies()
    token = check_token()
    if token:
        models = fetch_models(token)
        if models is not None:
            check_model(models)

    print()
    if not problems:
        print("ready. next: ./bin/ask.sh \"In corpus/memory.md, what does compaction do?\"")
        print("no model yet? the offline suites still run: ./bin/selftest.sh && ./bin/adversarial.sh")
        return 0

    print("not ready:")
    for problem in dict.fromkeys(problems):
        print(f"  - {problem}")
    for hint in dict.fromkeys(hints):
        print(f"  -> {hint}")
    print("\nthe offline suites need no model and no token: ./bin/selftest.sh && ./bin/adversarial.sh")
    return 1


if __name__ == "__main__":
    sys.exit(main())
