# HA Request & Response Agent

Hackathon prototype for **Hack_2026_001 — HA Request & Response Agents**: upload a
health-authority deficiency letter (PDF), have an agent extract every individual
request/deficiency with page-level source traceability, link relevant supporting
evidence, draft a grounded response, and let a human edit/approve with a full audit
trail.

- **Backend**: FastAPI, deployed as a Lambda container image behind API Gateway (HTTP API).
- **LLM**: AWS Bedrock, Claude Sonnet, via the Converse API with forced tool-use for
  reliable structured output (`backend/app/services/bedrock_client.py`).
- **Frontend**: React + TypeScript (Vite), run locally against the deployed API for the
  demo.
- **Infra**: AWS CDK (Python) — S3 (PDF storage), DynamoDB (correspondence records),
  Lambda, HTTP API.
- Submission content, registration/application tracking records, and historic precedent
  responses are **mocked** fixtures under `backend/app/data/` (small enough to pass in
  full to the model — no vector DB needed at this scale).

## Project flow

This builds on the existing Health Authority Interactions product, which already
converts incoming HA correspondence (email, letter) to PDF, imports it, and summarizes
it. This agent goes one level deeper — from "what does the letter say" to "what is the
health authority actually asking the applicant to do, and how do we respond."

1. **Intake** — a deficiency letter PDF is uploaded (`POST /api/correspondence`,
   `UploadPage.tsx` → `routes.upload_correspondence`). Text is pulled out paragraph by
   paragraph (`pdf_extractor.py`) and the raw PDF is stored.
2. **Extract structured requests** — rather than a flat summary, the agent identifies
   every distinct ask/deficiency as its own item: id, section, verbatim text, referenced
   documents/datasets, and the exact page/paragraph it came from
   (`agent_pipeline.extract_letter`, the `ExtractedRequest` model). Numbered items with
   lettered sub-parts (9a, 9b, ...) are split into separate requests, matching how an
   applicant tracks remediation items individually.
3. **Link to submission content and registration records** — each request is matched
   against a candidate pool of submission documents, historic precedent responses, and
   registration/application tracking records (application number, market, status,
   response due date), with a one-sentence rationale per match so a reviewer can see
   *why* something was pulled in (`agent_pipeline.link_evidence`). Backed by mock
   fixtures under `backend/app/data/` (`mock_submissions.json`,
   `mock_historic_responses.json`, `mock_registration_records.json`) standing in for the
   real HA Interactions / RIM data.
4. **Human-in-the-loop direction** — before drafting, a user can supply direction (e.g.
   "we will comply by providing X") via `DraftEditor.tsx` / `DraftRequestBody.direction`.
   This is where the applicant decides *what* they're going to do about an ask, not just
   what it says.
5. **Draft the response** — grounded only in the request text, linked evidence, the
   response template's section structure, and the user's direction; nothing fabricated
   (`agent_pipeline.draft_response`).
6. **Edit, approve, audit** — the draft is editable in place and explicitly approved
   (`PATCH .../draft`), with every drafted/edited/approved action timestamped in an
   `AuditEntry` (`AuditTrail.tsx`) — closing the loop from "letter received" to "response
   approved," with full traceability back to the source paragraph for each ask.

**Known gaps vs. the full ask** (flagged, not yet built):
- Requests aren't classified into a controlled deficiency-type taxonomy yet — `section`
  is free text copied from the letter's own heading, not a normalized category.
- Submission content, historic precedent, and registration/application tracking records
  are all mocked fixtures (`backend/app/data/`), not a live HA Interactions/RIM
  integration.
- There's only one response template (`templates.json`) and no way to select among
  several — `draft_response` always uses `templates[0]`.

## Prerequisites

- Python 3.12
- Node.js + npm (needed for both the React frontend and the AWS CDK CLI) — **not
  installed in the environment this was built in; install it before running the
  frontend or `cdk` commands.**
- Docker Desktop running (CDK builds the Lambda container image locally via Docker on `cdk deploy`)
- AWS CLI configured with an account that has Bedrock access to a Claude Sonnet model/
  inference profile in `us-east-1` (verify with `aws bedrock list-inference-profiles
  --region us-east-1`)

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

Run the test suite (unit tests for PDF extraction + agent pipeline, Bedrock mocked):

```bash
pytest
```

`tests/test_pdf_extractor.py` additionally exercises the real sample PDF if present at
`C:\Users\00005633\Downloads\2933_Intake001518.pdf` on the machine running the tests;
it's skipped automatically otherwise.

## 2. Frontend — local run

```bash
cd frontend
npm install
cp .env.example .env     # point VITE_API_BASE_URL at your local or deployed API
npm run dev
```

Open `http://localhost:5173`. Upload the sample PDF, watch the agent extract all 12
deficiency items (31 including lettered sub-items 9a–9p), click one, generate a draft,
edit it, and approve — the audit trail records each step.

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

- **PDF extraction** (`backend/app/services/pdf_extractor.py`) uses `pypdf` to pull text
  per page and groups lines into paragraphs, tagging each as `<p page="N" idx="K">`. This
  works for born-digital PDFs (like the FDA letter used here) without needing Textract/
  Document Intelligence OCR.
- **Agent pipeline** (`backend/app/services/agent_pipeline.py`) is three explicit,
  independently testable steps — not an open-ended autonomous loop, which matters for a
  regulated-content use case where explainability is required:
  1. `extract_requests` — one Bedrock call over the whole tagged letter.
  2. `link_evidence` — one Bedrock call per request, selecting from the mock submission/
     historic-precedent catalog.
  3. `draft_response` — one Bedrock call per request, grounded only in the linked
     evidence, template, user direction, and the request text.
- Every HTTP endpoint completes within a couple of Bedrock calls at most, comfortably
  inside API Gateway's 29s integration timeout — no Step Functions or async Lambda
  invokes needed at this scale.
- Data model: one DynamoDB item per correspondence, holding all of its requests/drafts/
  audit history as a nested document (see `backend/app/models.py`).
