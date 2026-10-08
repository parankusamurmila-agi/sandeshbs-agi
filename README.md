# HA Request & Response Agent

Hackathon prototype for **Hack_2026_001 — HA Request & Response Agents**: upload one or
many health-authority deficiency letters (PDF or Word), have an agent read each document
directly to extract every individual question/deficiency (each tagged with the specific
drug it concerns), let a human review and link each question to its registration/
application tracking record, draft a CTD/eCTD-style, region-aware response grounded only
in that record, and let a human edit/approve with a full document-level audit trail that
also tracks exactly what every LLM call cost.

- **Backend**: FastAPI, deployed as a Lambda container image behind API Gateway (HTTP API).
- **LLM**: AWS Bedrock, Claude Sonnet, via the Converse API with forced tool-use for
  reliable structured output, native PDF document blocks (no separate text-extraction
  step), and prompt caching on the (static, reused-every-call) system prompts
  (`backend/app/services/bedrock_client.py`).
- **Frontend**: React + TypeScript (Vite), run locally against the deployed API for the
  demo.
- **Infra**: AWS CDK (Python) — S3 (PDF storage), DynamoDB (correspondence records),
  Lambda, HTTP API.
- Registration/application tracking records, submission content, and historic precedent
  responses are **mocked** fixtures under `backend/app/data/` (small enough to pass in
  full to the model — no vector DB needed at this scale).

## Project flow

This builds on the existing Health Authority Interactions product, which already
converts incoming HA correspondence (email, letter) to PDF, imports it, and summarizes
it. This agent goes one level deeper — from "what does the letter say" to "what is the
health authority actually asking the applicant to do, and how do we respond."

1. **Intake** — one or many deficiency letters are ingested two ways (`UploadPage.tsx`
   mode toggle): direct multi-file upload (`POST /api/correspondence`, PDF or Word,
   `files: List[UploadFile]`) or by pointing at a path containing many documents
   (`POST /api/correspondence/from-path`, an `s3://bucket/prefix` for real use, or a
   local folder when the backend runs with `LOCAL_STORE=true`). A Word (`.docx`) file is
   converted to PDF first (`doc_converter.convert_docx_to_pdf`, mammoth + WeasyPrint —
   see the WeasyPrint caveat under Prerequisites) so the rest of the pipeline only ever
   handles PDFs. Every document is processed independently through the shared
   `_ingest_one_document` pipeline and sent **directly** to the model as a Bedrock
   Converse document block — no separate text-extraction pass — producing exactly one
   `Correspondence` and one `extract` **Invocation** (see step 7) per document.
2. **Extract structured questions** — the agent identifies every distinct question/
   deficiency as its own item: id, section, the specific **drug/product it concerns**,
   verbatim text, referenced documents/datasets, and a page + verbatim quote for
   traceability back into the PDF (`agent_pipeline.extract_letter`, the
   `ExtractedRequest` model). Numbered items with lettered sub-parts (9a, 9b, ...) are
   split into separate requests. Letters covering more than one product are supported —
   `drug` is recorded per-question, not just once for the whole letter.
3. **Human review, then link to affected content** — after reviewing a question in the
   UI (`RequestList.tsx` / `EvidencePanel.tsx`), the user explicitly triggers
   `POST .../requests/{id}/link`, which deterministically (no LLM call) matches that
   question's `drug` against `mock_registration_records.json`, narrowing by the letter's
   issuing health authority when a product has more than one registration (e.g. a US/FDA
   and an EU/EMA filing for the same drug) (`agent_pipeline.match_registration_records`).
   From there, the submission documents/datasets belonging to that same application
   (`agent_pipeline.match_submission_content`, via the registration record's own
   `related_submission_doc_ids`) and any historic precedent resolved on that same
   application in the past (`agent_pipeline.match_historic_precedents`, matched by
   application number) are pulled in too — all three evidence sources are deterministic
   lookups, surfaced for the user to review before drafting.
4. **Human-in-the-loop direction** — before drafting, a user can supply direction (e.g.
   "we will comply by providing X") via `DraftEditor.tsx` / `DraftRequestBody.direction`.
5. **Draft the response** — a second, final LLM call drafts a CTD/eCTD-style,
   point-by-point response (acknowledgement → response narrative → supporting evidence →
   commitment/timeline) using a template **selected** for the matched health authority
   (`agent_pipeline._select_template`, FDA/EMA/Health Canada/generic in `templates.json`)
   and region-specific terminology, grounded **only** in the linked registration
   record(s), submission content, historic precedent, and the user's direction — nothing
   fabricated (`agent_pipeline.draft_response`).
6. **Edit, approve, audit** — the draft is editable in place and explicitly approved
   (`PATCH .../draft`). Every lifecycle event — uploaded, extracted, linked, drafted,
   edited, approved — is appended to a single **document-level audit trail** on the
   `Correspondence` itself (`Correspondence.audit`), each entry optionally tagged with
   the `request_id` it relates to.
7. **Invocation metering** — every Bedrock call (the extract call in step 1, and each
   draft call in step 5) records an `Invocation` (`backend/app/models.py`) with
   input/output/cache-read/cache-write token counts (read from Converse's `usage`
   object) and an **estimated** USD cost (`bedrock_client.estimate_cost_usd` — a rough,
   demo-only approximation, not a billing-accurate figure). The detail page's **Audit**
   tab (separate from the **Requests** tab) shows both the lifecycle trail and this
   invocations table (`InvocationsPanel.tsx`), so a reviewer can see exactly what any
   given document or question cost to process. The question list also shows a drug
   count (`new Set(requests.map(r => r.drug)).size`) alongside the question count.

**Known gaps vs. the full ask** (flagged, not yet built):
- Requests aren't classified into a controlled deficiency-type taxonomy yet — `section`
  is free text copied from the letter's own heading, not a normalized category.
- Registration/application tracking records, submission content, and historic precedent
  are mocked fixtures (`backend/app/data/`), not a live HA Interactions/RIM integration.
  Drug-to-registration matching is a simple fuzzy substring match; submission/precedent
  linking rides on the registration record's own cross-references
  (`related_submission_doc_ids`, application number embedded in `precedent_id`) rather
  than a real master-data lookup.
- Template selection picks between a small, fixed set of per-authority templates
  (`templates.json`) that share the same four-section CTD skeleton with region-specific
  terminology substituted in — not fully bespoke FDA/EMA/Health Canada template
  structures.
- **No background job infra.** "Async" here means the UI stopped serializing actions
  behind one page-wide busy flag (`CorrespondenceDetail.tsx` now tracks busy state
  per-question) — the backend is still one synchronous Bedrock call per HTTP request,
  same as before. A real background-job architecture (SQS + worker Lambda, Step
  Functions) was explicitly out of scope for this pass.
- **No optimistic locking.** `store.py` does read-full-item → mutate → write-full-item
  with no version/conditional write. Two concurrent actions on *different questions in
  the same correspondence* (e.g. generating Q1's draft while linking Q2) can lose an
  update. Acceptable at hackathon scale; a real fix (versioned writes or per-request
  DynamoDB rows) touches every route.
- **Batch "from-path" ingestion is synchronous** — the HTTP request blocks until every
  discovered document is processed. Fine for a handful of documents; a large batch could
  hit the Lambda/API Gateway timeout.
- **Cost estimates are approximate.** `estimate_cost_usd` uses a small hardcoded
  per-million-token pricing table matched by substring on the model id — not account-
  specific billing data.

## Prerequisites

- Python 3.12
- Node.js + npm (needed for both the React frontend and the AWS CDK CLI) — **not
  installed in the environment this was built in; install it before running the
  frontend or `cdk` commands.**
- Docker Desktop running (CDK builds the Lambda container image locally via Docker on `cdk deploy`)
- AWS CLI configured with an account that has Bedrock access to a Claude Sonnet model/
  inference profile in `us-east-1` (verify with `aws bedrock list-inference-profiles
  --region us-east-1`)
- **For Word (.docx) upload support only**: WeasyPrint (used for the docx→PDF
  conversion) is pip-installable but still links native shared libraries (Pango, cairo,
  GDK-pixbuf, HarfBuzz) at runtime — it is **not** dependency-free just because it's
  pure Python. Locally on Windows, install the GTK3 runtime (see WeasyPrint's own
  [install docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation))
  or `.docx` uploads will fail with an `OSError` at conversion time (PDF uploads are
  unaffected either way — the import is lazy). The Lambda image installs the equivalent
  packages via `dnf` in `backend/Dockerfile`.

## 1. Backend — local run

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# Local dev without provisioning AWS resources first:
#   LOCAL_STORE=true keeps correspondence records in-process and PDFs on local disk.
LOCAL_STORE=true AWS_REGION=us-east-1 uvicorn app.main:app --reload
```

API is now at `http://localhost:8000`, docs at `http://localhost:8000/docs`.

Run the test suite (unit tests for the Bedrock client + agent pipeline, Bedrock mocked):

```bash
pytest
```

## 2. Frontend — local run

```bash
cd frontend
npm install
cp .env.example .env     # point VITE_API_BASE_URL at your local or deployed API
npm run dev
```

Open `http://localhost:5173`. On the upload page, either select one or more PDF/Word
files directly, or switch to "Provide a path" and point at an `s3://bucket/prefix` (or a
local folder, with `LOCAL_STORE=true`) containing several documents — each is ingested
independently. On a document's detail page, review a question (and the drug it's tagged
with), click "Link registration record," then "Generate draft," edit it, and approve.
Switch to the **Audit** tab to see the lifecycle trail plus every LLM call's token
counts and estimated cost.

## 3. Deploying the backend to AWS

```bash
cd infra
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt

npx cdk bootstrap   # once per account/region
npx cdk deploy
```

This provisions: an S3 bucket, a `HaCorrespondence` DynamoDB table, a Lambda function
built from `backend/Dockerfile`, and an HTTP API. The deploy output prints `ApiUrl` —
put that (plus `/api`) into `frontend/.env` as `VITE_API_BASE_URL` to point the local
React app at the live backend for the demo.

The IAM policy attached to the Lambda grants `bedrock:InvokeModel`/`Converse` broadly
(`Resource: "*"`) rather than enumerating specific model/inference-profile ARNs — fine
for a hackathon demo account, but tighten before any production use.

If `us.anthropic.claude-sonnet-5` isn't enabled in your account, override it:

```bash
npx cdk deploy -c bedrock_model_id=<your-model-id>
```

(or just edit the `BEDROCK_MODEL_ID` environment value in `infra/stacks/backend_stack.py`).

## Architecture notes

- **PDF handling**: the raw PDF bytes are sent straight to Bedrock Converse as a
  `document` content block (`bedrock_client.call_tool(document_bytes=..., document_name=...)`)
  — no separate text-extraction library or page/paragraph pre-tagging. The model reads
  the PDF natively and reports back a page number + verbatim quote per question for
  traceability.
- **Agent pipeline** (`backend/app/services/agent_pipeline.py`) is two explicit,
  independently testable LLM calls plus three deterministic lookups in between — not an
  open-ended autonomous loop, which matters for a regulated-content use case where
  explainability is required:
  1. `extract_letter` — one Bedrock call over the whole PDF, returns letter metadata and
     every question tagged with its own `drug`.
  2. `match_registration_records` — **zero-LLM**, plain-Python fuzzy match of a
     question's `drug` against `mock_registration_records.json`, narrowed by the
     letter's issuing health authority when more than one registration shares a product
     name.
     `match_submission_content` — resolves the submission docs/datasets tied to the
     matched registration record(s) via their own `related_submission_doc_ids`.
     `match_historic_precedents` — resolves prior HA deficiencies/responses tied to the
     same application number as the matched registration record(s).
     All three are triggered together, explicitly, via `POST .../requests/{id}/link`
     after a human reviews the question.
  3. `draft_response` — one Bedrock call per request, using a template selected by
     health authority (`_select_template`), grounded only in the linked registration
     record(s), submission content, historic precedent, region terminology (FDA/EMA/
     Health Canada), and user direction.
- Every HTTP endpoint completes within one Bedrock call at most, comfortably inside API
  Gateway's 29s integration timeout — no Step Functions or async Lambda invokes needed
  at this scale (batch "from-path" ingestion is the exception: it's N Bedrock calls in
  one request, one per discovered document).
- Data model: one DynamoDB item per correspondence, holding all of its requests/drafts,
  a document-level `audit` list, and a document-level `invocations` list (tokens +
  estimated cost per Bedrock call) as a nested document (see `backend/app/models.py`).
- **Prompt caching**: `bedrock_client.call_tool` appends a `cachePoint` block after the
  system prompt by default, since `ha-extract-requests`/`ha-draft-response` are
  identical across every call of that kind. Verified end-to-end against real Bedrock:
  the first `extract` call on one letter reported `cache_write_input_tokens`, and the
  very next letter's `extract` call reported the identical count as
  `cache_read_input_tokens` — the system prompt was genuinely cached and reused. If a
  given prompt is under the model's minimum cacheable token count, Bedrock silently
  skips caching instead (no error) — not guaranteed to hit for every model/prompt
  combination, just confirmed for this one. **Requires `boto3>=1.43.0`** — older
  botocore service models reject the `cachePoint` content block with a
  `ParamValidationError`.
- **Multi-document ingestion**: `routes._ingest_one_document` is the single pipeline
  shared by both the direct multi-file upload and `POST /correspondence/from-path`
  (`batch_ingest.list_documents_at_path`, S3 via a paginated `list_objects_v2` or a
  local folder gated on `LOCAL_STORE`), so both entry points produce identical
  `Correspondence` records.
