"""
core/ontology_builder.py - DAG 本体抽取与无环校验 (Phase 1B+)

职责：
  - 从文档文本（前 N 页/字符）提取概念拓扑
  - 使用 LLM JSON Mode 输出结构化本体
  - 物理级无环校验：graphlib.TopologicalSorter + 自动剪环
  - 持久化到 SQLite concept_dependencies 表

约束：
  - 零 Streamlit 依赖
  - 异步非阻塞：Embedding 级别使用 asyncio.to_thread
  - SRP：独立于 IngestionPipeline 的向量切分逻辑
"""

import json
import logging
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, ValidationError

from core.llm_engine import UnifiedLLMEngine, get_llm_engine
from utils.db_manager import db_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Pydantic Schema —— 强制 LLM 输出结构
# ---------------------------------------------------------------------------

class ConceptNode(BaseModel):
    """单个概念节点：名称、前置依赖、摘要。"""

    concept_name: str = Field(..., description="概念名称，如 '梯度下降'")
    depends_on: List[str] = Field(
        default_factory=list,
        description="直接前置依赖概念列表（必须在该概念之前掌握）",
    )
    summary: str = Field(
        default="",
        description="一句话摘要，说明该概念的核心含义",
    )


class DocumentOntology(BaseModel):
    """文档本体：完整 DAG。"""

    dag: List[ConceptNode] = Field(
        ...,
        description="文档中抽取出的所有概念节点及其依赖关系",
    )


# ---------------------------------------------------------------------------
# 2. OntologyBuilder —— 本体构建器
# ---------------------------------------------------------------------------

class OntologyBuilder:
    """
    本体构建器。

    核心流程：
      1. 截断文档前 N 字符（目录/前言）
      2. LLM 结构化提取 DocumentOntology
      3. graphlib 无环校验
      4. 自动剪环（熔断）
      5. 持久化到 DAO
    """

    _MAX_HEAD_CHARS: int = 12000  # 约等于 10 页 A4 文本
    _LLM_TEMPERATURE: float = 0.3   # 低温度确保确定性输出

    def __init__(self, llm: Optional[UnifiedLLMEngine] = None) -> None:
        self._llm = llm or get_llm_engine()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def extract_from_document(
        self,
        text: str,
        vault_uuid: str,
        doc_hash: str,
    ) -> DocumentOntology:
        """
        从文档提取本体并持久化。

        Args:
            text: 文档纯文本。
            vault_uuid: 所属笔记库。
            doc_hash: 文档 SHA-256 哈希（用于溯源）。

        Returns:
            经无环校验后的 DocumentOntology。
        """
        # 1. 截断前 N 字符
        head_text = text[: self._MAX_HEAD_CHARS]

        # 2. LLM 结构化提取
        raw_ontology = await self._llm_extract(head_text)

        # 3. 无环校验 + 剪环
        cleaned = self._ensure_acyclic(raw_ontology)

        # 4. 持久化
        self._persist(vault_uuid, doc_hash, cleaned)

        logger.info(
            "Ontology extracted: vault=%s doc=%s concepts=%d",
            vault_uuid,
            doc_hash[:16],
            len(cleaned.dag),
        )
        return cleaned

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _llm_extract(self, head_text: str) -> DocumentOntology:
        """调用 LLM 结构化提取本体。"""
        prompt = self._build_prompt(head_text)
        system = (
            "You are a knowledge graph extractor. "
            "Analyze the given text and extract a DAG of concepts. "
            "Each concept must have a clear name, a list of prerequisite concepts, "
            "and a one-sentence summary. "
            "Respond strictly in the requested JSON schema."
        )
        try:
            return await self._llm.structured_extract(
                prompt=prompt,
                model=DocumentOntology,
                system_prompt=system,
                temperature=self._LLM_TEMPERATURE,
            )
        except ValidationError as e:
            logger.warning("Ontology LLM validation failed: %s", e)
            # 降级：返回空本体
            return DocumentOntology(dag=[])

    @staticmethod
    def _build_prompt(head_text: str) -> str:
        """构建本体提取 Prompt。"""
        return (
            "请从以下教材/文档的前言或目录部分，提取知识概念的依赖拓扑图（DAG）。\n\n"
            "要求：\n"
            "1. 每个概念必须有名称、前置依赖列表（必须先掌握的概念）、一句话摘要\n"
            "2. 依赖关系必须构成有向无环图，不能出现循环依赖\n"
            "3. 只提取核心概念，不要过度细分\n"
            "4. 若文本缺少明确依赖关系，depends_on 可为空列表\n\n"
            "文档片段：\n"
            f"{head_text}\n\n"
            "请按 schema 输出 JSON。"
        )

    # ------------------------------------------------------------------
    # 无环校验与剪环
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_acyclic(ontology: DocumentOntology) -> DocumentOntology:
        """
        强制无环校验。若 LLM 输出存在环，自动剪断最弱边直至通过验证。
        """
        dag = list(ontology.dag)
        if not dag:
            return ontology

        max_iterations = len(dag) * 2  # 安全上限
        for _ in range(max_iterations):
            graph = OntologyBuilder._build_graph(dag)
            try:
                ts = TopologicalSorter(graph)
                ts.prepare()
                return DocumentOntology(dag=dag)
            except CycleError as e:
                cycle = e.args[1] if len(e.args) > 1 else []
                if not cycle:
                    logger.error("CycleError without cycle info; breaking all edges")
                    dag = OntologyBuilder._break_all_edges(dag)
                    continue
                dag = OntologyBuilder._break_weakest_edge(dag, cycle)
                logger.warning(
                    "Cycle detected among %s; weakest edge removed", cycle
                )

        # 终极降级：若仍无法通过，清空所有依赖
        logger.error("Unable to break all cycles; falling back to flat graph")
        flat = [c.model_copy(update={"depends_on": []}) for c in dag]
        return DocumentOntology(dag=flat)

    @staticmethod
    def _build_graph(dag: List[ConceptNode]) -> Dict[str, Set[str]]:
        """将 ConceptNode 列表转换为 graphlib 接受的图结构。"""
        graph: Dict[str, Set[str]] = {}
        for node in dag:
            graph[node.concept_name] = set(node.depends_on)
        return graph

    @staticmethod
    def _break_weakest_edge(dag: List[ConceptNode], cycle: List[str]) -> List[ConceptNode]:
        """
        剪断环中最弱边。

        策略：在环上找到出度最少的节点，删除其一条指向环内其他节点的依赖。
        """
        if not cycle:
            return dag

        # 统计环上每个节点的出度（仅统计指向环内其他节点的边）
        cycle_set = set(cycle)
        in_cycle_out_degree: Dict[str, int] = {}
        for node in dag:
            if node.concept_name in cycle_set:
                in_cycle_deps = [d for d in node.depends_on if d in cycle_set]
                in_cycle_out_degree[node.concept_name] = len(in_cycle_deps)

        # 找出出度最少的节点
        weakest_node = min(in_cycle_out_degree, key=lambda k: in_cycle_out_degree[k])

        # 修改该节点的 depends_on，删除第一个指向环内的依赖
        new_dag: List[ConceptNode] = []
        for node in dag:
            if node.concept_name == weakest_node:
                new_deps = [
                    d for d in node.depends_on
                    if d not in cycle_set or d == weakest_node
                ]
                # 至少保留一个指向环内的依赖（如果存在）用于剪断
                filtered = [d for d in node.depends_on if d in cycle_set and d != weakest_node]
                if filtered:
                    # 删除第一条环内依赖
                    to_remove = filtered[0]
                    new_deps = [d for d in node.depends_on if d != to_remove]
                new_dag.append(node.model_copy(update={"depends_on": new_deps}))
            else:
                new_dag.append(node)
        return new_dag

    @staticmethod
    def _break_all_edges(dag: List[ConceptNode]) -> List[ConceptNode]:
        """终极降级：清空所有节点的 depends_on。"""
        return [c.model_copy(update={"depends_on": []}) for c in dag]

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    @staticmethod
    def _persist(
        vault_uuid: str,
        doc_hash: str,
        ontology: DocumentOntology,
    ) -> None:
        """将本体写入 SQLite。"""
        concepts = [
            {
                "concept_name": node.concept_name,
                "depends_on": node.depends_on,
                "summary": node.summary,
            }
            for node in ontology.dag
        ]
        db_pool.save_concept_dependencies(vault_uuid, doc_hash, concepts)


# ---------------------------------------------------------------------------
# 3. 模块级单例
# ---------------------------------------------------------------------------

_ontology_singleton: Optional[OntologyBuilder] = None


def get_ontology_builder(llm: Optional[UnifiedLLMEngine] = None) -> OntologyBuilder:
    """获取全局唯一的 OntologyBuilder 实例。"""
    global _ontology_singleton
    if _ontology_singleton is None:
        _ontology_singleton = OntologyBuilder(llm=llm)
    return _ontology_singleton
