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
    assert re.search(r"^    needs: \[test, lint, handbook\]$", image, re.M)



def test_the_image_smoke_test_checks_the_ca_store_with_the_apps_own_self_check():
    """Note 04 R12: outbound https (USDA, Open Food Facts, AI) needs CA certificates in the image. The smoke test runs
    the app's start-up self-check inside the built image (as UID 10001) and fails when it finds none, so a base image
    change that drops ca-certificates cannot ship. One source of truth: it imports the app's check, never a copy."""
    smoke = read(".github/scripts/smoke-test.sh")
    block = smoke[smoke.index("from app.ai.transport import ca_store_problem"):]
    assert "sys.exit(1 if problem else 0)" in block.split("' ||", 1)[0]
    assert "FAIL: no CA certificates" in block and 'echo "ok   CA certificates for outbound TLS"' in block

def test_ci_builds_and_checks_the_handbook():
    """Note 08 §4.8: the handbook job (the image jobs need it) and the Zensical canary."""
    jobs = job_blocks(read(".github/workflows/ci.yml"))
    hb = jobs["handbook"]
    assert "--require-hashes" in hb and "-r handbook/requirements.lock" in hb and "-r requirements-dev.lock" in hb
    assert "scripts/build_handbook.py --check" in hb
    assert 'mkdocs" build --strict -d "$RUNNER_TEMP/learn"' in hb and "HANDBOOK_SITE_URL: http://localhost/learn/" in hb
    assert 'handbook/tools/check_links.py "$RUNNER_TEMP/learn" --allow /' in hb
    assert "--noconftest" in hb and "tests/test_handbook_content.py" in hb
    assert 'HANDBOOK_BUILT_SITE="$RUNNER_TEMP/learn"' in hb and "tests/test_learn_links.py" in hb
    assert "-r tools/e2e/requirements.lock" in hb and "tools/e2e/learn.py" in hb
    assert "playwright install" not in hb  # the runner's Chrome, never a browser download
    assert "PLACEHOLDER" not in read(".github/workflows/ci.yml")
    canary = jobs["handbook-zensical"]
    assert "continue-on-error: true" in canary
    assert "-r handbook/requirements-zensical.lock" in canary and "zensical build -f mkdocs.yml -s" in canary
    assert re.search(r"^zensical==\S+ \\$", read("handbook/requirements-zensical.lock"), re.M)


def test_handbook_pages_is_opt_in_and_least_privilege():
    wf = read(".github/workflows/handbook-pages.yml")
    assert re.search(r"^permissions: \{\}$", wf, re.M)
    jobs = job_blocks(wf)
    assert list(jobs) == ["build", "deploy"]
    assert "if: vars.HANDBOOK_PAGES == 'true'" in jobs["build"]
    assert re.search(r"permissions:\n      contents: read\n", jobs["build"])
    assert "--require-hashes" in jobs["build"] and "mkdocs build --strict -f mkdocs.pages.yml" in jobs["build"]
    assert "scripts/build_handbook.py --check" in jobs["build"]
    assert "needs: build" in jobs["deploy"] and "name: github-pages" in jobs["deploy"]
    assert re.findall(r"^      (\S+): write", jobs["deploy"], re.M) == ["pages", "id-token"]
    assert "cancel-in-progress: false" in wf and "branches: [main]" in wf
    for action in ("actions/configure-pages@", "actions/upload-pages-artifact@", "actions/deploy-pages@"):
        assert action in wf


def test_handbook_links_are_checked_weekly_and_reported_in_one_issue():
    wf = read(".github/workflows/handbook-links.yml")
    assert re.search(r"^permissions: \{\}$", wf, re.M)
    job = job_blocks(wf)["links"]
    assert re.findall(r"^      (\S+): (read|write)", job, re.M) == [("contents", "read"), ("issues", "write")]
    assert "lycheeverse/lychee-action@" in job and "--accept 200..=299,403,429" in job
    assert "handbook/sources.yml" in job and "handbook-links" in job
    assert re.search(r"- cron: ", wf)


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
    # the owner can hold :latest on the v0.2 digest while auto-updating v0.2 hosts move (M1 review)
    assert "vars.HOLD_LATEST != 'true' }}" in rel
    for doc in ("CHANGELOG.md", "README.md", "docs/deployment.md"):
        text = read(doc)
        assert "AutoUpdate=registry" in text and "podman-auto-update.timer" in text, doc
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
    # Dependabot only reads *.txt / *.in requirement files: pointing it at the *.lock directories makes
    # the job fail on the requirements*.txt shims and leaves the locks stale (M1 review).
    pip_block = text.split("package-ecosystem: pip", 1)[1].split("package-ecosystem:", 1)[0]
    assert re.findall(r'^\s+- "([^"]+)"', pip_block, re.M) == ["/.github"]
    assert "refresh-locks.yml" in text


def test_hash_locks_are_refreshed_weekly_with_a_cooldown_by_pull_request():
    wf = read(".github/workflows/refresh-locks.yml")
    assert re.search(r"^\s+- cron: ", wf, re.M) and "workflow_dispatch:" in wf
    assert 'PIP_UPLOADED_PRIOR_TO="P${COOLDOWN_DAYS}D" scripts/lock.sh --upgrade' in wf
    assert "default: \"7\"" in wf and "inputs.cooldown_days || '7'" in wf
    assert "gh pr create" in wf
    jobs = job_blocks(wf)
    assert set(jobs) == {"refresh"}
    assert re.search(r"contents: write", jobs["refresh"]) and re.search(r"pull-requests: write", jobs["refresh"])
    lock = read("scripts/lock.sh")
    assert "handbook/requirements.lock handbook/requirements.in" in lock
    for name in ("handbook/requirements-zensical", "tools/e2e/requirements"):
        assert lock.count(f"{name}.lock {name}.in") == 2, name  # local and container branches
        assert f"{name}.lock" in wf
    assert re.search(r'PIP_VERSION="2[6-9]\.', lock)  # pip >= 26.0 understands --uploaded-prior-to
    assert "-e PIP_UPLOADED_PRIOR_TO" in lock


# --------------------------------------------------------------------------- image


@pytest.mark.parametrize("path", CONTAINERFILES, ids=lambda p: p.name)
def test_containerfile_bases_are_digest_pinned_and_move_together(path):
    froms = re.findall(r"^FROM\s+(\S+)", path.read_text(encoding="utf-8"), re.M)
    assert len(froms) == 3, froms  # builder, handbook, runtime
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
    # /data arrives as a directory *entry* of the staging tree so it keeps mode 0770 (a plain
    # `COPY /out/data /data` would create /data as 0755 and break arbitrary-UID, GID-0 runs)
    assert re.search(r"COPY --from=builder\s+--chown=10001:0\s+/out/rootfs/\s+/\s*$", runtime, re.M)
    assert "chmod 0770 /out/rootfs/data" in text and "go=rX" in text
    assert not re.search(r"COPY[^\n]*/out/(rootfs/)?data\s+/data", runtime)
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
    # SPDX expression: the code (LICENSE) and the handbook text in /app/learn (handbook/LICENSE).
    # hadolint cannot parse SPDX expressions, so .hadolint.yaml checks it as text and this pins it.
    assert f'org.opencontainers.image.licenses="{IMAGE_LICENCES}"' in runtime
    assert "PLACEHOLDER" not in text


IMAGE_LICENCES = "PolyForm-Noncommercial-1.0.0 AND CC-BY-NC-SA-4.0"


@pytest.mark.parametrize("path", CONTAINERFILES, ids=lambda p: p.name)
def test_handbook_is_built_in_a_throwaway_stage_and_copied_read_only(path):
    """Note 08 §4.7: hash-locked toolchain in its own stage; only the built site reaches /app/learn."""
    text = path.read_text(encoding="utf-8")
    stages = re.split(r"^FROM ", text, flags=re.M)
    handbook = next(s for s in stages if re.match(r"\S+ AS handbook\s*$", s.splitlines()[0]))
    runtime = stages[-1]
    assert "COPY handbook/requirements.lock /tmp/handbook.lock" in handbook
    assert re.search(r"--no-deps --require-hashes --only-binary=:all: -r /tmp/handbook\.lock", handbook)
    assert "COPY handbook/ /src/handbook/" in handbook
    assert "HANDBOOK_SITE_URL=http://localhost/learn/" in handbook and "HANDBOOK_APP_LINK=/" in handbook
    assert "NO_MKDOCS_2_WARNING=true" in handbook
    assert "mkdocs build --strict -d /out/learn" in handbook
    assert "-name '*.map'" in handbook and "test -f /out/learn/index.html" in handbook
    assert "chmod -R u=rwX,go=rX /out/learn" in handbook
    # The runtime gets the plain files, root-owned, and nothing of the toolchain.
    assert re.search(r"^COPY --from=handbook\s+--chown=0:0\s+/out/learn\s+/app/learn\s*$", runtime, re.M)
    assert len(re.findall(r"--from=handbook", runtime)) == 1
    assert "/opt/hb" not in runtime and "mkdocs" not in runtime
    assert "HANDBOOK_DIR=/app/learn" in runtime


def test_release_labels_match_the_containerfile():
    rel = read(".github/workflows/release.yml")
    assert f"org.opencontainers.image.licenses={IMAGE_LICENCES}\n" in rel


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
    excluded = {ln.rstrip("/") for ln in lines[1:] if not ln.startswith("!")}
    for path in CONTAINERFILES:
        for src in re.findall(r"^COPY (?!--from)(\S+)", path.read_text(encoding="utf-8"), re.M):
            src = src.rstrip("/")
            inside = any(src == a or src.startswith(a + "/") for a in allowed)
            assert inside and src not in excluded, f"{path.name} copies {src}, which .dockerignore excludes"
    # The handbook stage builds from handbook/; a local build output must never reach the context.
    assert {"handbook/site", "handbook/.cache"} <= excluded


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
    assert not {"secret.example.yaml", "ingress.example.yaml", "cilium-networkpolicy.example.yaml", "restore-pod.example.yaml"} & set(resources)
    assert not (REPO / "deploy/k8s/ingress.yaml").exists(), "ingress-nginx is retired: Ingress is only an example"
    assert 'newTag: "0.3"' in kust
    netpol = read("deploy/k8s/networkpolicy.yaml")
    assert "name: default-deny" in netpol and "podSelector: {}" in netpol
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"):
        assert f"- {cidr}" in netpol
    assert "port: 443" in netpol and "k8s-app: kube-dns" in netpol
    cilium = read("deploy/k8s/cilium-networkpolicy.example.yaml")
    assert "toFQDNs" in cilium
    # Cilium's Gateway/Ingress has the reserved "ingress" identity, which no namespaceSelector matches
    assert re.search(r"fromEntities:\n\s+- ingress", cilium) and 'port: "8000"' in cilium
    assert "cilium-networkpolicy.example.yaml" in netpol and "fromEntities" in netpol


def test_k8s_restore_pod_is_restricted_and_documented():
    """The image has no tar (kubectl cp cannot work), so the guide streams the backup into this pod."""
    pod = read("deploy/k8s/restore-pod.example.yaml")
    for needle in ("runAsNonRoot: true", "runAsUser: 10001", "allowPrivilegeEscalation: false", "readOnlyRootFilesystem: true",
                   "claimName: kidney-health-data", "mountPath: /tmp", "type: RuntimeDefault", "automountServiceAccountToken: false"):
        assert needle in pod, needle
    assert re.search(r"drop:\n\s+- ALL", pod)
    guide = read("docs/deployment.md")
    assert "restore-pod.example.yaml" in guide and "kubectl -n kidney-health exec -i kidney-health-restore" in guide
    assert "kubectl cp" not in guide.replace("so `kubectl cp` cannot", "")


def test_restore_procedure_works_on_read_only_mounts():
    """Docs restore steps: the one-liner opens the backup immutable, the key check gets the secret, and
    sessions are revoked on the volume (a :ro mount cannot be written)."""
    text = read("docs/deployment.md")
    assert "mode=ro&immutable=1" in text
    assert "SECRET_KEY_FILE=/run/secrets/secret_key" in text
    assert "revoke-sessions --all" in text
    assert not re.search(r"restore-check[^\n]*--revoke-sessions[^\n]*/restore/", text)
    # The handbook explains the steps and links to the commands instead of repeating them.
    assert f"{DOCS_URL}/docs/deployment.md#backups-and-restore" in read("handbook/docs/self-hosting/backups.md")


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
    import yaml  # requirements-dev.lock installs PyYAML (the CI lint job installs it from .github/requirements-lint.txt)

    import importlib.util

    spec = importlib.util.spec_from_file_location("yaml_parse", REPO / ".github" / "scripts" / "yaml_parse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert yaml and module.main(REPO) == 0


# --------------------------------------------------------------------------- M1 review: deploy docs


def test_rootless_docker_docs_trust_the_gateway_for_a_same_host_proxy():
    """Under rootless Docker a same-host HTTPS proxy arrives from the RootlessKit gateway; keeping the
    loopback default makes the app ignore X-Forwarded-Proto and refuse a second account."""
    security = read("docs/security.md")
    row = next(line for line in security.splitlines() if line.startswith("| Rootless **Docker**"))
    assert "same host" in row and "https_required" in row and "127.0.0.1" in row
    assert "TRUSTED_PROXY_SECRET_FILE" in row and "compose.caddy.yaml" in row
    for doc in ("docs/deployment.md", "docs/https.md", "handbook/docs/self-hosting/docker-rootless.md"):
        assert "172.17.0.1" in read(doc), doc
    assert f"{DOCS_URL}/docs/deployment.md#rootless-docker" in read("handbook/docs/self-hosting/docker-rootless.md")
    assert "https_required` although the browser shows HTTPS" in read("docs/deployment.md")
    run = read("deploy/docker-rootless-run.sh")
    assert 'TRUSTED_PROXIES="${TRUSTED_PROXIES:-127.0.0.1,::1}"' in run
    assert '--env "TRUSTED_PROXIES=${TRUSTED_PROXIES}"' in run
    # re-running the script (e.g. to pin a verified digest) replaces the container instead of failing
    head, tail = run.split("\ndocker run", 1)
    assert "docker stop kidney-health" in head and "docker rm kidney-health" in head


def test_compose_docs_require_podman_compose_1_5():
    for doc in ("deploy/compose.yaml", "docs/deployment.md"):
        text = read(doc)
        assert re.search(r"podman-compose (must be )?1\.5\.0 or later|podman-compose 1\.5\.0 or later", text), doc
        assert "chcon -t container_file_t deploy/secrets/*" in text, doc
    page = read("handbook/docs/self-hosting/podman-rootless.md")
    assert "podman-compose (1.5.0 or later)" in page
    assert f"{DOCS_URL}/docs/deployment.md#compose-podman-compose-or-docker-compose" in page


# --------------------------------------------------------------------------- handbook self-hosting pages

DOCS_URL = "https://github.com/ksullivan86/kidney-health/blob/main"
SELF_HOSTING = sorted((REPO / "handbook" / "docs" / "self-hosting").glob("*.md"))


def github_anchors(rel: str) -> set[str]:
    """Heading anchors GitHub generates for a Markdown file (code blocks skipped, duplicates numbered)."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    fence = False
    for line in read(rel).splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not m:
            continue
        slug = re.sub(r"[^\w\- ]", "", m.group(1).replace("`", "").strip().lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchors.add(slug if n == 0 else f"{slug}-{n}")
    return anchors


def test_handbook_links_to_the_canonical_docs_resolve():
    """docs/deployment.md, docs/security.md, docs/https.md and SECURITY.md are canonical; the handbook
    links to their sections, and every link must name a file and a heading that exist."""
    pattern = re.compile(re.escape(DOCS_URL) + r"/([\w./-]+\.md)(?:#([\w-]+))?")
    checked = 0
    for page in sorted((REPO / "handbook" / "docs").rglob("*.md")):
        for rel, anchor in pattern.findall(page.read_text(encoding="utf-8")):
            assert (REPO / rel).is_file(), f"{page.relative_to(REPO)} links to {rel}, which does not exist"
            if anchor:
                assert anchor in github_anchors(rel), f"{page.relative_to(REPO)}: {rel} has no heading #{anchor}"
            checked += 1
    assert checked >= 20, checked


@pytest.mark.parametrize("page", [p for p in SELF_HOSTING if p.name != "building-the-handbook.md"], ids=lambda p: p.name)
def test_self_hosting_pages_link_to_commands_instead_of_copying_them(page):
    text = page.read_text(encoding="utf-8")
    shells = re.findall(r"^\s*```(?:bash|sh|shell|console|zsh)\s*$", text, re.M)
    assert not shells, f"{page.name}: shell command blocks belong in docs/deployment.md, docs/security.md or docs/https.md"
    for command in ("podman run", "podman exec", "kubectl apply", "kubectl -n", "systemctl --user", "docker run",
                    "podman unshare chown", "loginctl enable-linger"):
        assert command not in text, f"{page.name} repeats `{command}`; link to the canonical guide instead"


def test_verify_image_requires_cosign_3():
    verify = read("scripts/verify-image.sh")
    assert "cosign >= 3.0" in verify and '-lt 3' in verify
    assert "cosign 3.0 or later" in read("SECURITY.md") and "cosign 2.4 or later" not in read("SECURITY.md")


def test_podman_debug_command_overrides_the_python_entrypoint():
    guide = read("docs/deployment.md")
    assert "--entrypoint sh --user 10001:0 --volumes-from kidney-health" in guide
    assert "latest-dev sh`" not in guide
