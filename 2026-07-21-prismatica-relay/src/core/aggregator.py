import logging
from typing import Dict, Iterable, List, Mapping, Optional, Set

from pydantic import BaseModel, ValidationError

from src.core.models import ApiResponse, AggregatedResult, ErrorDetail, MetadataItem

logger = logging.getLogger(__name__)


class ResultAggregator:
    """
    Collects asynchronous sub‑responses, de‑duplicates, merges, and normalises them into the final payload.
    """

    def __init__(self) -> None:
        """
        Initialise the aggregator. No external state is required; the class is stateless and can be reused.
        """
        self._fingerprint_cache: Set[str] = set()
        logger.debug("ResultAggregator instantiated")

    @staticmethod
    def _fingerprint(item: MetadataItem) -> str:
        """
        Produce a deterministic fingerprint for a metadata item.
        The combination of ``id`` and ``source`` uniquely identifies an item across upstream providers.
        """
        return f"{item.id}|{item.source}"

    def deduplicate(self, items: Iterable[MetadataItem]) -> List[MetadataItem]:
        """
        Remove duplicate entries based on a deterministic fingerprint.
        The first occurrence of each fingerprint is retained; subsequent duplicates are discarded.
        """
        unique_items: List[MetadataItem] = []
        seen: Set[str] = set()
        for item in items:
            fp = self._fingerprint(item)
            if fp in seen:
                logger.debug("Duplicate filtered: %s", fp)
                continue
            seen.add(fp)
            unique_items.append(item)
        logger.info("Deduplicated %d items to %d unique items", len(list(items)), len(unique_items))
        return unique_items

    @staticmethod
    def _rank_items(items: List[MetadataItem]) -> List[MetadataItem]:
        """
        Apply simple ranking heuristics to the list of metadata items.
        Currently items are sorted alphabetically by title; more sophisticated heuristics can be added later.
        """
        return sorted(items, key=lambda i: i.title.lower())

    def _collect_errors(self, responses: List[ApiResponse]) -> List[ErrorDetail]:
        """
        Extract error details from the list of ApiResponse objects.
        Only non‑retryable errors are retained for the final payload; retryable errors are logged and omitted.
        """
        errors: List[ErrorDetail] = []
        for resp in responses:
            if resp.error is None:
                continue
            if resp.error.retryable:
                logger.warning(
                    "Retryable upstream error ignored for aggregation: %s (%s)",
                    resp.error.code,
                    resp.error.message,
                )
                continue
            errors.append(resp.error)
        return errors

    def aggregate(self, responses: List[ApiResponse]) -> AggregatedResult:
        """
        Merge fields, resolve conflicts, and apply ranking heuristics to produce the final aggregated result.
        """
        if not isinstance(responses, list):
            raise TypeError("responses must be a list of ApiResponse objects")

        # Separate successful payloads from error responses
        successful_items: List[MetadataItem] = []
        for resp in responses:
            if resp.status >= 200 and resp.status < 300 and resp.payload:
                successful_items.extend(resp.payload)
            else:
                logger.debug(
                    "Non‑2xx response received: status=%s, error=%s",
                    resp.status,
                    resp.error.code if resp.error else "none",
                )

        # Deduplicate and rank
        deduped_items = self.deduplicate(successful_items)
        ranked_items = self._rank_items(deduped_items)

        # Determine partial success flag
        partial_success = any(
            resp.status < 200 or resp.status >= 300 for resp in responses
        ) and len(ranked_items) > 0

        # Collect non‑retryable errors for reporting
        errors = self._collect_errors(responses)

        try:
            result = AggregatedResult(
                partial_success=partial_success,
                results=ranked_items,
                errors=errors if errors else None,
            )
        except ValidationError as exc:
            # This should never happen if models are defined correctly; log and raise a runtime error.
            logger.error("AggregatedResult validation failed: %s", exc)
            raise RuntimeError("Failed to construct AggregatedResult") from exc

        logger.info(
            "Aggregation completed: %d results, %d errors, partial_success=%s",
            len(ranked_items),
            len(errors),
            partial_success,
        )
        return result