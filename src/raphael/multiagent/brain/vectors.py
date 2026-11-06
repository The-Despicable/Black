"""Local, dependency-free embeddings for semantic recall.

Hashed feature bag: word unigrams + bigrams + character trigrams, projected
into a fixed 384-dim space, L2-normalized. No model download, no torch, no
network. Good enough to find "past thinking about similar topics"; swap in a
real embedding model later by replacing `embed()`.
"""
from __future__ import annotations

import math
import re
from array import array
from typing import List

DIM = 384
_WORD = re.compile(r"[a-z0-9]+")


def _features(text: str) -> List[str]:
    words = _WORD.findall(text.lower())
    feats: List[str] = []
    feats.extend(words)
    feats.extend(f"{a}_{b}" for a, b in zip(words, words[1:]))
    for w in words:
        if len(w) > 3:
            padded = f"#{w}#"
            feats.extend(padded[i : i + 3] for i in range(len(padded) - 2))
    return feats


def embed(text: str) -> array:
    vec = array("f", bytes(4 * DIM))
    for f in _features(text):
        # stable, portable hash (FNV-1a)
        h = 2166136261
        for ch in f.encode("utf-8"):
            h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
        idx = h % DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    for i in range(DIM):
        vec[i] /= norm
    return vec


def to_blob(vec: array) -> bytes:
    return vec.tobytes()


def from_blob(blob: bytes) -> array:
    vec = array("f")
    vec.frombytes(bytes(blob))
    return vec


def cosine(a: array, b: array) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
