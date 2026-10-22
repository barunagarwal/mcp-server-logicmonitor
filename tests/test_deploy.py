# Description: Guards the container and manifest settings that drift silently when edited.
# Description: Digest-pinned images, hash-checked installs from uv.lock, a fixed service UID.

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

DEPLOY_DIR = Path(__file__).parent.parent / "deploy"
DOCKERFILE = DEPLOY_DIR / "Dockerfile"
COMPOSE = DEPLOY_DIR / "docker-compose.yml"
K8S = DEPLOY_DIR / "k8s" / "deployment.yaml"
SERVICE_UID = 10001

# A readable tag plus the digest that actually selects the image.
_PINNED_IMAGE_RE = re.compile(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}")
# release.yml tags images with metadata-action's semver {{version}}, which has no "v".
IMAGE = "ghcr.io/ryanmat/mcp-server-logicmonitor"


def _instructions() -> list[tuple[str, str]]:
    """Dockerfile instructions as (KEYWORD, arguments), continuations joined, comments dropped."""
    instructions: list[tuple[str, str]] = []
    pending = ""
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        keyword, _, args = (pending + line).partition(" ")
        instructions.append((keyword.upper(), args.strip()))
        pending = ""
    return instructions


def _stages() -> list[list[tuple[str, str]]]:
    stages: list[list[tuple[str, str]]] = []
    for keyword, args in _instructions():
        if keyword == "FROM":
            stages.append([])
        stages[-1].append((keyword, args))
    return stages


def _commands(stage: list[tuple[str, str]]) -> list[str]:
    """Each shell command a stage runs, split at &&."""
    return [command.strip() for kw, args in stage if kw == "RUN" for command in args.split("&&")]


def _deployment() -> dict[str, Any]:
    docs = yaml.safe_load_all(K8S.read_text())
    return next(doc for doc in docs if doc and doc["kind"] == "Deployment")


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text())


class TestImagePins:
    """R2.3: every image a build or compose pulls is selected by digest."""

    def test_every_image_the_dockerfile_pulls_is_digest_pinned(self) -> None:
        images = [args.split()[0] for kw, args in _instructions() if kw == "FROM"]
        images += [
            token.removeprefix("--from=")
            for kw, args in _instructions()
            if kw == "COPY"
            for token in args.split()
            if token.startswith("--from=") and "/" in token
        ]
        assert len(images) >= 2, images
        for image in images:
            assert _PINNED_IMAGE_RE.fullmatch(image), f"{image} is not pinned to a digest"

    def test_every_pulled_compose_image_is_digest_pinned(self) -> None:
        pulled = [s["image"] for s in _compose()["services"].values() if "build" not in s]
        assert pulled
        for image in pulled:
            assert _PINNED_IMAGE_RE.fullmatch(image), f"{image} is not pinned to a digest"


class TestLockedInstall:
    """R2.3: the runtime installs exactly what uv.lock pins, checked by hash."""

    def test_builder_exports_the_lock(self) -> None:
        builder = _stages()[0]
        assert any("uv.lock" in args.split() for kw, args in builder if kw == "COPY")
        exports = [c for c in _commands(builder) if c.startswith("uv export")]
        assert len(exports) == 1, _commands(builder)
        for flag in ("--frozen", "--no-dev", "--extra http"):
            assert flag in exports[0], f"uv export lacks {flag}"

    def test_runtime_installs_only_with_hashes_and_no_resolution(self) -> None:
        installs = [c for c in _commands(_stages()[-1]) if c.startswith("pip install")]
        assert installs
        assert all("--no-deps" in c.split() for c in installs), installs
        assert any("--require-hashes" in c.split() and "-r" in c.split() for c in installs)

    def test_runtime_stage_carries_no_uv_or_curl(self) -> None:
        runtime = " ".join(args for _, args in _stages()[-1])
        assert not re.search(r"\b(uv|curl)\b", runtime), runtime


class TestServiceUser:
    """R2.3: the image user has a fixed UID that runAsNonRoot and runAsUser can match."""

    def test_image_runs_as_the_fixed_uid(self) -> None:
        runtime = _stages()[-1]
        assert any(c.startswith(f"useradd --uid {SERVICE_UID} ") for c in _commands(runtime))
        users = [args for kw, args in runtime if kw == "USER"]
        assert users[-1:] == [str(SERVICE_UID)]

    def test_pod_runs_as_the_image_uid(self) -> None:
        security = _deployment()["spec"]["template"]["spec"]["securityContext"]
        assert security["runAsNonRoot"] is True
        assert security["runAsUser"] == SERVICE_UID
        assert security["runAsGroup"] == SERVICE_UID


class TestKubernetesManifest:
    """R2.3: a release tag the registry carries, and a writable /tmp on a read-only root."""

    def test_image_is_the_release_this_tree_builds(self) -> None:
        pyproject = tomllib.loads((DEPLOY_DIR.parent / "pyproject.toml").read_text())
        container = _deployment()["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == f"{IMAGE}:{pyproject['project']['version']}"

    def test_tmp_is_an_empty_dir_on_a_read_only_root(self) -> None:
        pod = _deployment()["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        mounts = {m["mountPath"]: m["name"] for m in container["volumeMounts"]}
        volumes = {v["name"]: v for v in pod["volumes"]}
        assert "emptyDir" in volumes[mounts["/tmp"]]
        env = {e["name"]: e.get("value") for e in container["env"]}
        assert env["TMPDIR"] == "/tmp"


class TestHealthcheck:
    """R2.3: the healthcheck runs on the image's Python, so the runtime needs no curl."""

    def test_image_and_compose_run_one_python_healthcheck(self) -> None:
        healthcheck = next(args for kw, args in _instructions() if kw == "HEALTHCHECK")
        exec_form = healthcheck.partition(" CMD ")[2]
        assert exec_form.startswith("["), f"HEALTHCHECK is not in exec form: {exec_form}"
        image_cmd = json.loads(exec_form)
        compose_test = _compose()["services"]["lm-mcp"]["healthcheck"]["test"]
        assert compose_test == ["CMD", *image_cmd]
        assert image_cmd[:2] == ["python", "-c"]
        assert "LM_HTTP_PORT" in image_cmd[2]


class TestHttpExposure:
    """R3.3: the deployments require the inbound token and allow the Host names they serve."""

    @staticmethod
    def _compose_env() -> dict[str, str]:
        entries = _compose()["services"]["lm-mcp"]["environment"]
        return dict(entry.split("=", 1) for entry in entries)

    def test_compose_requires_the_inbound_token(self) -> None:
        token = self._compose_env()["LM_HTTP_AUTH_TOKEN"]
        assert token.startswith("${LM_HTTP_AUTH_TOKEN:?"), token

    def test_compose_allows_the_tls_domain_as_host(self) -> None:
        assert self._compose_env()["LM_HTTP_ALLOWED_HOSTS"] == (
            "${LM_HTTP_ALLOWED_HOSTS:-${DOMAIN:-localhost}}"
        )

    def test_k8s_allows_the_service_name_as_host(self) -> None:
        docs = [doc for doc in yaml.safe_load_all(K8S.read_text()) if doc]
        service = next(doc for doc in docs if doc["kind"] == "Service")
        container = _deployment()["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e.get("value") for e in container["env"]}
        hosts = [h.strip() for h in env["LM_HTTP_ALLOWED_HOSTS"].split(",")]
        assert service["metadata"]["name"] in hosts
