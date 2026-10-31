# 31 · The privacy filter: names, places and dates out before a cloud AI

| | |
|---|---|
| Status | Accepted and built for 0.20, 2026-10-31. No schema step. |
| Owner's words (2026-10-31) | "Privacy filter: it adds protection on top of your rules. It never replaces them. Lab reports and anything showing your name or date of birth still go to the local model only. The filter also takes names, places and dates out of everything else before it goes to a cloud AI. It's on whenever a cloud AI is set up, and it can't be turned off." |
| Standing rules it keeps | Lab reports, and anything showing the person's name or date of birth, go to the local model only, never to the cloud and never as a fallback. Prompts and replies are not stored anywhere new. The AI is never given a dosing task. Every setting is an environment variable (this feature has none: it cannot be turned off). |
| Builds on | ROADMAP "Privacy tiers" (tier 2), `app/ai/routing.py` (tiers 1 and 3), `app/ai/client.py` (the one place a request body is sent). |
| Out of scope | Photos, voice clips and lab report images (the filter reads text only). A named-entity model (§5). |

## 1. What it does

Before any request goes to a **cloud** AI, the app replaces identifying details in every text part of the request with
labels such as `[PERSON_1]`, `[PLACE_1]` or `[DATE_1]`. The same word gets the same label everywhere in that request.
When the reply comes back, the app puts the original words back before the person sees it. The table that links labels to
words lives in memory for that one request and is then dropped. It is never stored, logged or sent.

"Cloud" means any provider that is not pinned to the private network (`ProviderConfig.local_only` is false): the shared
cloud AI, a person's own provider, and a shared provider without the local role. Requests to the local AI are never
changed.

## 2. What it removes

| Label | What | How |
|---|---|---|
| `PERSON` | The account's user name, display name (and each part of it), e-mail and its local part; the user and display names of everyone in the person's Care team (both directions, open invites too) | Whole-word match, any case. A known name that is also a word in the app's own prompts or a nutrient name is skipped, so the prompt keeps working. |
| `PERSON` | A capitalised name after a cue: Dr, Doctor, Prof, Mr, Mrs, Ms, Miss, Nurse, dietitian, nephrologist and other care roles; "my wife/husband/son/daughter/friend/…"; "named", "called", "my name is"; "Dear", "Hi", "Hello" | One to three capitalised words. A name found this way is also replaced everywhere else in the request. "Dr Pepper" and "Dr Oetker" are kept. |
| `PLACE` | One to four capitalised words before Hospital, Clinic, Medical Center, Infirmary, Surgery, Pharmacy, Dialysis Unit and similar; a capitalised place after "live in", "moved to", "born in", "near", "trip to" and similar cues | |
| `ADDRESS` | A house number and one to three words ending in a street word (Street, Road, Ave, Lane, …); "Apt 4B", "Flat 2", "PO Box 12"; a US ZIP after a state code or "zip", ZIP+4, UK and Canadian postcodes | |
| `DATE` | Dates in common written forms: `2026-10-31`, `31/10/2026`, `10.31.26`, "31 October 2026", "Oct 31", "October 31st, 2026", "March 2025"; a year after "born" | Relative words (today, yesterday, last week), weekdays, times of day and a bare month or year stay. |
| `PHONE` | Numbers shaped like phone numbers: a leading `+`, an area code in brackets, dashes or dots between groups, or the group shapes of US and UK numbers | 10 to 15 digits. |
| `EMAIL` | Any e-mail address | |
| `URL` | A web address with a query string, a fragment, a user name, or a long number in it | Plain addresses such as a handbook link stay. |
| `ID` | A labelled number (MRN, NHS number, record, patient, account, member, policy, ID, SSN, …); any run of 7 or more digits; `123-45-6789` | A number next to a unit is never touched. |

It leaves alone what the question is about: "potassium 5.8", "2 cups", "150 mg", "eGFR 28", "stage 4", times, ages, food
names, and every number that is an amount with a unit. Numbers inside the app's own JSON data (after `:`, `,` or `[`) are
also left alone, so the data block stays valid JSON.

## 3. Where it runs

In one place: `ChatClient.complete_json` in `app/ai/client.py`, the only code that sends a chat request. For a cloud
provider it filters the whole body (system message, every user and assistant message, the repair turn) right before
it is sent, and restores the labels inside the parsed reply before the reply is checked. `ChatClient.request` refuses a
request body for a cloud provider that did not come through the filter, so no feature can skip it. The known names are
attached to the provider settings by `routing.resolve_feature`, the one place every feature resolves its provider.

"What will be sent?" (`Prepared.dry_run`) and the AI activity copy of the request (`Prepared.audit_copy`) run the same
filter, so they show exactly what leaves the server. The dry run also says how many details were replaced. The activity row
records that number (`privacy_filter`), never what was replaced. The reply kept in the activity row is the cloud's own
reply, with its labels.

The filter never changes routing. Lab report photos stay local-only exactly as before (the filter is never a reason to
send one to the cloud), and the tier 3 fallback is unchanged.

Photos and voice clips: the filter cannot read an image or a recording. The photo rules stay as they are: location and
camera data are removed, lab reports go only to the local AI, and the person agrees before a photo is sent.

## 4. Limits, said plainly

* It catches the patterns above. A name typed in lower case with no cue ("ann says hi"), a street with no number, or a
  town mentioned with no cue word gets through unless it is a known name. The test set measures recall (§6).
* It hides who is asking, not that someone with kidney disease asked. The health details are the question, so they stay.
* A false match costs a little meaning ("a soup called Minestrone" becomes "a soup called [PERSON_1]"); the person still
  sees their own words in the reply.
* Ask's date-aware tools see a label instead of a date. Words like "today" and "yesterday" still work.
* Input longer than 200,000 characters in one message part is not filtered: the request is refused, not sent unfiltered.

## 5. A named-entity model later

The ROADMAP suggests Microsoft Presidio with spaCy, or a GLiNER-class model. Either finds names and places without cue
words, so recall on free text would rise. The cost, roughly, to be measured before any decision:

* **Presidio + spaCy `en_core_web_lg`**: about 600 MB more in the image (the model is about 400 MB to download), about
  1 GB of memory once loaded, a few milliseconds per message on CPU. Several new Python packages.
* **GLiNER (small to medium, 150–200 million parameters)**: PyTorch (CPU) and Transformers, about 1–2 GB more in the
  image, 1–2 GB of memory, tens to hundreds of milliseconds per message on CPU.

Both are new dependencies and need the owner's decision. The rules here would stay as the first pass either way, and the
test set (§6) would show what the model adds. The LiteLLM proxy guardrail (ROADMAP) is the other route: it would cover
every client of the proxy, not only this app.

## 6. Tests

* `tests/data/redaction_cases.json`: messages with known identifiers, the words that must go and the words that must
  stay. `tests/test_ai_privacy_filter.py` prints the measured recall and fails below the floor.
* Requests to the local AI are byte-for-byte unchanged; lab reports stay local-only; the reply is restored; nothing about
  the replaced words is stored or logged; "What will be sent?" shows the filtered body for a cloud provider; hostile
  inputs (long runs of spaces, `(`, capital letters, digits) finish quickly.
* The app's own prompts and schemas pass through the filter unchanged.

## 7. Decisions the owner may change

1. **No new dependency.** Rules in the standard library now; an NER model later only by the owner's choice (§5).
2. **What it removes**: the list in §2. Bare months, bare years, weekdays and times of day stay.
3. **Where it runs**: one place in the client, on every text part of every cloud request.
4. **Restore in the reply**: labels go back to the original words in memory only, for that one request.
5. **"What will be sent?"** shows the filtered text for a cloud provider.
6. **Always on** for a cloud provider. No switch and no environment variable. Images and voice are not filtered.
7. **The activity row** records how many details were replaced, never which.
8. **No prompt change.** The models are not told what the labels mean (that would need a new prompt version and a live
   run). If live runs show models mangling labels, add one line to the prompts then.
9. **"Cloud" is "not pinned local"**: a shared provider on the private network that does not hold the local role is
   filtered too, because it may forward to a cloud model (a LiteLLM proxy, Hermes).
