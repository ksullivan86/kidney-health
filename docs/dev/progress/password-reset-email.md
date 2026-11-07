# Progress: password reset by email (role: password-reset-email)

Status: in progress

Branch: worktree-agent-a2f49c0ffcd44efdb (origin/main + origin/claude/adoring-sagan-th5swr, fast-forwarded). Do not push.

## Plan
1. m034: users.email, users.email_confirmed_at, email_tokens table; unique index on confirmed email.
2. config: EmailEnv (EMAIL_ENABLED, SMTP_*), refusals at start-up.
3. app/mail.py: message text, smtplib send in a deadline thread.
4. app/auth/email_api.py: /api/me/email (GET, PUT, DELETE), /api/auth/email/confirm, /api/auth/forgot, /api/admin/email/test.
5. UI: sign-in "Forgot your password?", Settings → Account block, admin about + test button, confirm-email screen.
6. Demo twin (mock/auth.js).
7. Tests (fake SMTP server in tests/fake_smtp.py).
8. Docs.

## Decisions
- Confirmation tokens live in their own table `email_tokens` (auth_tokens.purpose has a CHECK that only allows setup/invite/reset,
  and changing it needs a table rebuild). Each token is bound to the address it was sent to.
- Unique index covers confirmed addresses only, so nobody can block another person's address by typing it unconfirmed.
- Forgot: per-IP limit answers 429; the per-account limit is silent (same 202), so it reveals nothing.
- Forgot sends in the background (does not wait for SMTP), so the answer time does not depend on the account.

## Done
(nothing yet)
