"""Deployment and supply-chain invariants (docs/dev/research/01-rootless-and-security.md §5, §7, §10).

Static checks over deploy/, .github/ and the security docs, standard library only, no network.
CI's "lint" job adds the tool-based checks (hadolint, actionlint, zizmor, kubeconform, compose
config, a YAML parse of every file); these tests keep the decisions from regressing in review.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
CONTAINERFILES = [REPO / "deploy" / "Containerfile", REPO / "deploy" / "Containerfile.debian"]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def uses_lines(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^\s*(?:-\s*)?uses:\s*(.+)$", text, re.M)]


def job_blocks(text: str) -> dict[str, str]:
    """Top-level jobs of a workflow as {job_id: text of its block} (two-space indented ids)."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\s*$", body, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


# --------------------------------------------------------------------------- workflows


def test_expected_workflows_exist():
    names = {p.name for p in WORKFLOWS}
    assert {"ci.yml", "release.yml", "codeql.yml", "scheduled-scan.yml"} <= names


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_full_commit_sha_with_a_version_comment(workflow):
    lines = uses_lines(workflow.read_text(encoding="utf-8"))
    assert lines, workflow.name
    for line in lines:
        if line.startswith("./"):
            continue
        m = re.match(r"^([\w.-]+/[\w./-]+)@(\S+)\s+#\s*(v\d[\w.\-]*)$", line)
        assert m, f"{workflow.name}: not '<owner/repo>@<sha> # vX.Y.Z': {line}"
        assert SHA40.match(m.group(2)), f"{workflow.name}: not a 40-hex commit SHA: {line}"


def test_each_action_uses_one_sha_and_one_version_everywhere():
    seen: dict[str, set[tuple[str, str]]] = {}
    for workflow in WORKFLOWS:
        for line in uses_lines(workflow.read_text(encoding="utf-8")):
            m = re.match(r"^([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@(\S+)\s+#\s*(\S+)$", line)
            if m:
                seen.setdefault(m.group(1), set()).add((m.group(2), m.group(3)))
    drift = {repo: pins for repo, pins in seen.items() if len(pins) > 1}
    assert not drift, drift


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_least_privilege_permissions(workflow):
    text = workflow.read_text(encoding="utf-8")
    assert re.search(r"^permissions: \{\}\s*$", text, re.M), "top-level permissions must be {}"
    for job, block in job_blocks(text).items():
        assert re.search(r"^    permissions:", block, re.M), f"{workflow.name}: job {job} has no permissions block"
        assert "write-all" not in block and "read-all" not in block


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_dangerous_triggers_caches_or_credentials(workflow):
    text = workflow.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "pull_request_target" not in code
    assert "workflow_run" not in code
    assert "type=gha" not in text, "no GitHub Actions cache in image builds (cache poisoning)"
    assert not re.search(r"^\s+cache:\s*(pip|npm|true)", text, re.M)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "actions/checkout@" in line:
            window = "\n".join(lines[i + 1 : i + 4])
            assert "persist-credentials: false" in window, f"{workflow.name}:{i + 1}: checkout keeps credentials"


def run_scripts(text: str) -> list[str]:
    """Every `run:` script of a workflow (block scalars and one-liners, with or without `- `)."""
    scripts: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(- )?run:\s*(.*)$", line)
        if not m:
            continue
        if not m.group(3).startswith(("|", ">")):
            scripts.append(m.group(3))
            continue
        key_indent = len(m.group(1)) + (2 if m.group(2) else 0)
        body = []
        for nxt in lines[i + 1 :]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= key_indent:
                break
            body.append(nxt)
        scripts.append("\n".join(body))
    return scripts


def test_run_script_parser_finds_injection():
    sample = "jobs:\n  x:\n    steps:\n      - run: |\n          echo ${{ github.event.issue.title }}\n        env:\n          A: b\n"
    assert run_scripts(sample) == ["          echo ${{ github.event.issue.title }}"]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_event_data_never_interpolated_into_shell(workflow):
    """Expressions reach `run:` scripts only through env variables (template injection, zizmor)."""
    scripts = run_scripts(workflow.read_text(encoding="utf-8"))
    assert scripts
    for script in scripts:
        assert "${{" not in script, f"{workflow.name}: expression inside a run script:\n{script}"


def test_ci_covers_the_required_checks():
    ci = read(".github/workflows/ci.yml")
    jobs = job_blocks(ci)
    assert {"test", "js-parity", "lint", "zizmor", "image"} <= set(jobs)
    assert re.search(r'python:\s*\["3\.12",\s*"3\.14"\]', jobs["test"])
    assert "--require-hashes" in jobs["test"] and "requirements-dev.lock" in jobs["test"]
    assert "node tests/js/run_vectors.mjs" in jobs["js-parity"]
    lint = jobs["lint"]
    for tool in ("actionlint", "hadolint", "kubeconform", "kustomize"):
        assert re.search(rf"{tool.upper()}_SHA256", ci), f"{tool} download is not SHA-256 pinned"
    assert "sha256sum --check" in lint
    assert "deploy/Containerfile deploy/Containerfile.debian" in lint
    assert "kubeconform -strict" in lint
    assert "yaml_parse.py" in lint and "docker compose" in lint
    image = jobs["image"]
    assert "push: false" in image and "load: true" in image
    assert "smoke-test.sh" in image
    assert "severity-cutoff: high" in image and "only-fixed: true" in image


def test_release_moves_tags_only_after_scan_and_gates_public_only_steps():
    rel = read(".github/workflows/release.yml")
    jobs = job_blocks(rel)
    assert list(jobs) == ["build", "scan", "publish"]
    assert "push-by-digest=true" in jobs["build"] and "provenance: mode=max" in jobs["build"]
    assert "sbom: true" in jobs["build"] and "linux/amd64,linux/arm64" in jobs["build"]
    # Tags (ARCHITECTURE.md v0.3 decision 7): main -> :edge + :sha-<short>; v* -> :X.Y.Z, :X.Y, :latest.
    assert "type=edge,branch=main" in rel
    assert "type=sha,prefix=sha-,format=short,enable=${{ github.ref == 'refs/heads/main' }}" in rel
    assert "type=semver,pattern={{version}}" in rel and "type=semver,pattern={{major}}.{{minor}}" in rel
    assert re.search(r"type=raw,value=latest,enable=\$\{\{ startsWith\(github\.ref, 'refs/tags/v'\)", rel)
    assert "latest=false" in rel
    scan = jobs["scan"]
    assert "needs: build" in scan and "GRYPE_PLATFORM" in scan
    assert "only-fixed: true" in scan and "severity-cutoff: high" in scan and "fail-build: true" in scan
    assert not re.search(r"^\s+(packages|contents|id-token|attestations|security-events): write", scan, re.M)
    publish = jobs["publish"]
    assert "needs: [build, scan]" in publish
    assert "PUBLIC: ${{ github.event.repository.private == false }}" in publish
    for marker in ("cosign sign", "actions/attest@", "anchore/sbom-action@"):
        for m in re.finditer(re.escape(marker), publish):
            step = publish[: m.start()].rsplit("- ", 1)[-1] + publish[m.start() : m.start() + 200]
            assert "if: env.PUBLIC == 'true'" in step, f"{marker} is not gated on a public repository"
    assert publish.count("create-storage-record: false") == 2
    assert publish.rindex("imagetools create") > publish.rindex("cosign sign")


def test_codeql_runs_only_for_public_repositories():
    codeql = read(".github/workflows/codeql.yml")
    assert "needs.visibility.outputs.public == 'true'" in codeql
    assert re.search(r"language: \[python, javascript-typescript, actions\]", codeql)
    assert "build-mode: none" in codeql


def test_dependabot_covers_pip_actions_and_base_images_with_cooldowns():
    text = read(".github/dependabot.yml")
    for ecosystem in ("pip", "github-actions", "docker"):
        assert f"package-ecosystem: {ecosystem}" in text
    assert text.count("cooldown:") == 3
    assert '"/deploy"' in text


# --------------------------------------------------------------------------- image


@pytest.mark.parametrize("path", CONTAINERFILES, ids=lambda p: p.name)
def test_containerfile_bases_are_digest_pinned_and_move_together(path):
    froms = re.findall(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.M)
    assert len(froms) == 3, froms  # builder, handbook (M3 placeholder), runtime
    for ref in froms:
        assert DIGEST.search(ref), f"{path.name}: FROM without @sha256 digest: {ref}"
    assert froms[0] == froms[1], "builder and handbook stages must use the identical FROM line"


def test_chainguard_builder_and_runtime_are_the_same_family():
    froms = re.findall(r"^FROM\s+(\S+)", read("deploy/Containerfile"), re.M)
    assert froms[0].startswith("cgr.dev/chainguard/python:latest-dev@")
    assert froms[2].startswith("cgr.dev/chainguard/python:latest@")


@pytest.mark.parametrize("path", CONTAINERFILES, ids=lambda p: p.name)
def test_containerfile_hardening(path):
    text = path.read_text(encoding="utf-8")
    runtime = text.rsplit("\nFROM ", 1)[1]
    # Dependencies: hash-locked wheels only, never resolved at build time.
    assert re.search(r"--no-deps --require-hashes --only-binary=:all: -r requirements\.lock", text)
    # Code and venv root-owned; only /data belongs to the app user (10001:0, 0770).
    assert re.search(r"COPY --from=builder\s+--chown=0:0\s+/opt/venv\s+/opt/venv", runtime)
    assert re.search(r"COPY --from=builder\s+--chown=0:0\s+/opt/app\s+/app", runtime)
    assert re.search(r"COPY --from=builder\s+--chown=10001:0\s+/out/data\s+/data", runtime)
    assert "chmod 0770 /out/data" in text and "go=rX" in text
    users = re.findall(r"^USER\s+(\S+)", runtime, re.M)
    assert users == ["10001:10001"]
    # Health check is the stdlib module in exec form (there is no shell in the image).
    assert 'HEALTHCHECK' in runtime and 'CMD ["python", "-m", "app.healthcheck"]' in runtime
    # uvicorn: the app applies X-Forwarded-* itself; connection cap (note 01 §10 S9).
    assert 'ENTRYPOINT ["python", "-m", "uvicorn", "app.main:app"]' in runtime
    cmd = re.search(r"^CMD (\[.*?\])\s*$", runtime.replace("\\\n", ""), re.M | re.S)
    assert cmd
    args = json.loads(cmd.group(1))
    assert "--no-proxy-headers" in args and "--no-server-header" in args
    assert args[args.index("--limit-concurrency") + 1] == "64"
    assert "forwarded-allow-ips" not in text
    assert 'org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"' in runtime
    assert "PLACEHOLDER" in text and "AS handbook" in text


def test_debian_fallback_removes_pip_and_setuid_bits():
    runtime = read("deploy/Containerfile.debian").rsplit("\nFROM ", 1)[1]
    assert "pip uninstall" in runtime and "-perm /6000" in runtime
    assert runtime.index("pip uninstall") < runtime.index("USER 10001:10001")


def test_dockerignore_is_an_allowlist_that_matches_the_copy_sources():
    lines = [ln.strip() for ln in read(".dockerignore").splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines[0] == "*"
    allowed = {ln[1:].rstrip("/") for ln in lines if ln.startswith("!")}
    assert {"app", "data/foods.json", "LICENSE", "requirements.lock"} <= allowed
    assert not any(a.startswith(("deploy", "tests", ".git", "docs")) for a in allowed)
    for path in CONTAINERFILES:
        for src in re.findall(r"^COPY (?!--from)(\S+)", path.read_text(encoding="utf-8"), re.M):
            assert src.rstrip("/") in allowed, f"{path.name} copies {src}, which .dockerignore excludes"


def test_hadolint_trusts_the_base_registries():
    text = read(".hadolint.yaml")
    trusted = re.search(r"trustedRegistries:\n((?:\s+- .+\n)+)", text).group(1)
    assert {"cgr.dev", "docker.io", "ghcr.io"} <= {t.strip("- \n") for t in trusted.splitlines()}
    assert "failure-threshold: warning" in text


def test_healthcheck_module_exists():
    assert (REPO / "app" / "healthcheck.py").is_file() and (REPO / "app" / "admin.py").is_file()


# --------------------------------------------------------------------------- runtime profiles


def quadlet(path: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    section = ""
    for raw in read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line.strip("[]")
            continue
        key, _, value = line.partition("=")
        values.setdefault(f"{section}.{key}", []).append(value)
    return values


def test_quadlet_unit_is_hardened():
    q = quadlet("deploy/quadlet/kidney-health.container")
    one = lambda key: q[f"Container.{key}"][0]  # noqa: E731
    assert one("Image") == "ghcr.io/ksullivan86/kidney-health:0.3"
    assert one("Network") == "pasta"
    assert one("PublishPort").startswith("127.0.0.1:")
    assert one("ReadOnly") == "true" and one("NoNewPrivileges") == "true"
    assert one("DropCapability").lower() == "all"
    assert one("User") == "10001" and one("Group") == "10001"
    assert int(one("PidsLimit")) <= 256
    assert "--memory=512m" in one("PodmanArgs")
    assert one("Tmpfs").startswith("/tmp:") and "noexec" in one("Tmpfs")
    assert one("Volume").endswith(":noexec,nosuid,nodev")
    assert "Container.UserNS" not in q, "default rootless mapping only; never keep-id"
    secret = one("Secret")
    assert "type=mount" in secret and "uid=10001" in secret and "mode=0400" in secret
    assert "SECRET_KEY_FILE=/run/secrets/secret_key" in q["Container.Environment"]
    # Exec form: a plain string would run through /bin/sh, which the image does not have.
    assert json.loads(one("HealthCmd")) == ["python", "-m", "app.healthcheck"]
    assert one("HealthOnFailure") == "kill"
    assert "Container.EnvironmentFile" not in q, "secrets come from Secret=, not an env file"


def test_compose_is_hardened_and_uses_file_secrets():
    text = read("deploy/compose.yaml")
    for needle in (
        "read_only: true",
        "cap_drop: [ALL]",
        "no-new-privileges:true",
        "pids_limit: 128",
        "mem_limit: 512m",
        'user: "10001:10001"',
        "/tmp:rw,noexec,nosuid,nodev",
        '"127.0.0.1:${HOST_PORT:-8000}:8000"',
        "SECRET_KEY_FILE: /run/secrets/secret_key",
        "file: ./secrets/secret_key",
        'test: ["CMD", "python", "-m", "app.healthcheck"]',
        "image: ghcr.io/ksullivan86/kidney-health:0.3",
    ):
        assert needle in text, needle
    active = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "keep-id" not in active and "USDA_API_KEY:" not in active and "APP_PASSWORD" not in active
    assert read("deploy/secrets/.gitignore").split("\n")[-3:-1] == ["*", "!.gitignore"]
    assert ".env" in read("deploy/.gitignore").splitlines()


def test_ollama_overlay_is_isolated():
    text = read("deploy/compose.ai-ollama.yaml")
    ollama = text.split("\n  ollama:\n", 1)[1]
    assert DIGEST.search(ollama)
    assert "cap_drop: [ALL]" in ollama and "no-new-privileges:true" in ollama and "pids_limit:" in ollama
    assert "ports:" not in "\n".join(ln for ln in ollama.splitlines() if not ln.lstrip().startswith("#"))
    assert "internal: true" in text


def test_scripts_are_executable_and_strict():
    for rel in ("scripts/verify-image.sh", "deploy/docker-rootless-run.sh", ".github/scripts/smoke-test.sh"):
        path = REPO / rel
        assert os.access(path, os.X_OK), f"{rel} is not executable"
        assert "set -euo pipefail" in path.read_text(encoding="utf-8")
    verify = read("scripts/verify-image.sh")
    assert "--certificate-oidc-issuer" in verify and "release\\.yml@" in verify
    assert "gh attestation verify" in verify
    docker_run = read("deploy/docker-rootless-run.sh")
    for flag in ("--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit", "--memory", "127.0.0.1:"):
        assert flag in docker_run
    assert "--health-cmd" not in docker_run.split("\ndocker run", 1)[1]


# --------------------------------------------------------------------------- Kubernetes


def test_k8s_namespace_enforces_restricted():
    text = read("deploy/k8s/namespace.yaml")
    for mode in ("enforce", "audit", "warn"):
        assert f"pod-security.kubernetes.io/{mode}: restricted" in text


def test_k8s_deployment_security_context():
    text = read("deploy/k8s/deployment.yaml")
    for needle in (
        "automountServiceAccountToken: false",
        "enableServiceLinks: false",
        "runAsNonRoot: true",
        "runAsUser: 10001",
        "allowPrivilegeEscalation: false",
        "readOnlyRootFilesystem: true",
        "privileged: false",
        "type: RuntimeDefault",
        "imagePullPolicy: IfNotPresent",
        "mountPath: /tmp",
        "medium: Memory",
        "defaultMode: 0440",
        "value: /run/secrets/kidney-health/secret_key",
        "type: Recreate",
    ):
        assert needle in text, needle
    assert re.search(r"drop:\n\s+- ALL", text)
    active = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "envFrom" not in active and "cpu: 500m" not in active


def test_k8s_kustomization_and_network_policy():
    kust = read("deploy/k8s/kustomization.yaml")
    resources = re.findall(r"^  - (\S+\.yaml)$", kust, re.M)
    assert {"networkpolicy.yaml", "httproute.yaml", "deployment.yaml", "namespace.yaml"} <= set(resources)
    assert not {"secret.example.yaml", "ingress.example.yaml", "cilium-networkpolicy.example.yaml"} & set(resources)
    assert not (REPO / "deploy/k8s/ingress.yaml").exists(), "ingress-nginx is retired: Ingress is only an example"
    assert 'newTag: "0.3"' in kust
    netpol = read("deploy/k8s/networkpolicy.yaml")
    assert "name: default-deny" in netpol and "podSelector: {}" in netpol
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert f"- {cidr}" in netpol
    assert "port: 443" in netpol and "k8s-app: kube-dns" in netpol
    assert "toFQDNs" in read("deploy/k8s/cilium-networkpolicy.example.yaml")


# --------------------------------------------------------------------------- docs


def test_docs_exist_and_follow_the_v03_decisions():
    for rel in ("SECURITY.md", "docs/security.md", "docs/https.md", "docs/deployment.md", "docs/network-allowlist.md"):
        assert (REPO / rel).is_file(), rel
    deployment = read("docs/deployment.md")
    assert "python -m app.admin backup" in deployment and "pre-v3.bak" in deployment
    assert "FIRST-RUN SETUP" in deployment
    for line in deployment.splitlines():
        if "keep-id" in line:
            assert re.search(r"(?i)\bnot\b|never|withdrawn|development|no longer", line), line
    allow = read("docs/network-allowlist.md")
    for host in ("api.nal.usda.gov", "world.openfoodfacts.org", "api.openai.com"):
        assert host in allow
    https = read("docs/https.md")
    assert "Certificate" in https and "Transparency" in https and "Certificate Trust Settings" in https
    for rel in ("deploy", "docs/deployment.md", "docs/security.md", "SECURITY.md"):
        target = REPO / rel
        files = target.rglob("*") if target.is_dir() else [target]
        for path in files:
            if path.is_file():
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "forwarded-allow-ips" in line:  # only ever mentioned as removed
                        assert re.search(r"(?i)gone|removed|no longer", line), f"{path}: {line}"


def test_every_yaml_file_parses():
    yaml = pytest.importorskip("yaml")  # the CI lint job installs it; the test job does not need it
    import importlib.util

    spec = importlib.util.spec_from_file_location("yaml_parse", REPO / ".github" / "scripts" / "yaml_parse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert yaml and module.main(REPO) == 0
