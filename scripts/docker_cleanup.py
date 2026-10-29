"""Safely plan or perform small-platform Docker cleanup.

The default is read-only.  ``--confirm`` removes only exited containers from
the selected Compose project and old ``eat-agent`` images, while preserving
images used by running containers and the newest rollback images.  Volumes are
never removed.  BuildKit has no reliable Compose-project ownership metadata,
so confirmed cache cleanup is deliberately age-limited and never uses
``docker system prune -a``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]


def _run_docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], check=False, capture_output=True, text=True)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise subprocess.CalledProcessError(result.returncode, ["docker", *args], output=result.stdout, stderr=detail)
    return result.stdout.strip()


def _json_lines(output: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def _default_project_name() -> str:
    return os.environ.get("COMPOSE_PROJECT_NAME", ROOT_DIR.name)


def _project_containers(project_name: str) -> list[dict[str, Any]]:
    output = _run_docker(
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project_name}",
        "--format",
        "{{json .}}",
    )
    return _json_lines(output)


def _running_image_ids() -> set[str]:
    container_ids = _run_docker("ps", "-q").splitlines()
    image_ids: set[str] = set()
    for container_id in container_ids:
        image_id = _run_docker("inspect", "--format", "{{.Image}}", container_id, check=False).strip()
        if image_id:
            image_ids.add(image_id)
    return image_ids


def _project_images(image_repository: str) -> list[dict[str, Any]]:
    output = _run_docker(
        "image",
        "ls",
        "--filter",
        f"reference={image_repository}:*",
        "--format",
        "{{json .}}",
    )
    return _json_lines(output)


@dataclass(frozen=True)
class CleanupPlan:
    project_name: str
    stopped_containers: tuple[str, ...]
    removable_images: tuple[str, ...]
    preserved_images: tuple[str, ...]
    builder_cache_cleanup: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "stopped_containers": list(self.stopped_containers),
            "removable_images": list(self.removable_images),
            "preserved_images": list(self.preserved_images),
            "builder_cache_cleanup": self.builder_cache_cleanup,
            "volumes_removed": False,
        }


def build_plan(
    *,
    project_name: str,
    image_repository: str = "eat-agent",
    keep_images: int = 2,
    include_builder_cache: bool = True,
) -> CleanupPlan:
    if keep_images < 1:
        raise ValueError("keep_images 必须至少为 1")

    containers = _project_containers(project_name)
    stopped: list[str] = []
    for container in containers:
        status = str(container.get("Status", "")).lower()
        container_id = str(container.get("ID", ""))
        if container_id and (status.startswith("exited") or status.startswith("created") or status.startswith("dead")):
            stopped.append(container_id)

    running_image_ids = _running_image_ids()
    images = _project_images(image_repository)
    ordered_ids: list[str] = []
    for image in images:
        image_id = str(image.get("ID", ""))
        if image_id and image_id not in ordered_ids:
            ordered_ids.append(image_id)

    preserved = set(ordered_ids[:keep_images]) | running_image_ids
    removable = tuple(image_id for image_id in ordered_ids if image_id not in preserved)
    return CleanupPlan(
        project_name=project_name,
        stopped_containers=tuple(stopped),
        removable_images=removable,
        preserved_images=tuple(image_id for image_id in ordered_ids if image_id in preserved),
        builder_cache_cleanup=include_builder_cache,
    )


def execute_plan(plan: CleanupPlan, *, include_builder_cache: bool = True) -> None:
    if plan.stopped_containers:
        _run_docker("rm", *plan.stopped_containers)
    if plan.removable_images:
        # No -f: an image still referenced by a running or unknown container
        # must fail closed instead of being forcibly detached.
        _run_docker("image", "rm", *plan.removable_images)
    if include_builder_cache and plan.builder_cache_cleanup:
        # BuildKit cache is not project-labelled; keep this conservative and
        # only prune entries older than seven days.  Volumes are untouched.
        _run_docker("builder", "prune", "--force", "--filter", "until=168h")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or perform safe Docker cleanup")
    parser.add_argument("--confirm", action="store_true", help="perform the planned cleanup")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    parser.add_argument("--project-name", default=_default_project_name())
    parser.add_argument("--image-repository", default="eat-agent")
    parser.add_argument("--keep-images", type=int, default=2)
    parser.add_argument(
        "--no-builder-cache",
        action="store_true",
        help="do not prune the conservative seven-day-old BuildKit cache",
    )
    args = parser.parse_args(argv)

    try:
        plan = build_plan(
            project_name=args.project_name,
            image_repository=args.image_repository,
            keep_images=args.keep_images,
            include_builder_cache=not args.no_builder_cache,
        )
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        if not args.confirm:
            print("dry-run: 未执行删除；如确认计划无误，请追加 --confirm。")
            return 0
        execute_plan(plan, include_builder_cache=not args.no_builder_cache)
        print("cleanup completed")
        return 0
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or str(exc)
        print(f"docker cleanup failed: {type(exc).__name__}: {detail}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"docker cleanup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
