---
title: Optional AI
description: "What the optional AI features do, what is sent and to whom, how you give and take back consent, and the safety limits that always apply."
slug: ai
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE04, NOTE03, NOTE06, OPENAI-DATA, OPENROUTER-ROUTING, OLLAMA-OAI, HERMES-API, FRIDOLFSSON25, A26-6]
---

# Optional AI

!!! note "Off until you choose it"
    AI features are **off** unless your admin switches them on, and then off for you until you opt in.

The app works fully without AI. AI is an extra layer that can re-rank meal ideas, turn a sentence such
as "2 eggs, toast with butter, tea" into food searches, or read the numbers from a photo of a label
([design note 04][NOTE04]). The app's own rules check every AI answer before you see it.

## What AI can and cannot do here

| AI can | AI cannot |
|---|---|
| Pick and order meal ideas, using **only** foods the rules already allowed | Invent a food or a nutrient number: every number comes from the app's food list |
| Split "describe a meal" text into search words; you pick each match | Save anything: you tap **Add to plan** and the normal rules run again |
| Copy printed numbers from a label photo into a draft food you check, marked "from photo" | Estimate nutrients from a plate photo: it gives food **names** and a rough weight; the numbers come from your food list |
| Name foods it sees on a plate photo | Chat freely, answer medical questions, or read your lab results |

### Safety rules that always apply

- **No insulin, no doses.** AI never gives insulin doses, ratios, correction factors, pump or CGM
  settings, or medicine advice. Carbohydrate is shown only in grams ([design note 04][NOTE04]).
- **Lows never go to AI.** If you type words like "low", "hypo" or "shaky", the app shows its own
  "Treating a low" card and does not call AI ([ADA 2026][A26-6], section 6).
- **Red-flag symptoms never go to AI.** If you type "chest pain", "can't breathe", "confused", "faint" or
  "seizure", the app shows a **Get help now** card (call your emergency number; treat a low first)
  instead.
- **AI never overrides a warning.** An idea that would push your day over a limit is dropped.
- **No free text from AI.** The reasons you read under an idea ("Low in potassium; fits your
  dinner carbohydrate goal") are written by the app's maintainers, not by the AI.
- Every AI card says **"AI idea · provider · model · checked against your targets · not medical
  advice"**.

!!! danger "Call 911 (or your local emergency number)"
    For chest pain, trouble breathing, a low you cannot treat by mouth, confusion or a seizure, call for
    help. Do not ask the app. See [Get help now](../get-help-now.md).

## What is sent, and what is not

| Sent to the AI provider | Never sent |
|---|---|
| Your CKD stage, dialysis type and diabetes type | Your name, user name or email |
| Your targets and today's totals and status | Your weight, height, exact age or dates |
| Up to 40 candidate foods with their numbers | Entry notes, other people's data |
| Your food preferences, if you wrote any (up to 200 characters) | Anything when you have not opted in |
| Age in 10-year bands and sex, **only if you tick "share age and sex"** | |
| A label or plate photo (photo features only), with location and camera data removed | |

Before anything is sent the first time, a consent sheet shows the **provider**, the **server address**
it goes to, a line about how that provider handles data, and the **exact text** that will be sent. Every
AI button also has **What will be sent?**, which shows the same thing without sending
([design note 04][NOTE04]).

## Who the providers are

Your admin chooses which providers are offered. Typical ones:

| Provider | Where your data goes | Data line shown in the app |
|---|---|---|
| **Ollama** or another model your admin runs at home | your admin's computer ([Ollama][OLLAMA-OAI]) | "runs on your admin's hardware; your admin can read what is sent" |
| **Hermes Agent** (a dedicated, tool-free profile) | your admin's Hermes, which forwards to the model it is set up with ([Hermes][HERMES-API]) | "your admin's Hermes agent keeps a transcript and forwards the request" |
| **OpenAI** | OpenAI's servers | "not used for training; abuse logs up to 30 days" ([OpenAI][OPENAI-DATA]) |
| **OpenRouter** | OpenRouter, then the model's host | "routed only to providers that do not collect data" ([OpenRouter][OPENROUTER-ROUTING]) |

A model your admin runs at home keeps your data in the house and is the most private choice. If you
have your own OpenAI, OpenRouter or Nous Portal key, you may be able to add it in **Settings → AI ideas →
My own AI provider** (and, if your admin allows it, the address of another AI server that uses HTTPS).
Your key is encrypted on the server and never shown again; changing it asks for your password. If your
own provider fails, the app never sends your data to the shared one instead
([Settings and keys](settings-and-keys.md)).

## Where to find it

When AI is on for you, the **Add** screen shows **AI meal ideas**, **Describe a meal (AI)**, **Read a
label (AI)** and, if your admin allows it, **Plate photo (AI)**, with the number of shared AI calls left
today. Each AI idea shows its foods with their warnings, the totals, what is left of your day after it,
and **Add to plan**. If no AI idea fits your targets, the app shows its own ideas instead.

## Turn it on

1. Check that your admin has switched AI on (**Settings → AI ideas** says whether it is on).
2. Tick **Use AI ideas**.
3. Choose the provider your admin offers, or your own key if allowed.
4. Decide whether to share age band and sex. It is off by default.
5. Optional: write preferences such as "vegetarian, no fish".
6. The first time you use an AI button, read the consent sheet and the exact text, then accept. Photos
   have their own consent. You can also ask to see the request before every AI call.

## Take it back

- Untick **Use AI ideas** to stop all AI calls for your account.
- **Settings → AI ideas → AI activity** lists what was sent and what came back. **Delete my AI history**
  removes it. **What you agreed to send** has **Withdraw** for each server.
  Stored requests are kept for 30 days by default; admins see only counts, not contents.
- If your admin changes a provider's address, everyone is asked for consent again.

## Limits to keep in mind

- AI can be wrong or slow. A home model on a small computer can take a minute or two; the app then shows
  its own ideas.
- Photo reading copies what is printed. Check every field marked "from photo" against the label.
- Portions guessed from a plate photo were off by about a third on average in a 2025 test, and too
  small for big plates ([Fridolfsson 2025][FRIDOLFSSON25]). Do not count carbohydrate for insulin from a
  photo guess.
- There is a daily limit on shared AI use (30 calls per person by default).

## If something goes wrong

- **"The AI ideas did not fit your targets today, so these are the app's own ideas."** Every AI idea
  failed the rules. Use the app's ideas.
- **"This is outside what the app's AI helps with. Your care team can answer it."** The question is
  medical. Ask your team.
- **AI is missing.** Your admin has not switched it on, or today's shared limit is used up.

## Related pages

- [Meal guidance](guidance.md) · [Barcodes and label photos](barcode-and-photo.md) · [Privacy and your data](privacy.md) · [Settings and keys](settings-and-keys.md)
- For admins: [Configuration](../self-hosting/configuration.md) · [Network allowlist](../self-hosting/network-allowlist.md)

## Sources

- [Design note 04: optional AI][NOTE04] and its security review (guardrails, payload, consent, presets).
- [Design note 03][NOTE03] (label and plate photos); [design note 06][NOTE06] (the rules AI must pass).
- [OpenAI API: your data][OPENAI-DATA]; [OpenRouter: provider routing][OPENROUTER-ROUTING];
  [Ollama: OpenAI compatibility][OLLAMA-OAI]; [Hermes Agent: API server][HERMES-API].
- [Fridolfsson 2025][FRIDOLFSSON25]: AI estimates from food photos.
- [ADA Standards of Care 2026, section 6][A26-6]: treating a low.
