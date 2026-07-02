import os
import json
import logging
import math
from typing import List, Dict, Tuple, Optional, Any

from src.core.models import _logger, register_hook, Hook

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _discover_config(start_dir: str, filename: str) -> Optional[str]:
    """
    Walk upwards from ``start_dir`` looking for a JSON file named ``filename``.
    Returns the absolute path if found, otherwise ``None``.
    """
    current = os.path.abspath(start_dir)
    root = os.path.abspath(os.sep)

    while True:
        candidate = os.path.join(current, filename)
        if os.path.isfile(candidate):
            return candidate
        if current == root:
            break
        current = os.path.dirname(current)
    return None


def _load_json(path: str) -> Dict[str, Any]:
    """
    Load a JSON file securely. Errors are logged and an empty dict is returned.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to load JSON config %s: %s", path, exc)
        return {}


def _tokenize(text: str) -> List[str]:
    """
    Very small tokenizer: lower‑case and split on whitespace.
    """
    return text.lower().split()


def _sentence_similarity(a: str, b: str) -> float:
    """
    Compute a simple Jaccard similarity between two sentences based on token sets.
    """
    set_a = set(_tokenize(a))
    set_b = set(_tokenize(b))
    if not set_a or not set_b:
        return 0.0
    intersection = set_a.intersection(set_b)
    union = set_a.union(set_b)
    return len(intersection) / len(union)


def _build_similarity_matrix(
    sentences: List[str], use_numpy: bool
) -> Tuple[Any, int]:
    """
    Build a symmetric similarity matrix for the given sentences.
    Returns the matrix and the number of sentences.
    """
    n = len(sentences)
    if use_numpy:
        try:
            import numpy as np

            mat = np.zeros((n, n), dtype=float)
            for i in range(n):
                for j in range(i + 1, n):
                    sim = _sentence_similarity(sentences[i], sentences[j])
                    mat[i, j] = sim
                    mat[j, i] = sim
            return mat, n
        except Exception as exc:  # pragma: no cover
            _logger.error("NumPy import or matrix build failed: %s", exc)
            # Fall back to pure‑Python matrix
    # Pure‑Python fallback
    mat = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim = _sentence_similarity(sentences[i], sentences[j])
            mat[i][j] = sim
            mat[j][i] = sim
    return mat, n


def _pagerank(
    matrix: Any,
    n: int,
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
    use_numpy: bool = False,
) -> List[float]:
    """
    Compute PageRank scores from a similarity matrix.
    """
    if use_numpy:
        import numpy as np

        # Convert similarity to transition probabilities
        row_sums = matrix.sum(axis=1, keepdims=True)
        # Avoid division by zero
        row_sums[row_sums == 0] = 1.0
        transition = matrix / row_sums
        rank = np.full((n,), 1.0 / n, dtype=float)

        for _ in range(max_iter):
            new_rank = (1 - damping) / n + damping * transition.T.dot(rank)
            if np.linalg.norm(new_rank - rank, ord=1) < tol:
                break
            rank = new_rank
        return rank.tolist()
    # Pure‑Python implementation
    transition = [
        [0.0 for _ in range(n)] for _ in range(n)
    ]  # probability matrix
    for i in range(n):
        row_sum = sum(matrix[i])
        if row_sum == 0:
            transition[i] = [1.0 / n] * n
        else:
            transition[i] = [matrix[i][j] / row_sum for j in range(n)]

    rank = [1.0 / n] * n
    for _ in range(max_iter):
        new_rank = [(1 - damping) / n] * n
        for i in range(n):
            for j in range(n):
                new_rank[i] += damping * transition[j][i] * rank[j]
        diff = sum(abs(new_rank[i] - rank[i]) for i in range(n))
        if diff < tol:
            break
        rank = new_rank
    return rank


# --------------------------------------------------------------------------- #
# Summarizer implementation
# --------------------------------------------------------------------------- #


class Summarizer:
    """
    Provides extractive summarization via TextRank.  An optional NumPy‑accelerated
    backend can be enabled by passing ``use_numpy=True`` or by installing NumPy.
    """

    _DEFAULT_CONFIG = {
        "ratio": 0.2,
        "use_numpy": False,
        "hooks": [],
    }

    def __init__(self, config_dir: Optional[str] = None) -> None:
        """
        Initialise the summarizer, loading optional configuration from the nearest
        ``summarizer_config.json`` file.  The configuration may override the default
        ``ratio`` and ``use_numpy`` values.
        """
        self.config = self._load_config(config_dir)
        self.ratio: float = float(self.config.get("ratio", 0.2))
        self.use_numpy: bool = bool(self.config.get("use_numpy", False))

        # Register any hooks defined in the config
        for hook_path in self.config.get("hooks", []):
            self._register_external_hook(hook_path)

    def _load_config(self, start_dir: Optional[str]) -> Dict[str, Any]:
        """
        Locate and parse a JSON configuration file.  If none is found, the defaults
        are returned.
        """
        if start_dir is None:
            start_dir = os.getcwd()
        cfg_path = _discover_config(start_dir, "summarizer_config.json")
        if cfg_path:
            cfg = _load_json(cfg_path)
            if isinstance(cfg, dict):
                return {**self._DEFAULT_CONFIG, **cfg}
        return self._DEFAULT_CONFIG.copy()

    def _register_external_hook(self, dotted_path: str) -> None:
        """
        Dynamically import a callable given a dotted path (e.g. ``module.attr``) and
        register it as a ``summarizer`` hook.  Errors are logged but do not abort
        execution.
        """
        try:
            module_path, attr_name = dotted_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[attr_name])
            func = getattr(module, attr_name)
            if callable(func):
                register_hook("summarizer", func)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            _logger.error("Failed to register summarizer hook %s: %s", dotted_path, exc)

    def summarize(self, sentences: List[str], ratio: Optional[float] = None) -> List[str]:
        """
        Return the top‑ranked sentences that cover ``ratio`` of the original content.
        If an error occurs, a simple lead‑sentence heuristic is used as a fallback.
        """
        if not sentences:
            return []

        effective_ratio = self.ratio if ratio is None else float(ratio)
        try:
            # Build similarity matrix (NumPy if requested and available)
            matrix, n = _build_similarity_matrix(sentences, self.use_numpy)
            scores = _pagerank(matrix, n, use_numpy=self.use_numpy)

            # Pair each sentence with its score and sort descending
            scored = list(zip(scores, sentences))
            scored.sort(key=lambda pair: pair[0], reverse=True)

            # Determine number of sentences to keep
            keep = max(1, int(math.ceil(effective_ratio * len(sentences))))
            top_sentences = [sent for _, sent in scored[:keep]]

            # Preserve original order for readability
            sentence_set = set(top_sentences)
            ordered = [s for s in sentences if s in sentence_set]

            # Allow external hooks to modify the result
            for hook in register_hook.get("summarizer", []):
                try:
                    result = hook(ordered)  # type: ignore[call-arg]
                    if isinstance(result, list):
                        ordered = result
                except Exception as exc:  # pragma: no cover
                    _logger.error("Summarizer hook %s failed: %s", hook, exc)

            return ordered
        except Exception as exc:  # pragma: no cover
            _logger.error("Summarization failed: %s", exc)
            # Fallback: return the leading ``keep`` sentences
            keep = max(1, int(math.ceil(effective_ratio * len(sentences))))
            return sentences[:keep]


# --------------------------------------------------------------------------- #
# Example hook registration (users can add their own via config)
# --------------------------------------------------------------------------- #


def _default_length_filter(sentences: List[str]) -> List[str]:
    """
    Simple hook that removes sentences shorter than 5 words.
    """
    return [s for s in sentences if len(_tokenize(s)) >= 5]


# Register the built‑in hook so it runs after every summarization pass.
register_hook("summarizer", _default_length_filter)