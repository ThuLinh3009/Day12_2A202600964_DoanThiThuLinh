from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, create_react_agent

from app.config import Settings
from app.data_access import ShoppingDataStore, build_data_tools
from app.prompts import (
    DATA_WORKER_PROMPT,
    POLICY_WORKER_PROMPT,
    RESPONSE_WORKER_PROMPT,
    SUPERVISOR_PROMPT,
)
from app.state import ShoppingState
from app.utils import dump_json, extract_json_payload, timestamp_utc
from provider import get_chat_model
from rag.embeddings import SentenceTransformerEmbeddings
from rag.vector_store import ChromaPolicyStore


class ShoppingAssistant:
    """Multi-agent shopping assistant powered by LangGraph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        s = self.settings

        # Load LLM
        self._llm = get_chat_model(s)

        # Load data store
        self._store = ShoppingDataStore(s.orders_path)

        # Load vector store
        self._embedder = SentenceTransformerEmbeddings(s.embedding_model_name)
        self._vector_store = ChromaPolicyStore(s.chroma_dir, self._embedder)
        self._vector_store.ensure_index(s.policy_path)

        # Build tools
        self._data_tools = build_data_tools(self._store)

        @tool
        def search_policy(query: str) -> str:
            """Tìm kiếm chính sách liên quan trong knowledge base.
            Dùng khi cần tra cứu quy định giao hàng, hoàn trả, voucher."""
            hits = self._vector_store.search(query, top_k=s.top_k)
            return json.dumps(hits, ensure_ascii=False)

        self._policy_tools = [search_policy]
        self._search_policy_tool = search_policy

        # Compile graph
        self.graph = _build_graph(self)

    def ask(
        self,
        question: str,
        trace_file: Path | None = None,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        if rebuild_index:
            self._vector_store.rebuild(self.settings.policy_path)

        initial_state: ShoppingState = {
            "question": question,
            "trace": [{"event": "start", "question": question, "ts": timestamp_utc()}],
        }

        final_state = self.graph.invoke(initial_state)

        payload = {
            "question": question,
            "route": final_state.get("route", {}),
            "policy_result": final_state.get("policy_result", {}),
            "data_result": final_state.get("data_result", {}),
            "final_answer": final_state.get("final_answer", ""),
            "trace": final_state.get("trace", []),
        }

        if trace_file is not None:
            trace_file = Path(trace_file)
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            trace_file.write_text(dump_json(payload), encoding="utf-8")

        return payload

    def run_batch(
        self,
        test_file: Path,
        output_dir: Path,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        test_file = Path(test_file)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cases = json.loads(test_file.read_text(encoding="utf-8"))

        results = []
        for case in cases:
            qid = case.get("id", "unknown")
            question = case.get("question", "")
            trace_path = output_dir / f"{qid}_trace.json"

            try:
                result = self.ask(question, trace_file=trace_path, rebuild_index=False)
                results.append({
                    "id": qid,
                    "question": question,
                    "expected_route": case.get("expected_route"),
                    "expected_status": case.get("expected_status"),
                    "final_answer": result["final_answer"],
                    "route": result["route"],
                    "status": "ok",
                })
            except Exception as exc:
                results.append({
                    "id": qid,
                    "question": question,
                    "final_answer": "",
                    "status": "error",
                    "error": str(exc),
                })

        summary = {
            "total": len(results),
            "ok": sum(1 for r in results if r["status"] == "ok"),
            "error": sum(1 for r in results if r["status"] == "error"),
            "results": results,
            "generated_at": timestamp_utc(),
        }

        summary_path = output_dir / "summary.json"
        summary_path.write_text(dump_json(summary), encoding="utf-8")
        return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_text(content) -> str:
    """Normalize LLM response content to plain string (handles Gemini list format)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _supervisor_node(assistant: ShoppingAssistant):
    def node(state: ShoppingState) -> ShoppingState:
        question = state["question"]
        prompt = SUPERVISOR_PROMPT.format(question=question)
        messages = [HumanMessage(content=prompt)]
        response = assistant._llm.invoke(messages)
        raw = _get_text(response.content if hasattr(response, "content") else str(response))
        route = extract_json_payload(raw) or {
            "status": "ok",
            "needs_policy": True,
            "needs_data": False,
            "clarification_question": None,
        }
        return {
            "route": route,
            "trace": [{"event": "supervisor", "route": route, "ts": timestamp_utc()}],
        }
    return node


def _worker_1_policy_node(assistant: ShoppingAssistant):
    agent = create_react_agent(assistant._llm, assistant._policy_tools)

    def node(state: ShoppingState) -> ShoppingState:
        question = state["question"]
        prompt = POLICY_WORKER_PROMPT.format(question=question)
        agent_input = {"messages": [HumanMessage(content=prompt)]}
        agent_output = agent.invoke(agent_input)
        last_msg = agent_output["messages"][-1]
        raw = _get_text(last_msg.content if hasattr(last_msg, "content") else str(last_msg))
        result = extract_json_payload(raw) or {"status": "ok", "summary": raw, "facts": [], "citations": []}
        return {
            "policy_result": result,
            "trace": [{"event": "policy_worker", "result": result, "ts": timestamp_utc()}],
        }
    return node


def _worker_2_data_node(assistant: ShoppingAssistant):
    agent = create_react_agent(assistant._llm, assistant._data_tools)

    def node(state: ShoppingState) -> ShoppingState:
        question = state["question"]
        prompt = DATA_WORKER_PROMPT.format(question=question)
        agent_input = {"messages": [HumanMessage(content=prompt)]}
        agent_output = agent.invoke(agent_input)
        last_msg = agent_output["messages"][-1]
        raw = _get_text(last_msg.content if hasattr(last_msg, "content") else str(last_msg))
        result = extract_json_payload(raw) or {
            "status": "ok",
            "summary": raw,
            "facts": [],
            "missing_fields": [],
            "not_found_entities": [],
        }
        return {
            "data_result": result,
            "trace": [{"event": "data_worker", "result": result, "ts": timestamp_utc()}],
        }
    return node


def _worker_3_response_node(assistant: ShoppingAssistant):
    def node(state: ShoppingState) -> ShoppingState:
        question = state["question"]
        route = state.get("route", {})
        policy_result = state.get("policy_result", {})
        data_result = state.get("data_result", {})

        # Handle clarification at supervisor level
        if route.get("status") == "clarification_needed":
            clarification_q = route.get("clarification_question", "Bạn có thể cung cấp thêm thông tin không?")
            answer = f"Status: clarification_needed\nQuestion: {clarification_q}"
            return {
                "final_answer": answer,
                "trace": [{"event": "response_worker", "final_answer": answer, "ts": timestamp_utc()}],
            }

        prompt = RESPONSE_WORKER_PROMPT.format(
            question=question,
            policy_result=json.dumps(policy_result, ensure_ascii=False, indent=2),
            data_result=json.dumps(data_result, ensure_ascii=False, indent=2),
        )
        messages = [HumanMessage(content=prompt)]
        response = assistant._llm.invoke(messages)
        answer = _get_text(response.content if hasattr(response, "content") else str(response))
        return {
            "final_answer": answer,
            "trace": [{"event": "response_worker", "final_answer": answer, "ts": timestamp_utc()}],
        }
    return node


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _route_after_supervisor(state: ShoppingState) -> str:
    route = state.get("route", {})
    status = route.get("status", "ok")
    if status == "clarification_needed":
        return "worker_3_response"
    needs_policy = route.get("needs_policy", False)
    needs_data = route.get("needs_data", False)
    if needs_policy and needs_data:
        return "worker_1_policy"
    if needs_policy:
        return "worker_1_policy"
    if needs_data:
        return "worker_2_data"
    return "worker_3_response"


def _route_after_policy(state: ShoppingState) -> str:
    route = state.get("route", {})
    if route.get("needs_data", False):
        return "worker_2_data"
    return "worker_3_response"


def _build_graph(assistant: ShoppingAssistant):
    workflow = StateGraph(ShoppingState)

    workflow.add_node("supervisor", _supervisor_node(assistant))
    workflow.add_node("worker_1_policy", _worker_1_policy_node(assistant))
    workflow.add_node("worker_2_data", _worker_2_data_node(assistant))
    workflow.add_node("worker_3_response", _worker_3_response_node(assistant))

    workflow.set_entry_point("supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "worker_1_policy": "worker_1_policy",
            "worker_2_data": "worker_2_data",
            "worker_3_response": "worker_3_response",
        },
    )

    workflow.add_conditional_edges(
        "worker_1_policy",
        _route_after_policy,
        {
            "worker_2_data": "worker_2_data",
            "worker_3_response": "worker_3_response",
        },
    )

    workflow.add_edge("worker_2_data", "worker_3_response")
    workflow.add_edge("worker_3_response", END)

    return workflow.compile()


def build_graph() -> Any:
    """Public helper — instantiates assistant with default settings and returns compiled graph."""
    assistant = ShoppingAssistant()
    return assistant.graph


# Keep module-level node functions for reference
def supervisor_node(state: ShoppingState) -> ShoppingState:
    raise NotImplementedError("Use ShoppingAssistant to get a bound node.")


def worker_1_policy_node(state: ShoppingState) -> ShoppingState:
    raise NotImplementedError("Use ShoppingAssistant to get a bound node.")


def worker_2_data_node(state: ShoppingState) -> ShoppingState:
    raise NotImplementedError("Use ShoppingAssistant to get a bound node.")


def worker_3_response_node(state: ShoppingState) -> ShoppingState:
    raise NotImplementedError("Use ShoppingAssistant to get a bound node.")
