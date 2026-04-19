"""Ingestion Traces page – browse ingestion trace history with per-stage detail.

Layout:
1. Trace list (reverse-chronological, filtered to trace_type=="ingestion")
2. Pipeline overview: source file, total time, stage timing waterfall
3. Per-stage detail tabs:
   📄 Load    – raw document text preview
   ✂️ Split   – chunk list with text
   🔄 Transform – before/after diff, enrichment metadata
   🔢 Embed   – vector stats
   💾 Upsert  – stored IDs
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import streamlit as st

from src.observability.dashboard.services.trace_service import TraceService

logger = logging.getLogger(__name__)


def render() -> None:
    """Render the Ingestion Traces page."""
    st.header("🔬 摄取跟踪")

    svc = TraceService()
    traces = svc.list_traces(trace_type="ingestion")

    if not traces:
        st.info("尚未记录摄取跟踪。首先运行摄取！")
        return

    st.subheader(f"📋 跟踪历史 ({len(traces)})")

    for idx, trace in enumerate(traces):
        trace_id = trace.get("trace_id", "unknown")
        started = trace.get("started_at", "—")
        total_ms = trace.get("elapsed_ms")
        total_label = f"{total_ms:.0f} ms" if total_ms is not None else "—"
        meta = trace.get("metadata", {})
        source_path = meta.get("source_path", "—")

        # Build expander title
        file_name = source_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if source_path != "—" else "—"
        expander_title = f"📄 **{file_name}** · {total_label} · {started[:19]}"

        with st.expander(expander_title, expanded=(idx == 0)):
            timings = svc.get_stage_timings(trace)
            stages_by_name = {t["stage_name"]: t for t in timings}

            # ── 1. Overview metrics ────────────────────────────
            st.markdown("#### 📊 管道概览")
            st.caption(f"来源: `{source_path}`")

            load_d = stages_by_name.get("load", {}).get("data", {})
            split_d = stages_by_name.get("split", {}).get("data", {})
            transform_d = stages_by_name.get("transform", {}).get("data", {})
            embed_d = stages_by_name.get("embed", {}).get("data", {})
            upsert_d = stages_by_name.get("upsert", {}).get("data", {})

            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                st.metric("文档长度", f"{load_d.get('text_length', 0):,} 字符")
            with c2:
                st.metric("块", split_d.get("chunk_count", 0))
            with c3:
                st.metric("图像", load_d.get("image_count", 0))
            with c4:
                st.metric("向量", upsert_d.get("vector_count", 0))
            with c5:
                st.metric("总时间", total_label)

            st.divider()

            # ── 2. Stage timing waterfall ──────────────────────
            # Filter to main pipeline stages only (not sub-stages)
            main_stages = [
                t for t in timings
                if t["stage_name"] in ("load", "split", "transform", "embed", "upsert")
            ]
            if main_stages:
                st.markdown("#### ⏱️ 阶段计时")
                chart_data = {t["stage_name"]: t["elapsed_ms"] for t in main_stages}
                st.bar_chart(chart_data, horizontal=True)
                st.table([
                    {
                        "阶段": t["stage_name"],
                        "耗时 (ms)": round(t["elapsed_ms"], 2),
                    }
                    for t in main_stages
                ])

            # ── Diagnostics ───────────────────────────────────
            _render_ingestion_diagnostics(stages_by_name, load_d, split_d, transform_d, embed_d, upsert_d)

            st.divider()

            # ── 3. Per-stage detail tabs ───────────────────────
            st.markdown("#### 🔍 阶段详情")

            tab_defs = []
            if "load" in stages_by_name:
                tab_defs.append(("📄 加载", "load"))
            if "split" in stages_by_name:
                tab_defs.append(("✂️ 分割", "split"))
            if "transform" in stages_by_name:
                tab_defs.append(("🔄 转换", "transform"))
            if "embed" in stages_by_name:
                tab_defs.append(("🔢 嵌入", "embed"))
            if "upsert" in stages_by_name:
                tab_defs.append(("💾 插入", "upsert"))

            if tab_defs:
                tabs = st.tabs([label for label, _ in tab_defs])
                for tab, (label, key) in zip(tabs, tab_defs):
                    with tab:
                        stage = stages_by_name[key]
                        data = stage.get("data", {})
                        elapsed = stage.get("elapsed_ms")
                        if elapsed is not None:
                            st.caption(f"⏱️ {elapsed:.1f} ms")

                        if key == "load":
                            _render_load_stage(data, trace_idx=idx)
                        elif key == "split":
                            _render_split_stage(data, trace_idx=idx)
                        elif key == "transform":
                            _render_transform_stage(data, trace_idx=idx)
                        elif key == "embed":
                            _render_embed_stage(data)
                        elif key == "upsert":
                            _render_upsert_stage(data)
            else:
                st.info("无阶段详情可用。")


def _render_ingestion_diagnostics(
    stages_by_name: Dict[str, Any],
    load_d: Dict[str, Any],
    split_d: Dict[str, Any],
    transform_d: Dict[str, Any],
    embed_d: Dict[str, Any],
    upsert_d: Dict[str, Any],
) -> None:
    """Render diagnostic hints for ingestion pipeline stages."""
    expected = ["load", "split", "transform", "embed", "upsert"]
    present = [s for s in expected if s in stages_by_name]
    missing = [s for s in expected if s not in stages_by_name]

    if missing:
        missing_labels = {"load": "📄 加载", "split": "✂️ 分割", "transform": "🔄 转换", "embed": "🔢 嵌入", "upsert": "💾 插入"}
        names = ", ".join(missing_labels.get(m, m) for m in missing)
        if "load" in missing:
            st.error(
                f"**管道不完整 — 缺少阶段: {names}。** "
                "加载阶段失败或被跳过。文档可能损坏或不受支持。"
            )
        else:
            st.warning(
                f"**管道不完整 — 缺少阶段: {names}。** "
                "处理过程中可能发生错误。请检查日志详情。"
            )

    # Stage-specific diagnostics
    if "load" in stages_by_name and load_d.get("text_length", 0) == 0:
        st.warning("**加载阶段产生空文本。** 文档可能是纯图像或不受支持的格式。")

    if "split" in stages_by_name and split_d.get("chunk_count", 0) == 0:
        st.warning("**分割阶段产生 0 块。** 文档文本可能太短或为空。")

    if "transform" in stages_by_name:
        refined_llm = transform_d.get("refined_by_llm", 0)
        refined_rule = transform_d.get("refined_by_rule", 0)
        if refined_llm == 0 and refined_rule == 0:
            st.info("**转换:** 无块被精炼。LLM 精炼可能被禁用或为短块跳过。")

    if "embed" in stages_by_name and embed_d.get("dense_vector_count", 0) == 0:
        st.warning("**嵌入阶段产生 0 向量。** 嵌入 API 可能失败。请检查 API 密钥和端点。")

    if "upsert" in stages_by_name:
        vec_count = upsert_d.get("vector_count", upsert_d.get("dense_store", {}).get("count", 0))
        if vec_count == 0:
            st.warning("**插入阶段存储 0 向量。** 数据库写入可能失败。")

    # Check for error fields in any stage data
    for stage_name in present:
        stage_data = stages_by_name[stage_name].get("data", {})
        err = stage_data.get("error", "")
        if err:
            label = stage_name.replace("_", " ").title()
            st.error(f"**{label} 阶段错误:** {err}")


# ═══════════════════════════════════════════════════════════════
# Per-stage renderers
# ═══════════════════════════════════════════════════════════════

def _render_load_stage(data: Dict[str, Any], *, trace_idx: int = 0) -> None:
    """Render Load stage: raw document preview."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("文档 ID", data.get("doc_id", "—")[:16])
    with c2:
        st.metric("文本长度", f"{data.get('text_length', 0):,}")
    with c3:
        st.metric("图像", data.get("image_count", 0))

    preview = data.get("text_preview", "")
    if preview:
        st.markdown("**原始文档文本**")
        st.text_area(
            "raw_text",
            value=preview,
            height=max(120, min(len(preview) // 2, 600)),
            disabled=True,
            label_visibility="collapsed",
            key=f"load_raw_text_{trace_idx}",
        )
    else:
        st.info("此跟踪中未记录文本预览。")


def _render_split_stage(data: Dict[str, Any], *, trace_idx: int = 0) -> None:
    """Render Split stage: chunk list with texts."""
    c1, c2 = st.columns(2)
    with c1:
        st.metric("块", data.get("chunk_count", 0))
    with c2:
        st.metric("平均大小", f"{data.get('avg_chunk_size', 0)} 字符")

    chunks = data.get("chunks", [])
    if chunks:
        st.markdown("**分割后的块**")
        for i, chunk in enumerate(chunks):
            char_len = chunk.get("char_len", 0)
            chunk_id = chunk.get("chunk_id", "")
            text = chunk.get("text", "")
            header = f"📝 **块 #{i+1}** — `{chunk_id[:20]}` — {char_len} 字符"
            with st.expander(header, expanded=(i < 2)):
                st.text_area(
                    f"split_{i}",
                    value=text,
                    height=max(100, min(len(text) // 2, 500)),
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"split_{trace_idx}_{i}",
                )
    else:
        st.info("未记录块文本。重新运行摄取以生成新跟踪。")


def _render_transform_stage(data: Dict[str, Any], *, trace_idx: int = 0) -> None:
    """Render Transform stage: before/after refinement + enrichment metadata."""
    # Summary metrics
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            "精炼 (LLM / 规则)",
            f"{data.get('refined_by_llm', 0)} / {data.get('refined_by_rule', 0)}",
        )
    with c2:
        st.metric(
            "丰富 (LLM / 规则)",
            f"{data.get('enriched_by_llm', 0)} / {data.get('enriched_by_rule', 0)}",
        )
    with c3:
        st.metric("描述", data.get("captioned_chunks", 0))

    chunks = data.get("chunks", [])
    if chunks:
        st.markdown("**每块转换结果**")
        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_id", "")
            refined_by = chunk.get("refined_by", "")
            enriched_by = chunk.get("enriched_by", "")
            title = chunk.get("title", "")
            tags = chunk.get("tags", [])
            summary = chunk.get("summary", "")
            text_before = chunk.get("text_before", "")
            text_after = chunk.get("text_after", "")

            badge_parts = []
            if refined_by:
                badge_parts.append(f"refined:`{refined_by}`")
            if enriched_by:
                badge_parts.append(f"enriched:`{enriched_by}`")
            badges = " · ".join(badge_parts)

            header = f"🔄 **块 #{i+1}** — `{chunk_id[:20]}` — {badges}"
            with st.expander(header, expanded=(i == 0)):
                # Metadata from enrichment
                if title or tags or summary:
                    st.markdown("**丰富元数据**")
                    meta_cols = st.columns(3)
                    with meta_cols[0]:
                        st.markdown(f"**标题:** {title}" if title else "_无标题_")
                    with meta_cols[1]:
                        if tags:
                            st.markdown("**标签:** " + ", ".join(f"`{t}`" for t in tags))
                        else:
                            st.markdown("_无标签_")
                    with meta_cols[2]:
                        if summary:
                            st.markdown(f"**摘要:** {summary}")

                # Before / After text comparison
                if text_before or text_after:
                    st.markdown("**文本比较**")
                    # Compute a uniform height so both sides match
                    _max_len = max(len(text_before or ""), len(text_after or ""))
                    _h = max(150, min(_max_len // 2, 600))
                    col_before, col_after = st.columns(2)
                    with col_before:
                        st.markdown("*精炼前:*")
                        st.text_area(
                            f"before_{i}",
                            value=text_before if text_before else "(empty)",
                            height=_h,
                            disabled=True,
                            label_visibility="collapsed",
                            key=f"transform_before_{trace_idx}_{i}",
                        )
                    with col_after:
                        st.markdown("*精炼后 + 丰富:*")
                        st.text_area(
                            f"after_{i}",
                            value=text_after if text_after else "(empty)",
                            height=_h,
                            disabled=True,
                            label_visibility="collapsed",
                            key=f"transform_after_{trace_idx}_{i}",
                        )
    else:
        st.info("未记录每块转换数据。重新运行摄取以生成新跟踪。")


def _render_embed_stage(data: Dict[str, Any]) -> None:
    """Render Embed stage: dual-path Dense + Sparse encoding details."""
    # ── Overview metrics ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("密集向量", data.get("dense_vector_count", 0))
    with c2:
        st.metric("维度", data.get("dense_dimension", 0))
    with c3:
        st.metric("稀疏文档", data.get("sparse_doc_count", 0))
    with c4:
        st.metric("方法", data.get("method", "—"))

    chunks = data.get("chunks", [])
    if not chunks:
        st.info("未记录块编码数据。")
        return

    # ── Dual-path per-chunk table ──
    st.markdown("---")
    dense_tab, sparse_tab = st.tabs(["🟦 密集编码", "🟨 稀疏编码 (BM25)"])

    with dense_tab:
        st.markdown("每个块 → 通过嵌入模型 (例如 `text-embedding-ada-002`) 的 **浮点向量**")
        dense_rows = []
        for i, chunk in enumerate(chunks):
            char_len = chunk.get("char_len", 0)
            dense_rows.append({
                "#": i + 1,
                "块 ID": chunk.get("chunk_id", ""),
                "字符": char_len,
                "估计令牌": max(1, char_len // 3),
                "密集维度": chunk.get("dense_dim", data.get("dense_dimension", "—")),
            })
        st.table(dense_rows)

    with sparse_tab:
        st.markdown("每个块 → BM25 索引的 **术语频率统计**")
        sparse_rows = []
        for i, chunk in enumerate(chunks):
            sparse_rows.append({
                "#": i + 1,
                "块 ID": chunk.get("chunk_id", ""),
                "文档长度 (术语)": chunk.get("doc_length", "—"),
                "唯一术语": chunk.get("unique_terms", "—"),
            })
        st.table(sparse_rows)

        # Top terms per chunk
        for i, chunk in enumerate(chunks):
            top_terms = chunk.get("top_terms", [])
            if top_terms:
                with st.expander(f"🔤 块 {i + 1} — 顶级术语", expanded=False):
                    term_rows = [{"术语": t["term"], "频率": t["freq"]} for t in top_terms]
                    st.table(term_rows)


def _render_upsert_stage(data: Dict[str, Any]) -> None:
    """Render Upsert stage: per-store details with chunk mapping."""
    dense_store = data.get("dense_store", {})
    sparse_store = data.get("sparse_store", {})
    image_store = data.get("image_store", {})

    # ── Overview metrics ──
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("密集向量", dense_store.get("count", data.get("vector_count", 0)))
    with c2:
        st.metric("稀疏 (BM25)", sparse_store.get("count", data.get("bm25_docs", 0)))
    with c3:
        st.metric("图像", image_store.get("count", data.get("images_indexed", 0)))

    # ── Dense store details ──
    if dense_store:
        with st.expander("🟦 密集向量存储 (ChromaDB)", expanded=True):
            dc1, dc2 = st.columns(2)
            with dc1:
                st.markdown(f"**后端:** `{dense_store.get('backend', '—')}`")
                st.markdown(f"**集合:** `{dense_store.get('collection', '—')}`")
            with dc2:
                st.markdown(f"**路径:** `{dense_store.get('path', '—')}`")
                st.markdown(f"**向量:** {dense_store.get('count', 0)}")

    # ── Sparse store details ──
    if sparse_store:
        with st.expander("🟨 稀疏索引 (BM25)", expanded=True):
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown(f"**后端:** `{sparse_store.get('backend', '—')}`")
                st.markdown(f"**集合:** `{sparse_store.get('collection', '—')}`")
            with sc2:
                st.markdown(f"**路径:** `{sparse_store.get('path', '—')}`")
                st.markdown(f"**文档:** {sparse_store.get('count', 0)}")

    # ── Image store details ──
    if image_store and image_store.get("count", 0) > 0:
        with st.expander(f"🖼️ 图像存储 ({image_store.get('count', 0)} 张图像)", expanded=True):
            st.markdown(f"**后端:** `{image_store.get('backend', '—')}`")
            imgs = image_store.get("images", [])
            if imgs:
                img_rows = [
                    {
                        "图像 ID": img.get("image_id", ""),
                        "页面": img.get("page", 0),
                        "文件": img.get("file_path", ""),
                        "文档哈希": img.get("doc_hash", "")[:16] + "…",
                    }
                    for img in imgs
                ]
                st.table(img_rows)

    # ── Chunk → Vector ID mapping ──
    chunk_mapping = data.get("chunk_mapping", [])
    if chunk_mapping:
        with st.expander(f"🔗 块 → 向量映射 ({len(chunk_mapping)} 条目)", expanded=False):
            mapping_rows = [
                {
                    "#": i + 1,
                    "块 ID": m.get("chunk_id", ""),
                    "向量 ID": m.get("vector_id", ""),
                    "存储": m.get("store", ""),
                    "集合": m.get("collection", ""),
                }
                for i, m in enumerate(chunk_mapping)
            ]
            st.table(mapping_rows)

    # ── Fallback: legacy format with just vector_ids ──
    if not chunk_mapping and not dense_store:
        vector_ids = data.get("vector_ids", [])
        if vector_ids:
            with st.expander("向量 ID", expanded=False):
                for vid in vector_ids:
                    st.code(vid, language=None)
