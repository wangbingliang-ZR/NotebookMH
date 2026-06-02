"""core/rag.py — 混合检索 (BM25 + dense + RRF)"""
import logging
from typing import Optional

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from config import RAG_TOP_K, RERANK_TOP_K, BM25_WEIGHT, DENSE_WEIGHT
from core.db import db_manager
from core.vector_store import vector_store

log = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    # lcut_for_search 对未登录词保留原词同时切出细粒度结果，更适合作检索
    return [t for t in jieba.lcut_for_search(text) if t.strip()]


def _bm25_search(query: str, vault_uuid: str,
                 source_hashes: Optional[list[str]], top_k: int) -> list[dict]:
    candidates: list[dict] = []
    docs = db_manager.list_documents(vault_uuid)
    for d in docs:
        if source_hashes and d.content_hash not in source_hashes:
            continue
        chunks = db_manager.get_chunks(vault_uuid, d.content_hash)
        for c in chunks:
            candidates.append({
                "doc_hash": d.content_hash,
                "chunk_index": c.chunk_index,
                "chunk_text": c.chunk_text,
                "file_name": d.file_name,
            })
    if not candidates:
        return []
    corpus = [_tokenize(c["chunk_text"]) for c in candidates]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(scores, candidates), key=lambda x: -x[0])[:top_k * 2]
    return [{**c, "score": float(s)} for s, c in ranked if s > 0]


def _enrich_dense_results(dense: list[dict], vault_uuid: str) -> list[dict]:
    """给 dense 结果补 file_name（vector_store 默认不带）"""
    if not dense:
        return []
    hash_to_name = {d.content_hash: d.file_name
                    for d in db_manager.list_documents(vault_uuid)}
    for item in dense:
        item["file_name"] = hash_to_name.get(item.get("doc_hash"), "?")
    return dense


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """计算两个归一化向量的余弦相似度。"""
    return float(np.dot(a, b))


def _semantic_rerank(query: str, candidates: list[dict],
                   top_k: int = RERANK_TOP_K) -> list[dict]:
    """用 embedding 余弦相似度做语义重排序。"""
    if not candidates:
        return []
    q_emb = vector_store.embed_text(query)
    scored = []
    for c in candidates:
        c_emb = vector_store.embed_text(c["chunk_text"])
        sim = _cosine_sim(q_emb, c_emb)
        scored.append({**c, "rerank_score": sim})
    scored.sort(key=lambda x: -x["rerank_score"])
    return scored[:top_k]


def _rrf_merge(dense: list[dict], sparse: list[dict],
               k: int = 60, top_k: int = 5) -> list[dict]:
    scores: dict = {}
    for rank, item in enumerate(dense):
        key = f"{item['doc_hash']}_{item['chunk_index']}"
        scores.setdefault(key, {"item": item, "score": 0.0})
        scores[key]["score"] += DENSE_WEIGHT / (k + rank + 1)
    for rank, item in enumerate(sparse):
        key = f"{item['doc_hash']}_{item['chunk_index']}"
        scores.setdefault(key, {"item": item, "score": 0.0})
        scores[key]["score"] += BM25_WEIGHT / (k + rank + 1)
    merged = sorted(scores.values(), key=lambda x: -x["score"])[:top_k]
    return [{**m["item"], "rrf_score": m["score"]} for m in merged]


async def retrieve(query: str, vault_uuid: str, top_k: int = RAG_TOP_K,
                   source_hashes: Optional[list[str]] = None) -> list[dict]:
    if not query.strip() or not vault_uuid:
        return []
    try:
        dense = vector_store.query(vault_uuid, query, top_k=top_k * 2,
                                   source_hashes=source_hashes)
        dense = _enrich_dense_results(dense, vault_uuid)
    except Exception as e:
        log.warning("dense retrieval failed: %s", e)
        dense = []
    try:
        sparse = _bm25_search(query, vault_uuid, source_hashes, top_k)
    except Exception as e:
        log.warning("bm25 retrieval failed: %s", e)
        sparse = []
    merged = _rrf_merge(dense, sparse, top_k=top_k)
    # 语义重排序：从 RRF top_k 中再精选语义最相关的
    return _semantic_rerank(query, merged, top_k=RERANK_TOP_K)
