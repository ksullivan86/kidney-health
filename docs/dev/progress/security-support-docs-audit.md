Status: complete

Branch `docs/security-support-policy`, main `cea3c94`. Create an unmerged PR.

Confirmed SECURITY.md's support table called 0.10 the latest minor and sent older users only as far as 0.10,
while pyproject.toml and the latest published stable release are 0.22.2. CHANGELOG.md already states the
policy: security fixes go to the newest minor version. The table had drifted from that policy.

Use the latest-release link for the supported minor, and send older users to the deployment upgrade guide
with its backup/release-note instructions. The policy is unchanged and the table no longer needs a version
edit at every minor release. No application, dependency, release or clinical changes.

Verified: all 100 deployment/documentation checks pass; diff whitespace is clean; the upgrade anchor exists
and GitHub latest points to the published stable release. No new tests were needed for this documentation correction.
The PR is ready for review and must remain unmerged. Evidence: GitHub latest release v0.22.2, published 2026-11-06T05:06:19Z.
