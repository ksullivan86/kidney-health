---
title: Optional AI
description: "What the optional AI features do, what is sent and to whom, how you give and take back consent, and the safety limits that always apply."
slug: ai
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-15
fact_checked: 2026-10-05
sources: [NOTE04, NOTE03, NOTE06, OPENAI-DATA, OPENROUTER-ROUTING, OLLAMA-OAI, HERMES-API, FRIDOLFSSON25, A26-6, ASSISTANT-DOC]
---

# Optional AI

!!! note "Off until you choose it"
    AI features are **off** unless your admin switches them on, and then off for you until you opt in.

The app works fully without AI. AI is an extra layer that can re-rank meal ideas, turn a sentence such
as "2 eggs, toast with butter, tea" into food searches, or read the numbers from a photo of a label
([design note 04][NOTE04]). The app's own rules check every AI answer before you see it.

## How the setup fits together

Three choices make up every AI setup (Settings → AI ideas starts with the same three questions):

1. **Which AI answers.** Your admin chooses it: a model running at home, a company's AI over the
   internet (such as OpenAI or OpenRouter), or a home "Hermes" agent. Your admin may also let you add
   your own key.
2. **What it may do.** Your admin switches AI on, and then you opt in. AI can suggest meals, turn a
   typed meal into food searches, and read a label photo. If your admin also switches on **Ask**, it can
   answer a short question about your food and numbers. It cannot give doses or save anything.
3. **Who sees your request.** The consent sheet names where your request goes and who can read it.
   **What will be sent?** shows the exact request before it goes.

A model at home keeps your data in the house. A company's AI means your request leaves the house, so
the consent sheet says so before you agree.

## What AI can and cannot do here

| AI can | AI cannot |
|---|---|
| Pick and order meal ideas, using **only** foods the rules already allowed | Invent a food or a nutrient number: every number comes from the app's food list |
| Split "describe a meal" text into search words; you pick each match | Save anything on its own, unless you chose to trust it in **Ask** (below): you tap **Add to plan** or **Save** and the normal rules run again |
| Copy printed numbers from a label photo into a draft food you check, marked "from photo" | Estimate nutrients from a plate photo: it gives food **names** and a rough weight; the numbers come from your food list |
| Name foods it sees on a plate photo | Give doses, answer medical questions, or read your lab results |
| In **Ask**, answer a short question after looking up your own numbers in the app | Make up a number: the app checks every number in an answer before you see it |

### Safety rules that always apply

- **No insulin, no doses.** AI never gives insulin doses, ratios, correction factors, pump or CGM
  settings, or medicine advice. Carbohydrate is shown only in grams ([design note 04][NOTE04]).
- **Lows never go to AI.** If you type words like "low", "hypo" or "shaky", the app shows its own
  "Treating a low" card and does not call AI ([ADA 2026][A26-6], section 6).
- **Red-flag symptoms never go to AI.** If you type "chest pain", "can't breathe", "confused", "faint" or
  "seizure", the app shows a **Get help now** card (call your emergency number; treat a low first)
  instead.
- **AI never overrides a warning.** An idea that would push your day over a limit is dropped.
- **No free text from AI in the meal features.** The reasons you read under an idea ("Low in potassium; fits your
  dinner carbohydrate goal") are written by the app's maintainers, not by the AI. **Ask** is the one place
  where the AI writes sentences, and the app checks them before you see them (see "Ask" below).
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
| Your messages in an **Ask** conversation, and the numbers the assistant looks up for it (your targets, today's totals, food names and nutrients), **only after you agree to it separately** | |

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
and **Add to plan**. If no AI idea fits your targets, the app shows its own ideas instead. If your admin
has switched on **Ask**, a tab called **Ask** is there too.

## Turn it on

1. Check that your admin has switched AI on (**Settings → AI ideas** says whether it is on).
2. Tick **Use AI ideas**.
3. Choose the provider your admin offers, or your own key if allowed.
4. Decide whether to share age band and sex. It is off by default.
5. Optional: write preferences such as "vegetarian, no fish".
6. The first time you use an AI button, read the consent sheet and the exact text, then accept. Photos
   have their own consent, and so does **Ask**. You can also ask to see the request before every AI call.

## Take it back

- Untick **Use AI ideas** to stop all AI calls for your account.
- **Settings → AI ideas → AI activity** lists what was sent and what came back. What came back is the AI
  server's own answer, before the app checked it: the app used only the parts that passed, so words it never
  shows you, such as anything about insulin, doses or medicines, read [hidden] there. It is not advice. Your
  data export keeps the full text. **Delete my AI history** removes it. **What you agreed to send** has **Withdraw** for each server.
  Stored requests are kept for 30 days by default; admins see only counts, not contents.
- If your admin changes a provider's address, everyone is asked for consent again.

## Limits to keep in mind

- AI can be wrong or slow. A home model on a small computer can take a minute or two; the app then shows
  its own ideas.
- Photo reading copies what is printed. Check every field marked "from photo" against the label.
- Portions guessed from a plate photo were off by about a third on average in a 2025 test, and too
  small for big plates ([Fridolfsson 2025][FRIDOLFSSON25]). Do not count carbohydrate for insulin from a
  photo guess.
- There is a daily limit on shared AI use (30 calls per person by default). One question in Ask can use
  several of those calls, so the limit runs out sooner.

## Ask: a chat inside the app (optional)

If your admin switches on **Ask**, a tab called **Ask** appears for people who use AI ideas. You type a question,
for example "How much potassium do I have left today?" or "Can I have a banana as a snack?", and press Enter.

- The assistant **looks up your own numbers in the app** (your targets, your day, a food) and answers in a few
  plain sentences. Under the answer, **From the app** shows the figures the app itself worked out.
- If your message sounds like a **low**, the app shows its own **Treating a low** card at once. If it sounds like
  an emergency, it shows **Get help now**. The AI is not asked, and nothing in Ask ever tells you to wait or skip
  treating a low.
- The app **checks every answer** before you see it. If an answer touched on insulin or medicine doses, or had a
  number the app did not work out, you see a short notice instead, with the app's own numbers. Ask your care
  team about doses and about lab results.
- **Saving from Ask.** If you ask it to log, plan or save something ("log a banana for breakfast"), it does not
  save it by itself. By default it shows a **card**: the foods the app found, the amounts and the app's totals,
  with the words "Nothing has been saved yet". Press **Save as eaten**, **Save as planned** or **Cancel**; only your
  press saves. You can also use the **Add** screen as always.
- **How much do you trust the assistant?** In **Settings → AI ideas** you can choose **Ask me before every save**
  (the default, and the one we recommend), **Trust it for this conversation** or **Trust it always**. The last two
  save at once without asking, so you do not have to confirm every time, and they come with a warning first: the
  assistant can pick the wrong food or the wrong amount. Every number still comes from the app, the low and emergency
  rules and the dose checks stay on, and you can **Undo** each save (or delete it on **Today**). Photo and label
  readings are always shown to you to check, whatever you choose. These two options only work if your admin has
  allowed them; if not, Ask always asks first. "This conversation" ends when you start a new conversation or after
  12 hours.
- The conversation stays on the page. **New conversation**, reloading or signing out clears it, and the server
  keeps no copy of what you wrote. Your AI activity shows that a call happened, not what was said.
- The first time, a sheet asks you to agree to send your messages and the numbers it looks up. **What will be
  sent?** shows the exact request first.
- Ask answers can be wrong or slow, like any AI. If a number matters, check it on **Today**. It does not replace
  your care team.

## Talk to an assistant (optional)

Some people like to ask about food in a chat, by typing or by talking. If your admin turns on **assistant
access**, you can connect a chat assistant you already use (for example Open WebUI, or a Hermes Agent profile) to
the app with a personal token from **Settings → Assistant access**
([Settings and keys](settings-and-keys.md#assistant-access)).

- The assistant **asks the app** for your targets, what is left of today, the values of a food, and how a meal
  would change your day. The app does the sums from your own log; the assistant is told never to make numbers up.
- A token **reads only** unless you tick **Can also save food and recipes** when you make it. With that box
  ticked the assistant can also add food to your log and save a recipe as a saved meal. It is told to read back
  what it will save and wait for your yes, and to say what it saved. A model can still get an amount wrong, so
  look at **Today** or **Saved meals** afterwards; you can edit or delete anything it saved, and each save is
  listed in your activity. It can never change a setting or delete anything. A token that only reads leaves
  logging to you, in the app.
- When a message sounds like a low, the app hands the assistant the same **Treating a low** card you see in the
  app, to show first. When a message sounds like an emergency, it hands over **Get help now**.
- The app cannot check what the assistant finally says. If a number looks wrong, check it on **Today**.
- What you type or say, and the app's answers, go to the chat assistant and to the AI model it uses. A model run
  by a company sees them.

How to set it up is in the [assistant guide][ASSISTANT-DOC] for whoever runs your server.

## If something goes wrong

- **"The AI ideas did not fit your targets today, so these are the app's own ideas."** Every AI idea
  failed the rules. Use the app's ideas.
- **"This is outside what the app's AI helps with. Your care team can answer it."** The question is
  medical. Ask your team.
- **"This answer was not shown because it touched on medicine or insulin doses."** (in Ask) The app does not
  show answers about doses. Ask your care team.
- **"The assistant's answer had a number the app did not work out, so it is not shown."** (in Ask) The app shows
  its own numbers instead. Ask again, or look on **Today**.
- **"The assistant could not finish; here are the app's numbers."** (in Ask) The AI needed too many steps. Try a
  shorter question.
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
- [The assistant guide][ASSISTANT-DOC]: connecting a chat assistant, its system prompt and its limits.
