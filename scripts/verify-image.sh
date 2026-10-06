#!/usr/bin/env bash
# Verify a published kidney-health image before you deploy it, then pin it by digest.
# Spec: docs/dev/research/01-rootless-and-security.md §3.6, §5.4. Background: SECURITY.md.
#
#   scripts/verify-image.sh 0.3.0          # a release tag (signed by release.yml on refs/tags/v*)
#   scripts/verify-image.sh 0.3            # the minor tag you track
#   scripts/verify-image.sh edge           # the main branch build (signed on refs/heads/main)
#   scripts/verify-image.sh sha256:<hex>   # a digest you already have
#
# Checks, in order (any failure exits non-zero and nothing is printed as "verified"):
#   1. resolves the tag to the image INDEX digest (crane, skopeo or docker buildx; tags can move,
#      digests cannot);
#   2. cosign: a keyless Sigstore signature whose certificate names THIS repository's release.yml
#      workflow, on a v* tag (or main for :edge), issued by GitHub Actions' OIDC provider;
#   3. gh: GitHub's SLSA build-provenance attestation, and the SPDX SBOM attestation, both signed
#      by release.yml in this repository;
#   4. prints the in-index buildx provenance summary when docker buildx is available.
# Signatures and attestations exist only once the repository is public (release.yml gates them).
#
# Needs: cosign >= 3.0 (release.yml signs with cosign 3: a Sigstore bundle stored as an OCI 1.1
# referrer, which cosign 2.4/2.5 cannot find), a current gh with `gh attestation`, and one of crane, skopeo or
# docker buildx. Private package: log in first (docker/podman login ghcr.io, and gh auth login).
# Override for a fork: IMAGE_REPO=ghcr.io/you/kidney-health GITHUB_REPO=you/kidney-health
set -euo pipefail

IMAGE_REPO="${IMAGE_REPO:-ghcr.io/ksullivan86/kidney-health}"
GITHUB_REPO="${GITHUB_REPO:-ksullivan86/kidney-health}"
OIDC_ISSUER="https://token.actions.githubusercontent.com"
WORKFLOW_PATH=".github/workflows/release.yml"

usage() { sed -n '2,23p' "$0" >&2; exit 2; }
[ $# -eq 1 ] || usage
ref="$1"
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing tool: $1 ($2)" >&2; exit 2; }; }
need cosign "https://docs.sigstore.dev/cosign/system_config/installation/"
need gh "https://cli.github.com/"

# cosign 2.x looks for the legacy sha256-<digest>.sig tag and reports "no signatures found" for the
# bundle-format signatures release.yml makes, which would look like a forged image. Refuse it.
cosign_version="$(cosign version 2>/dev/null | sed -n 's/^GitVersion:[[:space:]]*v\{0,1\}\([0-9][0-9]*\)\..*/\1/p' | head -n 1)"
if [ -z "$cosign_version" ] || [ "$cosign_version" -lt 3 ]; then
  echo "cosign 3.0 or later is needed (found: $(cosign version 2>/dev/null | sed -n 's/^GitVersion:[[:space:]]*//p' | head -n 1))." >&2
  echo "Older versions cannot see the bundle-format signatures this project publishes." >&2
  exit 2
fi

# Which git refs may have produced this image (the signing certificate records the ref).
repo_re="${GITHUB_REPO//./\\.}"
case "$ref" in
  edge)        ref_re='refs/heads/main' ;;
  sha256:*)    ref_re='refs/(heads/main|tags/v[0-9][^@]*)' ;;
  latest|[0-9]*) ref_re='refs/tags/v[0-9][^@]*' ;;
  *) echo "unexpected reference '$ref' (use a version, 'edge' or a sha256: digest)" >&2; exit 2 ;;
esac
identity_re="^https://github\.com/${repo_re}/\.github/workflows/release\.yml@${ref_re}\$"

# 1. Digest of the image index.
if [[ "$ref" == sha256:* ]]; then
  digest="$ref"
elif command -v crane >/dev/null 2>&1; then
  digest="$(crane digest "${IMAGE_REPO}:${ref}")"
elif command -v skopeo >/dev/null 2>&1; then
  digest="$(skopeo inspect --raw "docker://${IMAGE_REPO}:${ref}" | sha256sum | awk '{print "sha256:" $1}')"
elif command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
  digest="$(docker buildx imagetools inspect "${IMAGE_REPO}:${ref}" --format '{{json .Manifest.Digest}}' | tr -d '"')"
else
  echo "need crane, skopeo or docker buildx to resolve the tag to a digest" >&2
  exit 2
fi
if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "could not resolve ${IMAGE_REPO}:${ref} to a digest (got '${digest}')" >&2
  exit 1
fi
image="${IMAGE_REPO}@${digest}"
echo "==> ${IMAGE_REPO}:${ref} is ${digest}"

# 2. Keyless signature from this repository's release workflow.
echo "==> cosign verify (identity ${identity_re})"
cosign verify "$image" \
  --certificate-identity-regexp "$identity_re" \
  --certificate-oidc-issuer "$OIDC_ISSUER" \
  --output text >/dev/null
echo "    signature OK"

# 3. GitHub attestations: SLSA provenance and the SPDX SBOM, both from release.yml.
echo "==> gh attestation verify (provenance)"
gh attestation verify "oci://${image}" --repo "$GITHUB_REPO" \
  --signer-workflow "${GITHUB_REPO}/${WORKFLOW_PATH}" \
  --predicate-type "https://slsa.dev/provenance/v1" >/dev/null
echo "    provenance OK"
echo "==> gh attestation verify (SBOM)"
gh attestation verify "oci://${image}" --repo "$GITHUB_REPO" \
  --signer-workflow "${GITHUB_REPO}/${WORKFLOW_PATH}" \
  --predicate-type "https://spdx.dev/Document/v2.3" >/dev/null
echo "    SBOM OK"

# 4. Informational: what buildx recorded in the index (platforms, base images, build args).
if command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
  echo "==> in-index provenance (buildx, informational)"
  docker buildx imagetools inspect "$image" --format '{{range $p, $v := .Provenance}}provenance recorded for {{$p}}{{"\n"}}{{end}}' 2>/dev/null || true
fi

# The tag is kept next to the digest for humans; the digest is what the engine pulls.
pinned="${IMAGE_REPO}:${ref}@${digest}"
[[ "$ref" == sha256:* ]] && pinned="$image"
cat <<EOF

verified: ${image}
Pin this digest in your deployment, for example:
  Quadlet:     Image=${pinned}
  compose:     image: ${pinned}
  kustomize:   kustomize edit set image ${IMAGE_REPO}=${pinned}
EOF
