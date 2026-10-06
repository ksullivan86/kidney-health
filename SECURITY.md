# Security policy

kidney-health stores health data for people with chronic kidney disease and type 1 diabetes, and a
wrong number can lead to an unsafe meal. Security reports are welcome and taken seriously.

## Reporting a vulnerability

**Please do not open a public issue for a vulnerability.** Report it privately through GitHub:
**Security → Advisories → Report a vulnerability** on this repository (private vulnerability
reporting). Include what you found, how to reproduce it, the version or image digest, and what an
attacker could do with it.

What to expect:

* an acknowledgement within 7 days;
* an assessment and, for a confirmed issue, a fix or mitigation plan within 30 days (sooner for
  anything that exposes health data, credentials or keys, or lets someone change targets or food
  values);
* credit in the advisory and release notes, unless you prefer otherwise.

In scope: the application (`app/`), the published container image, the deployment files in
`deploy/`, and the CI/release workflows in `.github/`. Reports about a dependency are welcome when
the app is actually affected; please also report them upstream.

Out of scope: findings that need an already-compromised host or admin account; denial of service
by sheer volume; the optional AI provider's own behaviour; missing hardening on a deployment that
removed the shipped defaults (see [`docs/security.md`](docs/security.md)).

This app gives no insulin or medication doses and never warns against treating a low blood sugar.
If you find a way to make it do either, report it as a security issue.

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x (latest minor) | Yes: security fixes are released as 0.3.x patch versions |
| 0.2.x and older | No: upgrade to 0.3 ([`docs/deployment.md`](docs/deployment.md#from-v02-to-v03)) |
| `:edge` (builds from `main`) | Best effort; for testing only |

Track the minor tag (`ghcr.io/ksullivan86/kidney-health:0.3`) or a digest you verified, not
`:latest` or `:edge`.

## Verifying the image before you run it

Release images are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) from
a hash-locked dependency set on digest-pinned base images, scanned with Grype before any tag moves,
and, once this repository is public, signed keylessly with cosign and published with GitHub-signed
SLSA build provenance and SBOM attestations. While the repository is private those signing steps
are skipped (GitHub offers attestations to private repositories only on Enterprise Cloud), so the
commands below succeed only for images released after it went public.

The script does all of it and prints the digest to pin:

```bash
scripts/verify-image.sh 0.3.0      # a release; or 0.3, edge, or sha256:<digest>
```

By hand (cosign 2.4 or later, a current `gh` with the `attestation` command, and `crane` or `skopeo`):

```bash
D=$(crane digest ghcr.io/ksullivan86/kidney-health:0.3.0)

# 1. Signature: made by this repository's release workflow, for a v* tag, via GitHub's OIDC issuer.
cosign verify "ghcr.io/ksullivan86/kidney-health@$D" \
  --certificate-identity-regexp '^https://github\.com/ksullivan86/kidney-health/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# 2. Build provenance and SBOM attestations, signed by the same workflow.
gh attestation verify "oci://ghcr.io/ksullivan86/kidney-health@$D" --repo ksullivan86/kidney-health \
  --signer-workflow ksullivan86/kidney-health/.github/workflows/release.yml
gh attestation verify "oci://ghcr.io/ksullivan86/kidney-health@$D" --repo ksullivan86/kidney-health \
  --signer-workflow ksullivan86/kidney-health/.github/workflows/release.yml \
  --predicate-type https://spdx.dev/Document/v2.3
```

Then deploy **by digest** (`ghcr.io/ksullivan86/kidney-health:0.3.0@sha256:…`), or track `:0.3`
with auto-update. Podman cannot enforce these signatures at pull time (its `policy.json` needs a
`subjectEmail`, and GitHub's certificates carry a workflow URI instead), so verify before you pin.
For `:edge` images, the certificate identity ends in `@refs/heads/main`.

## How the project protects its supply chain

* Python dependencies are pinned with SHA-256 hashes (`requirements.lock`) and installed as wheels
  only (`--require-hashes --only-binary=:all:`).
* Base images are pinned by digest; Dependabot proposes updates with a cooldown (security updates
  are never delayed).
* Every GitHub Action is pinned to a full commit SHA; workflows start with no permissions and grant
  each job only what it needs; scanners run without write access; zizmor and actionlint check the
  workflows on every push.
* Grype blocks a release on High or Critical vulnerabilities that have a fix, and a weekly scan
  re-checks the published image.

Details and the operator hardening guide: [`docs/security.md`](docs/security.md). Design and threat
model: [`docs/dev/research/01-rootless-and-security.md`](docs/dev/research/01-rootless-and-security.md).

## Repository settings (maintainers)

Keep these on: private vulnerability reporting; Actions → "Require actions to be pinned to a full
commit SHA"; workflow token read-only by default; rulesets requiring pull requests with green CI on
`main` and forbidding force-pushes or deletion of `v*` tags; immutable releases; the GHCR package's
"Manage Actions access" limited to this repository (and the package made public when the repository
goes public); optionally the `release` environment with required reviewers.
