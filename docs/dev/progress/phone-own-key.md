Status: in progress

# phone-own-key: the person's own AI key on the iPhone app (owner, 2026-11-25)

Base: `git reset --keep worktree-agent-a140ec927b7fd74a2` (release branch + Ask on the phone). Avoid profile.js, settings
registry, gateway BODY_KEYS, ServerAPI.swift settings keys (helper `height-units` edits those).

## Decisions
* Providers: only the server's `user_allowed` presets (app/ai/presets.py): OpenAI (api.openai.com/v1), OpenRouter
  (openrouter.ai/api/v1), Nous Portal (inference-api.nousresearch.com/v1). All speak OpenAI Chat Completions, so the app has one
  wire format. Hosts and quirks are fixed in Swift (OwnAI.swift); a pytest checks they equal presets.py.
* The app builds the request from ai-prompts.json `own_key` (system prompt, template, schema) so the page can only name a task and
  hand its data; the app refuses any task not on its list and photos unless the switch is on.
* Order (js/mock/ai.js): server (D2, unchanged) → own key (features it can do) → iPhone's model → no AI. device_only skips both.
* Name/birth: the phone has no privacy filter twin; the data for these tasks has no name or birth field, and the page refuses to
  send a request to the own key whose body contains the profile's name or birth month (falls through to the iPhone's model).
* Ask stays server-only (its tools read the log on the server).

## Done

## Next

## Commands
