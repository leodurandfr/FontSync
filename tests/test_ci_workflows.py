"""CI guards: no image is published unless the test suite passed (M-22)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name} is not a mapping"
    return data


def _all_run_steps(workflow: dict[str, Any]) -> str:
    runs = []
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []) or []:
            runs.append(str(step.get("run", "")))
    return "\n".join(runs)


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), triggers
    return triggers


def test_build_and_push_needs_test() -> None:
    publish = _load("docker-publish.yml")
    jobs = publish["jobs"]
    needs = jobs["build-and-push"].get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert "test" in needs
    assert jobs["test"].get("uses") == "./.github/workflows/ci.yml"


def test_ci_runs_pytest_and_frontend_build() -> None:
    ci = _load("ci.yml")
    runs = _all_run_steps(ci)
    assert "pytest" in runs
    assert "ruff check" in runs
    assert "npm run build" in runs
    assert "npm test" in runs
    triggers = _triggers(ci)
    assert {"push", "pull_request", "workflow_call"} <= set(triggers)


def test_publish_has_concurrency() -> None:
    publish = _load("docker-publish.yml")
    concurrency = publish.get("concurrency")
    assert isinstance(concurrency, dict)
    assert concurrency.get("group")
    # A tag build is never cancelled; only a newer manual dispatch replaces one.
    assert "workflow_dispatch" in str(concurrency.get("cancel-in-progress"))


def _metadata_step(publish: dict[str, Any]) -> dict[str, Any]:
    for step in publish["jobs"]["build-and-push"]["steps"]:
        if str(step.get("uses", "")).startswith("docker/metadata-action"):
            return step
    raise AssertionError("no docker/metadata-action step")


def test_metadata_emits_sha_tag() -> None:
    tags = str(_metadata_step(_load("docker-publish.yml"))["with"]["tags"])
    assert "type=sha" in tags
    assert "prefix=sha-" in tags


def test_latest_not_auto() -> None:
    step = _metadata_step(_load("docker-publish.yml"))
    flavor = str(step["with"].get("flavor", ""))
    assert "latest=auto" not in flavor
    assert "latest=false" in flavor
    # `latest` only moves for the highest non-prerelease v* tag.
    assert "is_highest" in str(step["with"]["tags"])


def _all_uses() -> list[tuple[str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            if "uses" in job:
                found.append((path.name, str(job["uses"])))
            for step in job.get("steps", []) or []:
                if "uses" in step:
                    found.append((path.name, str(step["uses"])))
    return found


def test_all_actions_pinned_by_sha() -> None:
    import re

    unpinned = [
        f"{name}: {uses}"
        for name, uses in _all_uses()
        if not uses.startswith("./") and not re.search(r"@[0-9a-f]{40}$", uses)
    ]
    assert not unpinned, "actions not pinned by full commit SHA:\n" + "\n".join(
        unpinned
    )


def test_dependabot_covers_ecosystems() -> None:
    config = yaml.safe_load(
        (WORKFLOWS.parent / "dependabot.yml").read_text(encoding="utf-8")
    )
    ecosystems = {u["package-ecosystem"]: u for u in config["updates"]}
    assert {"pip", "npm", "github-actions", "docker"} <= set(ecosystems)
    assert ecosystems["npm"]["directory"] == "/frontend"
    for update in config["updates"]:
        assert update["schedule"]["interval"] == "weekly"
