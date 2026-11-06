Status: complete

Branch `audit/ios-settings-lifecycle`, main `cea3c94`. Keep PR unmerged.

Confirmed: token replacement at the same server retains the former token's Health anchors/since;
late Test connection replies overwrite a removed/replaced setting and can apply the old server's 429 wait
to the new server. Sync rounds similarly keep captured credentials and may restore old anchors/status
after local removal or replacement.

Four simulator tests were committed before changing production code: new token resets position, unchanged token
keeps it, held connection success after removal, and held 429 after changing server. CI on `8d4553f`
confirmed exactly three assertion failures; the unchanged-token test passed. Job:
https://github.com/ksullivan86/kidney-health/actions/runs/42177940442/job/127760662633

Fixed settings generations, sync checks before/after Health reads and transport replies, and a guarded transport
that stops later requests in a batch. A changed server/token resets anchors/since/last-send summary and wait;
identical credentials keep their position. Also enforce the existing documented pause after a refused token,
resuming on explicit settings save or a successful connection check. `HealthReading` permits deterministic
simulator tests without HealthKit permissions; no new Health types or dependencies.

Added tests for removal/replacement during a held sync, removal during a held Health read, stopping between
two batch requests, and refused-token pause/resume. Bounded test waits fail rather than hanging a simulator.
17 Python iOS policy checks pass. Native tests run in the existing CI simulator job because this workspace
has no Swift/Xcode. The fix at `ddb467e` passed the simulator build/tests, Swift package, Python 3.12/3.14/3.15,
Node parity, lint, handbook, CodeQL and image checks in CI run 42179418391. Local iOS policy tests (17),
generated pages and strict handbook also pass. No compiler warning beyond the simulator destination note.

PR https://github.com/ksullivan86/kidney-health/pull/156 is ready for review and remains unmerged.
No new Health types, dependencies, workflow changes or clinical rules.
