"""Example usage of guizang-visualizer end‑to‑end pipeline."""

import sys
import pathlib
from uuid import uuid4

from src.core.models import IllustrationRequest
from src.core.engine import SkillEngine
from src.memory import MemoryStore


def main() -> None:
    """Run a minimal illustration request through the full pipeline."""
    request = IllustrationRequest(
        request_id=str(uuid4()),
        input_type="text",
        raw_content="示例文本用于生成图表",
        target_use="slide",
        custom_accent="#FF5733",
    )

    # Use an in‑memory SQLite database to avoid side effects on disk.
    memory = MemoryStore(db_path=":memory:")
    engine = SkillEngine(memory=memory)

    try:
        result = engine.run(request)
    except Exception as exc:  # noqa: BLE001
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Write the generated image to a file for manual inspection.
    output_dir = pathlib.Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{request.request_id}.png"
    image_path.write_bytes(result.image_bytes)

    print(f"Illustration saved to {image_path}")
    print(f"Prompt used: {result.prompt_used}")
    print(f"QA passed: {result.qa_report.passed}")


if __name__ == "__main__":
    main()