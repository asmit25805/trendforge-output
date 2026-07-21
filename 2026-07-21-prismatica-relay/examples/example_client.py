import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx

from src.core.models import AggregatedResult, ApiResponse, ErrorDetail, MetadataItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("example_client")


def build_query(targets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Construct a metadata query payload.

    The payload follows the schema expected by the ``/metadata`` endpoint:
    ``{"targets": [{ "endpoint": "...", "params": {...}, "timeout_ms": ... }, ...]}``
    """
    return {"targets": targets}


def load_targets_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    Load a list of target specifications from a JSON file.

    The file must contain an array of objects with at least ``endpoint`` and ``params`` keys.
    """
    if not file_path.is_file():
        logger.error("Target file %s does not exist.", file_path)
        raise FileNotFoundError(f"Target file {file_path} not found")
    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        logger.error("Target file %s does not contain a JSON array.", file_path)
        raise ValueError("Target file must contain a JSON array")
    return data


def send_metadata_request(
    base_url: str,
    payload: Dict[str, Any],
    timeout: float = 10.0,
) -> httpx.Response:
    """
    POST the metadata query to the server and return the raw HTTP response.

    ``base_url`` should include scheme and host, e.g. ``http://localhost:8000``.
    """
    url = f"{base_url.rstrip('/')}/metadata"
    logger.info("Sending POST request to %s", url)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
    logger.debug("Received response: %s %s", response.status_code, response.text)
    return response


def parse_success_response(data: Dict[str, Any]) -> AggregatedResult:
    """
    Convert a successful JSON payload into an ``AggregatedResult`` instance.
    """
    items_data = data.get("items", [])
    errors_data = data.get("errors", [])
    items = [
        MetadataItem(
            id=item["id"],
            title=item["title"],
            tags=item.get("tags", []),
            thumbnail_url=item["thumbnail_url"],
            source=item["source"],
        )
        for item in items_data
    ]
    errors = [
        ErrorDetail(
            code=err["code"],
            message=err["message"],
            retryable=err.get("retryable", False),
        )
        for err in errors_data
    ]
    return AggregatedResult(
        items=items,
        partial_success=data.get("partial_success", False),
        errors=errors,
    )


def parse_error_response(data: Dict[str, Any]) -> ErrorDetail:
    """
    Convert an error JSON payload into an ``ErrorDetail`` instance.
    """
    return ErrorDetail(
        code=data.get("code", "unknown_error"),
        message=data.get("message", "An unknown error occurred"),
        retryable=data.get("retryable", False),
    )


def handle_response(response: httpx.Response) -> None:
    """
    Interpret the HTTP response, print a human‑readable summary, and exit with an appropriate status.
    """
    if response.status_code == 200:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from successful response.")
            sys.exit(1)
        result = parse_success_response(payload)
        print_aggregated_result(result)
        sys.exit(0)
    elif 400 <= response.status_code < 600:
        try:
            error_payload = response.json()
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from error response.")
            sys.exit(1)
        error = parse_error_response(error_payload)
        logger.error(
            "Request failed with %s: %s (retryable=%s)",
            error.code,
            error.message,
            error.retryable,
        )
        sys.exit(1)
    else:
        logger.error("Unexpected HTTP status %s received.", response.status_code)
        sys.exit(1)


def print_aggregated_result(result: AggregatedResult) -> None:
    """
    Output the aggregated result in a readable format.
    """
    header = "Aggregated Metadata Result"
    if result.partial_success:
        header += " (partial success)"
    print(header)
    print("-" * len(header))
    for item in result.items:
        tags = ", ".join(item.tags)
        print(
            f"ID: {item.id}\n"
            f"Title: {item.title}\n"
            f"Source: {item.source}\n"
            f"Tags: {tags}\n"
            f"Thumbnail: {item.thumbnail_url}\n"
            f"{'-'*40}"
        )
    if result.errors:
        print("\nErrors:")
        for err in result.errors:
            print(
                f"- Code: {err.code}\n"
                f"  Message: {err.message}\n"
                f"  Retryable: {err.retryable}\n"
            )


def main() -> None:
    """
    Entry point for the example client.

    It builds a query, sends it to the server, and processes the response.
    """
    # Example static targets; replace or load from a file for real use cases.
    example_targets = [
        {
            "endpoint": "https://api.example.org/v1/items",
            "params": {"category": "books"},
            "timeout_ms": 1500,
        },
        {
            "endpoint": "https://api.example.org/v1/articles",
            "params": {"tag": "science"},
        },
    ]

    # Allow optional external target definition via a JSON file.
    if len(sys.argv) > 1:
        target_file = Path(sys.argv[1])
        example_targets = load_targets_from_file(target_file)

    query_payload = build_query(example_targets)
    response = send_metadata_request(base_url="http://localhost:8000", payload=query_payload)
    handle_response(response)


if __name__ == "__main__":
    main()