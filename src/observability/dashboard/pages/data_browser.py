"""数据浏览器页面 - 浏览已摄取的文档、块和图像。

布局：
1. 集合选择器（侧边栏）
2. 带有块计数的文档列表
3. 可展开的文档详情 → 块卡片，包含文本和元数据
4. 图像预览库
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.observability.dashboard.services.data_service import DataService


def render() -> None:
    """渲染数据浏览器页面."""
    st.header("🔍 数据浏览器")

    try:
        svc = DataService()
    except Exception as exc:
        st.error(f"初始化DataService失败: {exc}")
        return

    # ── Collection selector ────────────────────────────────────────
    collections = svc.list_collections()
    if "default" not in collections:
        collections.insert(0, "default")
    collection = st.selectbox(
        "集合",
        options=collections,
        index=0,
        key="db_collection_filter",
    )
    coll_arg = collection if collection else None

    # ── Danger zone: clear all data ────────────────────────────────
    st.divider()
    with st.expander("⚠️ 危险区域", expanded=False):
        st.warning(
            "这将**永久删除**所有数据："
            "ChromaDB集合、BM25索引、图像、摄取历史和跟踪日志。"
        )
        col_btn, col_status = st.columns([1, 2])
        with col_btn:
            if st.button("🗑️ 清除所有数据", type="primary", key="btn_clear_all"):
                st.session_state["confirm_clear"] = True

        if st.session_state.get("confirm_clear"):
            st.error("确定吗？此操作无法撤销！")
            c1, c2, _ = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ 是，删除所有", key="btn_confirm_clear"):
                    result = svc.reset_all()
                    st.session_state["confirm_clear"] = False
                    if result["errors"]:
                        st.warning(
                            f"清除时出现 {len(result['errors'])} 个错误: "
                            + "; ".join(result["errors"])
                        )
                    else:
                        st.success(
                            f"所有数据已清除！"
                            f"{result['collections_deleted']} 个集合已删除。"
                        )
                    st.rerun()
            with c2:
                if st.button("❌ 取消", key="btn_cancel_clear"):
                    st.session_state["confirm_clear"] = False
                    st.rerun()

    st.divider()

    # ── Document list ──────────────────────────────────────────────
    try:
        docs = svc.list_documents(coll_arg)
    except Exception as exc:
        st.error(f"加载文档失败: {exc}")
        return

    if not docs:
        st.info(
            "**在此集合中未找到文档。** "
            "使用摄取管理器页面上传并摄取文件，"
            "或从上方下拉菜单选择不同集合。"
        )
        return

    st.subheader(f"📄 文档 ({len(docs)})")

    for idx, doc in enumerate(docs):
        source_name = Path(doc["source_path"]).name
        label = f"📑 {source_name}  —  {doc['chunk_count']} 块 · {doc['image_count']} 图像"
        with st.expander(label, expanded=(len(docs) == 1)):
            # ── Document metadata ──────────────────────────────────
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("块", doc["chunk_count"])
            col_b.metric("图像", doc["image_count"])
            col_c.metric("集合", doc.get("collection", "—"))
            st.caption(
                f"**来源:** {doc['source_path']}  ·  "
                f"**哈希:** `{doc['source_hash'][:16]}…`  ·  "
                f"**处理时间:** {doc.get('processed_at', '—')}"
            )

            st.divider()

            # ── Chunk cards ────────────────────────────────────────
            chunks = svc.get_chunks(doc["source_hash"], coll_arg)
            if chunks:
                st.markdown(f"### 📦 块 ({len(chunks)})")
                for cidx, chunk in enumerate(chunks):
                    text = chunk.get("text", "")
                    meta = chunk.get("metadata", {})
                    chunk_id = chunk["id"]

                    # Title from metadata or first line
                    title = meta.get("title", "")
                    if not title:
                        title = text[:60].replace("\n", " ").strip()
                        if len(text) > 60:
                            title += "…"

                    with st.container(border=True):
                        st.markdown(
                            f"**块 {cidx + 1}** · `{chunk_id[-16:]}` · "
                            f"{len(text)} 字符"
                        )
                        # Show the actual chunk text (scrollable)
                        _height = max(120, min(len(text) // 2, 600))
                        st.text_area(
                            "内容",
                            value=text,
                            height=_height,
                            disabled=True,
                            key=f"chunk_text_{idx}_{cidx}",
                            label_visibility="collapsed",
                        )
                        # Expandable metadata
                        with st.expander("📋 元数据", expanded=False):
                            st.json(meta)
            else:
                st.caption("在此文档的向量存储中未找到块。")

            # ── Image preview ──────────────────────────────────────
            images = svc.get_images(doc["source_hash"], coll_arg)
            if images:
                st.divider()
                st.markdown(f"### 🖼️ 图像 ({len(images)})")
                img_cols = st.columns(min(len(images), 4))
                for iidx, img in enumerate(images):
                    with img_cols[iidx % len(img_cols)]:
                        img_path = Path(img.get("file_path", ""))
                        if img_path.exists():
                            st.image(str(img_path), caption=img["image_id"], width=200)
                        else:
                            st.caption(f"{img['image_id']} (文件缺失)")
