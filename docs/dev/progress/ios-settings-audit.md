Status: in progress

Branch `audit/ios-settings-lifecycle`, main `cea3c94`. Keep PR unmerged.

Code review suspects: token replacement at the same server retains the former token's Health anchors/since;
late Test connection replies overwrite a removed/replaced setting and can apply the old server's 429 wait
to the new server. Sync rounds similarly keep captured credentials and may restore old anchors/status
after local removal or replacement.

Added four simulator tests before changing production code: new token resets position, unchanged token
keeps it, held connection success after removal, and held 429 after changing server. Native tests run in
the existing CI iOS simulator job because this workspace has no Swift/Xcode. Push a draft audit checkpoint,
verify baseline failures, then fix settings generation checks and sync transport guards; add failure-path tests,
docs and verify CI. No dependency or workflow changes planned.
