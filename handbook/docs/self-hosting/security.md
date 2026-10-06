---
title: Security
description: "The hardening summary, verifying images, and serving the handbook from its own origin."
slug: security
audience: [self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-05
sources: [NOTE01, NOTE08]
---

# Security

!!! info "This page is being written"
    It will cover the points below. Until it is finished, use them to prepare questions for your care team.

## What this page will teach

<!-- Writers: copied from docs/dev/research/08-handbook-site.md §5. Turn each item into page text using
     handbook/templates/page.md, cite sources.yml ids, then delete this list. -->

- [ ] The hardening summary, verifying images.
- [ ] **Serving `/learn` from its own origin** with a reverse proxy, so the handbook's relaxed CSP (inline-script hashes, no Trusted Types) never shares an origin with the API (note 08 §4.6).

## Sources

- [Design note 01][NOTE01]
- [Design note 08][NOTE08]
