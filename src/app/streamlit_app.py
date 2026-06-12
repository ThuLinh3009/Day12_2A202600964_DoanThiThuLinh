from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure src is on path when running via streamlit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph import ShoppingAssistant

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Shopping Assistant",
    page_icon="🛒",
    layout="wide",
)

st.title("🛒 Shopping Assistant — Multi-Agent Demo")
st.caption("Powered by LangGraph · RAG · DeepSeek/Gemini")

# ---------------------------------------------------------------------------
# Init assistant (cached)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Đang khởi động hệ thống...")
def load_assistant():
    return ShoppingAssistant()

assistant = load_assistant()

# ---------------------------------------------------------------------------
# Sidebar — example questions
# ---------------------------------------------------------------------------
st.sidebar.header("📋 Câu hỏi mẫu")
examples = {
    "📦 Policy": [
        "Chính sách hoàn trả hàng như thế nào?",
        "Thời gian giao hàng tiêu chuẩn là bao lâu?",
        "Sản phẩm nào không được trả hàng?",
        "Voucher có được hoàn lại khi hủy đơn không?",
    ],
    "🔍 Tra cứu dữ liệu": [
        "Đơn hàng 1971 đang ở đâu?",
        "Cho tôi xem các đơn hàng của khách C001",
        "Voucher còn lại của C001 là gì?",
        "Đơn hàng 2058 đã giao chưa?",
    ],
    "🔗 Kết hợp": [
        "Đơn hàng 1971 có được hoàn trả không?",
        "Đơn hàng 2058 còn trong hạn trả hàng không?",
        "C001 còn dùng được bao nhiêu voucher tháng này?",
    ],
    "❓ Edge cases": [
        "Đơn hàng 9999 thế nào?",
        "Tôi muốn hoàn trả",
    ],
}

selected_question = None
for group, qs in examples.items():
    st.sidebar.subheader(group)
    for q in qs:
        if st.sidebar.button(q, key=q, use_container_width=True):
            selected_question = q

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
user_input = st.chat_input("Nhập câu hỏi của bạn...")

# Use sidebar button or chat input
question = selected_question or user_input

if question:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # Run assistant
    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý..."):
            result = assistant.ask(question)

        answer = result.get("final_answer", "Không có câu trả lời.")
        st.markdown(answer)

        # Show routing info in expander
        route = result.get("route", {})
        policy_result = result.get("policy_result", {})
        data_result = result.get("data_result", {})

        with st.expander("🔍 Chi tiết xử lý", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.subheader("Supervisor routing")
                status = route.get("status", "-")
                color = "green" if status == "ok" else "orange"
                st.markdown(f"**Status:** :{color}[{status}]")
                st.markdown(f"**Policy:** {'✅' if route.get('needs_policy') else '❌'}")
                st.markdown(f"**Data:** {'✅' if route.get('needs_data') else '❌'}")

            with col2:
                st.subheader("Policy Worker")
                if policy_result:
                    st.markdown(f"**Status:** {policy_result.get('status', '-')}")
                    citations = policy_result.get("citations", [])
                    if citations:
                        st.markdown("**Citations:**")
                        for c in citations:
                            st.markdown(f"- {c}")
                    facts = policy_result.get("facts", [])
                    if facts:
                        st.markdown("**Facts:**")
                        for f in facts:
                            st.markdown(f"- {f}")
                else:
                    st.markdown("_Không gọi_")

            with col3:
                st.subheader("Data Worker")
                if data_result:
                    st.markdown(f"**Status:** {data_result.get('status', '-')}")
                    facts = data_result.get("facts", [])
                    if facts:
                        st.markdown("**Facts:**")
                        for f in facts:
                            st.markdown(f"- {f}")
                else:
                    st.markdown("_Không gọi_")

    st.session_state.messages.append({"role": "assistant", "content": answer})
