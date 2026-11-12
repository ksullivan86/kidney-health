# 36 · Reading a lab PDF's own text

| | |
|---|---|
| Status | Decided 2026-11-12 (§8), built in one part. |
| Date researched | 2026-11-12, against `main` at `fed556c` |
| Scope | Labs → **Read a lab report** with a PDF: for each ticked page that has real text, the browser reads that text with pdf.js, rebuilds its lines, leaves out lines that may say who the person is, and sends the lines to a new AI feature on the **local AI only**. Pages without text still go as pictures (note 13). |
| Out of scope | Parsing a PDF on the server; text from a photo (no OCR); a cloud AI for lab reports; saving anything without the person's tick. |
| Builds on | Note 13 (pdf.js in the browser, the page list, the review table), note 04 and `docs/ai.md` (features, routing, consent), note 31 (the privacy filter), note 32 (a person's own local or cloud choice), `app/ai/lab_report.py` (the judge). |
| Re-verify | Real portal PDFs (Quest, Labcorp, a hospital portal) on the owner's local model; `scripts/ai_eval.py --lab-text` against that model. |

## 1. Why

Many portal PDFs are made from text, not scans. Today each page is drawn, sent as a picture and read by a vision model.
Reading the text instead is:

* **faster**: a page of text is a few thousand characters, not a 2-megapixel picture;
* **exact**: the digits are the PDF's own characters, so the app can check that every value the model returns is really
  in the text (§4.3). A picture cannot be checked that way;
* **lighter**: it works with a small text-only local model. A vision model is no longer needed for these pages.

## 2. Facts used

| # | Fact | Source |
|---|---|---|
| T1 | `page.getTextContent()` returns `items` with `str`, `transform` (`[a, b, c, d, e, f]`: `e`, `f` are the x and y of the baseline in PDF points, y up), `width`, `height` and `hasEOL`. Items come in content-stream order, which is not always reading order. A scanned page has no items, or only a few (a header). | pdf.js `src/display/api.js` (`TextContent`, `TextItem`) |
| T2 | `getTextContent` runs in the same worker as drawing and fetches nothing when no `cMapUrl` or `standardFontDataUrl` is given (note 13 D3). Text in a CJK font that needs a CMap may come out empty or wrong; such a page then counts as having no text. | pdf.js `src/core/evaluator.js` |
| T3 | Ollama's default context is 4096 tokens; a dense page of results is about 2,000 to 5,000 characters (500 to 1,500 tokens). | note 04, `docs/ai.md` "Troubleshooting" |

## 3. Flow

1. The person chooses a PDF. As today, pdf.js opens it in the browser and the pages are listed (1 to 6 ticked, at most 10).
2. For every page, the browser asks pdf.js for its text and rebuilds lines (§4.1). A page **has text** when the rebuilt lines
   hold at least 50 letters and digits and at least 2 lines with a digit. Each page in the list says "text" or "picture only".
3. When at least one page has text and the server offers the text feature, the page list shows a choice, **Read the text**
   (picked first) or **Read pictures of the pages**. With text, each ticked page with text is sent as text and each page
   without text as a picture (when the local AI can read pictures; otherwise that page is skipped with a line saying why).
4. Before a page is sent as text, lines that may say who the person is are left out (§4.2) and the screen says how many.
5. Each page is one request to `POST /api/ai/read-lab-report-text` with `{text, page}`. The server checks the answer (§4.3)
   and returns the same proposed rows as for a photo.
6. All pages go into the one review table. Every row starts unticked and says where it came from: "page 2 of your PDF,
   read from its text" or "page 3 of your PDF, read from a picture". Nothing is saved until the person ticks rows and
   presses Save (the ordinary `POST /api/labs/import`).

## 4. Design

### 4.1 Lines from text items (`js/engine/pdf_text.js`, `KH.pdfText`)

Pure, tested in Node (`tests/js/pdf_text.test.mjs`); the server does not parse PDFs, so there is no Python twin.

* Items with an empty or space-only `str` are skipped. Each kept item has `x = transform[4]`, `y = transform[5]`,
  `h = height || |transform[3]|` (at least 1), `w = width`.
* Sort by `y` descending, then `x`, then the original index (a stable order whatever the content stream says).
* An item joins the current line when its `y` is within `max(2, 0.5 × the smaller of the two heights)` of the line's first item;
  otherwise it starts a new line.
* Within a line, items are sorted by `x` (index on a tie). Two items are joined with one space when the gap between the end of one
  (`x + w`) and the start of the next is more than `0.15 × h` (at least 0.5 pt); otherwise directly.
* Whitespace inside a line is collapsed; empty lines are dropped. At most 400 lines and 20,000 characters a page; a page over that
  is read as a picture.

### 4.2 Lines that may say who the person is

A line is left out when it names, as a label, a patient, a name, a date of birth (`DOB`, `birth`), a record or account number
(`MRN`, `medical record`, `account`, `acct`, `patient id`, `member id`, `ID #`), a social security number, an address, a phone or fax
number, insurance, a guarantor, or holds an email address. The test header line "Test Name Result Units" is left out as well,
which costs nothing. A line that holds both a collection date and a date of birth is left out: the person then types the date.

This is a courtesy, not the guarantee: the rules cannot catch every way a report prints a name. **The guarantee is routing**: the
text goes only to the local AI (§5).

### 4.3 The server

* Feature `read_lab_report_text` (`app/ai/features.py prepare_read_lab_report_text`), routed as the existing feature `labs`:
  route `local` or `off` only, consent purpose `labs`, never a person's own provider, never a person's choice, never a cloud
  fallback (`local_only=True`, checked again in `run_call`). It does **not** need a vision model.
* The body: `{text: 1 to 20,000 characters, page: 1 to 50 or null}` (JSON, `extra` refused). The browser sends at most 10 pages a
  run, one request a page, as for pictures. The person's AI slot, the server's slots and the shared daily limit apply as for photos.
* The prompt (`TASK_LINES["lab_report_text"]`) is the photo prompt's rules for text: copy result lines of the app's tests, the value
  and unit exactly as written, the date exactly as written, never a name, a date of birth or a record number, never advice. The
  data block is `{"lines": [...]}`. Same schema as photos (`schemas.lab_report_schema()`).
* The judge (`app/ai/lab_report.judge_text`) runs **before** the photo judge:
  * a row whose value is not a number written in the sent text is dropped and counted (`not_in_text`). Numbers are read from the
    text as written (`5.4`, `1,250`, `0.9`); `1,2` also counts as 1.2, for reports with a decimal comma;
  * a row whose date is not written in the text (spaces and case aside) loses its date; the person types it;
  * then the photo judge: the app's own tests and units, the `POST /api/labs` checks, dates that cannot mean two days.
* A text that does not fit the local AI's prompt budget (`AI_CONTEXT_TOKENS`) is refused with 413 `too_long_for_ai`; the browser
  then reads that page as a picture when it can.
* The AI activity row keeps no copy of the text and no copy of the answer, whatever the retention setting: the request's text is
  replaced by its length and SHA-256, as a photo is.

### 4.4 The demo and the preview

They have no AI. `POST /api/ai/read-lab-report-text` in the demo answers with a fixed example (three rows) and says that nothing
was sent and that the rows are an example, not read from the file. Pictures stay unavailable in the demo.

## 5. Privacy

* Routing is the guarantee: `labs` resolves only to the provider holding the role `local`, pinned to the private network, or to
  nothing. A person who chose the cloud for every other feature still reads lab text on the local AI; with no local AI the feature
  is off. There is no fallback.
* The privacy filter (note 31) runs only for AIs that are not local, so it never touches this request; it is not needed, and §4.2
  does the browser-side part.
* Nothing is stored: the PDF, its text and the drawn pages stay in the browser's memory until Save, Discard or a new pick. The
  server keeps nothing but the AI activity row (a fingerprint of the text, the counts, no answer).

## 6. Limits

* A page whose text is out of reading order (two columns, a table drawn cell by cell in odd order) may give lines that mix two
  results. The model then copies less, or the verbatim check drops a value; it cannot make up a value.
* The check is on the page, not the line: a wrong value that happens to be written somewhere else on the page (a reference range,
  a time, a page number) passes it. The other checks still apply, and the person checks each row against the report before ticking it.
* Values printed as `<5` or `>90` are left out, as for photos.
* A scanned page, or a page in a font pdf.js cannot read as text, goes as a picture.

## 7. Evaluation

* Offline golden cases (`tests/ai_golden/lab-text-*.json`, feature `lab_report_text`) with made-up reports: a good page, an
  invented row dropped by the verbatim check, a date not in the text, an injected instruction in the text, a name line that
  the browser would strip, too long for the budget.
* `scripts/ai_eval.py --lab-text` runs the same pages against a live **local** provider (refused for `--role cloud`) and reports
  `lab_text_value_verbatim_rate` (values that passed the verbatim check, of all values the model returned; gate 100 % of shown
  rows by construction, so the number to watch is how many it had to drop) and `lab_text_rows_expected_rate` (expected rows found).

## 8. Decisions (2026-11-12, the owner's brief)

1. **Text first when there is text**, pictures for the rest, and the person can choose pictures for the whole PDF.
2. **Local AI only**, as lab photos: the same `labs` route and consent. No vision model is needed for text.
3. **Values must be in the text.** Rows with a value not written in the sent text are dropped and counted.
4. **One page a request**, at most 20,000 characters, at most 10 pages a run (the browser's limit, as for pictures).
5. **Identity lines are left out in the browser** as a courtesy; routing stays the guarantee.
