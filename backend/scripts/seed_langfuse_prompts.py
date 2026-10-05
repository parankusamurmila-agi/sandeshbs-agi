"""One-time push of the default prompts into Langfuse.

Run with LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY set so the prompt names
app.services.prompts.get_prompt looks up exist with a "production" label.
Safe to re-run -- each run creates a new version and re-labels it.

    cd backend && python -m scripts.seed_langfuse_prompts
"""

from langfuse import Langfuse

from app import config
from app.services.prompts import _local_prompts


def main() -> None:
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        raise SystemExit("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY first.")

    client = Langfuse(
        public_key=config.LANGFUSE_PUBLIC_KEY,
        secret_key=config.LANGFUSE_SECRET_KEY,
        host=config.LANGFUSE_HOST,
    )
    for name, text in _local_prompts().items():
        client.create_prompt(name=name, prompt=text, labels=["production"], type="text")
        print(f"seeded {name}")


if __name__ == "__main__":
    main()
