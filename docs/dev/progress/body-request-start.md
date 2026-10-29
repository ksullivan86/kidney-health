Status: complete

Base: 547bb6e, combined current main 6fa43ab, Claude 289c2b3 and the tested reliability/recipe
serving branches. Latest branches checked before this work. Own branch fix/body-request-start.
No PR, deployment or environment publication.

Remaining parent-loader gap: body.js clears as soon as called, but Today calls it only AFTER the
food log resolves or fails. Old weight/BP rows can therefore remain under a new date while food
waits. Symptoms already loads at the start of Today. Start body the same way and remove the two
post-food calls. Keep its own ordering/retry behavior and API unchanged.

Fix: start weight/BP with the other Today reads, before awaiting food; remove post-render/error
restarts. Body and Symptoms header comments now describe the actual independent loading order.

Validation: 9 body-loader Node cases pass (the two new parent-loader cases failed before the fix),
and all 8 Symptoms-loader cases pass. Focused pytest: 673 passed, existing handbook warning only.
Full body Chromium walk: 366 passed. New cases hold BOTH the food request and weight request,
verify clearing immediately, switch back and release the old replies; all three real passes pass.
Report /tmp/kidney-body-independent-20261029/report.json. Parity, syntax, demo build, Ruff and
diff checks pass. Ready on fix/body-request-start. No PR/deployment.

The prior 6551-test batch result is for 12523c2, not this follow-up; current integration will
get its own fixed-snapshot verification including Claude's later changes and recipe servings.
