"""Standalone manual test: calls the agent pipeline directly (no FastAPI, no
uvicorn, no HTTP) against one sample letter, printing each step's result to
the terminal. Run from backend/ with the venv active and real AWS credentials
set (Bedrock calls are real)."""

import sys
from pathlib import Path

from app.services import agent_pipeline

LETTERS_DIR = Path(__file__).resolve().parent.parent / "Hack_2026_001 - HA Request & Response Agents"
DEFAULT_FILENAME = "Deficiency_Letter_example4_lv.pdf"
SAMPLE_PDF = LETTERS_DIR / (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILENAME)


def main() -> None:
    print(f"Reading {SAMPLE_PDF.name} ...")
    pdf_bytes = SAMPLE_PDF.read_bytes()

    print("\n=== STEP 1: extract_letter ===")
    meta, requests, usage = agent_pipeline.extract_letter(pdf_bytes, SAMPLE_PDF.name)
    print(f"applicant={meta.applicant!r} source={meta.source!r}")
    print(f"found {len(requests)} request(s); tokens in={usage.input_tokens} out={usage.output_tokens}")
    for r in requests:
        print(f"  [{r.request_id}] drug={r.drug!r} section={r.section!r}")

    request = requests[0]
    print(f"\nUsing request [{request.request_id}] drug={request.drug!r} for link/draft steps.")

    print("\n=== STEP 2: link_request (agent-orchestrated) ===")
    linked_registration, linked_submissions, linked_precedents, link_usage = agent_pipeline.link_request(
        request.drug, meta.source
    )
    print(f"tokens in={link_usage.input_tokens} out={link_usage.output_tokens}")
    print(f"linked_registration: {[r.registration_id for r in linked_registration]}")
    print(f"linked_submissions:  {[s.doc_id for s in linked_submissions]}")
    print(f"linked_precedents:   {[p.precedent_id for p in linked_precedents]}")

    print("\n=== STEP 3: draft_response (agent-orchestrated) ===")
    from app.models import HaRequest

    ha_request = HaRequest(**request.model_dump())
    draft, draft_usage = agent_pipeline.draft_response(
        ha_request,
        linked_registration,
        linked_submissions,
        linked_precedents,
        meta,
        direction="We will submit a CAPA plan within 90 days.",
    )
    print(f"tokens in={draft_usage.input_tokens} out={draft_usage.output_tokens}")
    print(f"template_id: {draft.template_id}")
    print(f"citations:   {draft.citations}")
    print("\n--- draft text ---")
    print(draft.text)

    print("\n=== DONE ===")
    if link_usage.input_tokens == 0 or draft_usage.input_tokens == 0:
        print("WARNING: a step reported 0 tokens -- the agent likely didn't run its tool loop correctly.")
    if draft.template_id is None:
        print("WARNING: template_id is None -- select_template_tool was probably never called.")


if __name__ == "__main__":
    main()
