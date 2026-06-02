"""core/vector_store.py — ChromaDB 向量存储"""
import logging
from typing import Optional

import chromadb
import numpy as np
from chromadb.config import Settings

from config import CHROMA_DIR, EMBEDDING_MODEL, USE_SEMANTIC_EMBEDDING

log = logging.getLogger(__name__)

# 尝试加载 sentence-transformers，失败则回退到 HashingVectorizer
try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except ImportError:
    _HAS_ST = False


class VectorStore:
    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._model = None  # lazy load
        self._vectorizer = None  # fallback
        # 是否使用语义模型；配置禁用或库未安装时直接用 HashingVectorizer
        self._use_st = USE_SEMANTIC_EMBEDDING and _HAS_ST
        if not self._use_st:
            log.info("语义模型已禁用或未安装，使用 HashingVectorizer。")

    def _build_vectorizer(self):
        if self._vectorizer is None:
            from sklearn.feature_extraction.text import HashingVectorizer
            self._vectorizer = HashingVectorizer(
                n_features=384, alternate_sign=False, norm='l2',
                ngram_range=(1, 2), analyzer='char_wb',
            )
        return self._vectorizer

    def _load_model(self):
        """仅从本地缓存加载模型，绝不联网下载。失败则永久降级。"""
        if self._model is None and self._use_st:
            try:
                log.info("Loading embedding model (local cache only): %s",
                         EMBEDDING_MODEL)
                self._model = SentenceTransformer(
                    EMBEDDING_MODEL, local_files_only=True,
                )
            except Exception as e:
                log.warning("语义模型未缓存或加载失败，降级为 HashingVectorizer: %s", e)
                self._use_st = False
                self._build_vectorizer()
        return self._model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._use_st:
            m = self._load_model()
            if m is not None:
                return m.encode(texts, normalize_embeddings=True,
                                convert_to_numpy=True,
                                show_progress_bar=False).tolist()
        # 降级路径：HashingVectorizer（同为 384 维，与 collection 兼容）
        return self._build_vectorizer().transform(texts).toarray().tolist()

    def embed_text(self, text: str) -> list[float]:
        """对外暴露单文本 embedding 接口（供 reranker 使用）。"""
        return self._embed([text])[0]

    def _collection_name(self, vault_uuid: str) -> str:
        # 降级使用 HashingVectorizer，与旧库编码兼容，沿用原集合名
        return f"vault_{vault_uuid}"

    def _get_collection(self, vault_uuid: str):
        return self._client.get_or_create_collection(
            name=self._collection_name(vault_uuid),
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, vault_uuid: str, doc_hash: str, chunks: list[dict]) -> None:
        if not chunks:
            return
        coll = self._get_collection(vault_uuid)
        texts = [c["chunk_text"] for c in chunks]
        embeddings = self._embed(texts)
        ids = [f"{doc_hash}_{c['chunk_index']}" for c in chunks]
        metadatas = [{
            "doc_hash": doc_hash,
            "chunk_index": int(c["chunk_index"]),
            "source_page": int(c.get("source_page", 0)),
            "header": str(c.get("header_hierarchy", "")),
        } for c in chunks]
        coll.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    def query(self, vault_uuid: str, query_text: str, top_k: int = 5,
              source_hashes: Optional[list[str]] = None) -> list[dict]:
        coll = self._get_collection(vault_uuid)
        emb = self._embed([query_text])[0]
        where = None
        if source_hashes:
            where = {"doc_hash": {"$in": source_hashes}}
        try:
            res = coll.query(query_embeddings=[emb], n_results=top_k, where=where)
        except Exception as e:
            log.warning("Chroma query failed: %s", e)
            return []
        out = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, _id in enumerate(ids):
            out.append({
                "chunk_text": docs[i],
                "doc_hash": metas[i].get("doc_hash"),
                "chunk_index": metas[i].get("chunk_index"),
                "score": 1.0 - float(dists[i]) if i < len(dists) else 0.0,
            })
        return out

    def delete(self, vault_uuid: str, doc_hash: str) -> None:
        try:
            coll = self._get_collection(vault_uuid)
            coll.delete(where={"doc_hash": doc_hash})
        except Exception as e:
            log.warning("Chroma delete failed: %s", e)

    def delete_collection(self, vault_uuid: str) -> None:
        try:
            self._client.delete_collection(self._collection_name(vault_uuid))
        except Exception:
            pass


vector_store = VectorStore()
