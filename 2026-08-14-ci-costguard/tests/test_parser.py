import json
import logging
from pathlib import Path
from typing import Iterator, List

import pytest

from src.core.models import TokenRecord
from src.core.parser import ProviderParser, parse_file, register_parser, _registry  # type: ignore


class DummyParser(ProviderParser):
    """Simple parser that reads JSON lines and yields TokenRecord objects."""

    @staticmethod
    def supported_extensions() -> set[str]:
        return {".dummylog"}

    def parse(self, file_path: Path) -> Iterator[TokenRecord]:
        with file_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield TokenRecord(
                        timestamp=data["timestamp"],
                        provider=data["provider"],
                        model=data["model"],
                        prompt_tokens=int(data["prompt_tokens"]),
                        completion_tokens=int(data["completion_tokens"]),
                        total_tokens=int(data["total_tokens"]),
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logging.getLogger(__name__).warning(
                        "Failed to parse line %d in %s: %s", line_no, file_path, exc
                    )
                    continue


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Ensure the dummy parser does not leak into other tests."""
    yield
    _registry.pop(".dummylog", None)


def test_register_parser_adds_supported_extension(tmp_path: Path) -> None:
    register_parser(DummyParser())
    dummy_file = tmp_path / "sample.dummylog"
    dummy_file.write_text(
        json.dumps(
            {
                "timestamp": "2023-01-01T00:00:00Z",
                "provider": "dummy",
                "model": "test-model",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        )
    )
    records = list(parse_file(dummy_file))
    assert len(records) == 1
    assert records[0].provider == "dummy"


def test_parse_file_uses_correct_parser(tmp_path: Path) -> None:
    register_parser(DummyParser())
    dummy_file = tmp_path / "log.dummylog"
    dummy_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2023-01-01T00:00:00Z",
                        "provider": "dummy",
                        "model": "m1",
                        "prompt_tokens": 1,
                        "completion_tokens": 2,
                        "total_tokens": 3,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2023-01-01T00:01:00Z",
                        "provider": "dummy",
                        "model": "m2",
                        "prompt_tokens": 4,
                        "completion_tokens": 5,
                        "total_tokens": 9,
                    }
                ),
            ]
        )
    )
    iterator = parse_file(dummy_file)
    first = next(iterator)
    second = next(iterator)
    assert first.model == "m1"
    assert second.total_tokens == 9


def test_parse_file_unsupported_extension_raises(tmp_path: Path) -> None:
    unknown_file = tmp_path / "unknown.txt"
    unknown_file.write_text("irrelevant content")
    with pytest.raises(ValueError, match="No parser registered for extension"):
        parse_file(unknown_file)


def test_parser_skips_malformed_line_and_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    register_parser(DummyParser())
    bad_file = tmp_path / "mixed.dummylog"
    bad_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2023-01-01T00:00:00Z",
                        "provider": "dummy",
                        "model": "good",
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    }
                ),
                "this is not json",
                json.dumps(
                    {
                        "timestamp": "2023-01-01T00:02:00Z",
                        "provider": "dummy",
                        "model": "also_good",
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    }
                ),
            ]
        )
    )
    caplog.set_level(logging.WARNING)
    records = list(parse_file(bad_file))
    assert len(records) == 2
    assert all(isinstance(r, TokenRecord) for r in records)
    warning_messages = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("Failed to parse line 2" in msg for msg in warning_messages)


def test_parser_multiple_files_aggregation(tmp_path: Path) -> None:
    register_parser(DummyParser())
    files: List[Path] = []
    for i in range(3):
        p = tmp_path / f"file{i}.dummylog"
        p.write_text(
            json.dumps(
                {
                    "timestamp": f"2023-01-01T00:0{i}:00Z",
                    "provider": "dummy",
                    "model": f"model{i}",
                    "prompt_tokens": i + 1,
                    "completion_tokens": i + 2,
                    "total_tokens": (i + 1) + (i + 2),
                }
            )
        )
        files.append(p)

    all_records: List[TokenRecord] = []
    for f in files:
        all_records.extend(parse_file(f))

    assert len(all_records) == 3
    totals = [r.total_tokens for r in all_records]
    assert totals == [3, 6, 9]  # (1+2), (2+3), (3+4)


def test_parser_deregistration_prevents_future_parsing(tmp_path: Path) -> None:
    parser_instance = DummyParser()
    register_parser(parser_instance)
    dummy_file = tmp_path / "temp.dummylog"
    dummy_file.write_text(
        json.dumps(
            {
                "timestamp": "2023-01-01T00:00:00Z",
                "provider": "dummy",
                "model": "temp",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            }
        )
    )
    # Ensure it works while registered
    assert list(parse_file(dummy_file))

    # Remove registration manually
    _registry.pop(".dummylog", None)

    with pytest.raises(ValueError, match="No parser registered for extension"):
        parse_file(dummy_file)