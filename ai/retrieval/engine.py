"""实现离线可复现的字符 n-gram 向量检索基线。"""

from __future__ import annotations

from hashlib import blake2b
from math import sqrt
import re


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")
EMBEDDING_DIMENSION = 192


def chunk_text(text: str, size: int = 700, overlap: int = 100) -> list[tuple[str, str]]:
    """把文档切为带字符位置的重叠片段。

    重叠区保留跨段语义，位置字符串用于回答中展示精确引用范围。
    """

    normalized = re.sub(r"\r\n?", "\n", text).strip()
    if not normalized:
        return []
    if size < 100 or overlap < 0 or overlap >= size:
        raise ValueError("切分参数必须满足 size>=100 且 0<=overlap<size")
    chunks: list[tuple[str, str]] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary
        content = normalized[start:end].strip()
        if content:
            chunks.append((content, f"字符 {start + 1}-{end}"))
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _tokens(text: str) -> list[str]:
    """生成兼顾中文单字和英文单词的稳定 token 序列。"""

    basic = [token.lower() for token in TOKEN_PATTERN.findall(text)]
    chinese = [token for token in basic if len(token) == 1 and "\u3400" <= token <= "\u9fff"]
    return basic + ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]


def embed_text(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """用带符号哈希投影生成可持久化、无需外部模型的稀疏向量。"""

    if dimension < 32:
        raise ValueError("向量维度不能小于 32")
    vector = [0.0] * dimension
    for token in _tokens(text):
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        vector[bucket] += 1.0 if digest[4] % 2 == 0 else -1.0
    norm = sqrt(sum(value * value for value in vector))
    return vector if norm == 0 else [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算等长归一化向量的余弦相似度。"""

    if len(left) != len(right):
        raise ValueError("向量维度不一致")
    return sum(a * b for a, b in zip(left, right, strict=True))
