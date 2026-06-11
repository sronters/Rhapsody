from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

TOKEN_PATTERN = re.compile(r"[\w']+", re.UNICODE)


class EmbeddingService:
    """Small deterministic embedding service used until production embedding APIs are wired in.

    The implementation uses feature hashing over normalized lexical tokens. It is intentionally
    deterministic, cheap, and dependency-free so tests/local development do not require a model
    server. The serialized vectors can later be replaced by pgvector values from a real embedding
    provider without changing the memory-service boundary.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 16:
            raise ValueError("Embedding dimensions must be at least 16.")
        self.dimensions = dimensions

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)
        if not tokens:
            return vector

        counts = Counter(tokens)
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign * (1.0 + math.log(count))
        return normalize_vector(vector)

    def serialize(self, vector: list[float]) -> list[float]:
        return [round(value, 6) for value in vector]

    def deserialize(self, payload: Sequence[float] | str | None) -> list[float] | None:
        if payload is None:
            return None
        if isinstance(payload, str):
            return parse_legacy_vector_string(payload)
        vector = list(payload)
        if not vector or not all(isinstance(item, int | float) for item in vector):
            return None
        return [float(item) for item in vector]

    def embed_for_storage(self, text: str) -> list[float]:
        return self.serialize(self.embed_text(text))

    def similarity(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True))


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def parse_legacy_vector_string(payload: str) -> list[float] | None:
    stripped = payload.strip().strip("[]")
    if not stripped:
        return None
    try:
        return [float(item) for item in stripped.split(",")]
    except ValueError:
        return None
