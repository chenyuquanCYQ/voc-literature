"""
dashboard.py — Streamlit 本地視覺化介面
啟動：streamlit run dashboard.py
"""

import streamlit as st
import sqlite3
import pandas as pd
import json
import yaml
from pathlib import Path
from datetime import datetime, timedelta

# ─────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────

st.set_page_config(
    page_title="VOC 文獻監控",
    page_icon="🫁",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自訂樣式
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #e9ecef;
    }
    .score-high   { color: #2ecc71; font-weight: bold; }
    .score-mid    { color: #f39c12; font-weight: bold; }
    .score-low    { color: #95a5a6; }
    .tag-badge {
        display: inline-block;
        background: #e8f4f8;
        color: #2980b9;
        border-radius: 4px;
        padding: 2px 6px;
        margin: 1px;
        font-size: 0.8em;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# 設定載入
# ─────────────────────────────────────────

@st.cache_data(ttl=60)
def load_config():
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {"database_path": "literature.db"}

config = load_config()
DB_PATH = config.get("database_path", "literature.db")

CATEGORY_ZH = {
    "voc_breath":      "🫁 呼氣 VOC",
    "voc_liquid":      "💧 液態 VOC",
    "disease_cancer":  "🔬 癌症應用",
    "disease_chronic": "🩺 慢性病",
    "infection":       "🦠 感染症",
    "subhealth":       "⚡ 亞健康",
    "sensor_hardware": "📡 感測器",
    "ai_model":        "🤖 AI模型",
    "odor_medicine":   "👃 氣味醫學",
    "method_tech":     "🔧 分析方法",
    "other":           "📄 其他",
}

# ─────────────────────────────────────────
# 資料讀取
# ─────────────────────────────────────────

@st.cache_data(ttl=30)
def load_data(db_path: str) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("""
        SELECT id, title, authors, year, journal, category, score,
               tags, one_line, doi, url, source, is_relevant,
               created_at
        FROM literature
        ORDER BY created_at DESC
    """, conn)
    conn.close()
    # 解析 tags JSON
    def parse_tags(t):
        try:
            v = json.loads(t) if t else []
            return v if isinstance(v, list) else []
        except Exception:
            return []
    df["tags_list"] = df["tags"].apply(parse_tags)
    df["tags_str"]  = df["tags_list"].apply(lambda x: ", ".join(x))
    df["created_date"] = pd.to_datetime(df["created_at"]).dt.date
    return df


@st.cache_data(ttl=30)
def load_stats(db_path: str) -> dict:
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    stats = {}
    stats["total"]    = cursor.execute("SELECT COUNT(*) FROM literature").fetchone()[0]
    stats["relevant"] = cursor.execute("SELECT COUNT(*) FROM literature WHERE is_relevant=1").fetchone()[0]
    stats["today"]    = cursor.execute(
        "SELECT COUNT(*) FROM literature WHERE date(created_at)=date('now')").fetchone()[0]
    stats["this_week"]= cursor.execute(
        "SELECT COUNT(*) FROM literature WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
    stats["avg_score"]= cursor.execute(
        "SELECT ROUND(AVG(score),2) FROM literature WHERE is_relevant=1").fetchone()[0] or 0
    stats["by_cat"]   = dict(cursor.execute(
        "SELECT category, COUNT(*) FROM literature WHERE is_relevant=1 GROUP BY category ORDER BY COUNT(*) DESC"
    ).fetchall())
    stats["by_source"]= dict(cursor.execute(
        "SELECT source, COUNT(*) FROM literature GROUP BY source"
    ).fetchall())
    stats["recent_log"]= cursor.execute("""
        SELECT run_at, found, new_added FROM search_log
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    conn.close()
    return stats


# ─────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────

with st.sidebar:
    st.title("🫁 VOC 文獻監控")
    st.markdown("---")

    # 重新整理按鈕
    if st.button("🔄 重新整理資料", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("### 篩選條件")

    show_relevant_only = st.checkbox("只顯示相關文獻", value=True)

    min_score = st.slider("最低評分", min_value=0, max_value=5, value=2)

    all_cats = list(CATEGORY_ZH.keys())
    selected_cats = st.multiselect(
        "類別篩選",
        options=all_cats,
        default=all_cats,
        format_func=lambda x: CATEGORY_ZH.get(x, x)
    )

    date_range = st.selectbox(
        "時間範圍",
        ["全部", "今天", "7天內", "30天內", "90天內"],
        index=0
    )

    st.markdown("---")
    st.markdown("### 搜尋文獻")
    search_query = st.text_input("關鍵字搜尋（標題/摘要）", placeholder="例：lung cancer VOC")

    st.markdown("---")
    st.markdown("### 快速操作")

    if st.button("▶️ 立即執行搜尋", use_container_width=True):
        with st.spinner("執行中... 請稍候（約 5-15 分鐘）"):
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "scheduler.py"],
                capture_output=True, text=True, timeout=900
            )
            st.success("執行完成！")
            if result.stdout:
                st.text(result.stdout[-2000:])
            st.cache_data.clear()
            st.rerun()

    if st.button("📥 匯出 CSV", use_container_width=True):
        import subprocess, sys
        subprocess.run([sys.executable, "scheduler.py", "--export-csv"])
        st.success("CSV 已匯出至 exports/ 目錄")


# ─────────────────────────────────────────
# 主畫面
# ─────────────────────────────────────────

df_all = load_data(DB_PATH)
stats  = load_stats(DB_PATH)

if df_all.empty:
    st.warning("⚠️ 尚無資料。請先執行 `python scheduler.py` 建立資料庫。")
    st.stop()

# ── Tab 頁籤 ──
tab1, tab2, tab3, tab4 = st.tabs(["📊 總覽", "📋 文獻列表", "📈 統計分析", "📅 每日報告"])

# ════════════════════════════════════════
# Tab 1: 總覽
# ════════════════════════════════════════
with tab1:
    st.markdown("## 資料庫總覽")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📚 總文獻數",   stats.get("total", 0))
    c2.metric("✅ 相關文獻",   stats.get("relevant", 0))
    c3.metric("📅 今日新增",   stats.get("today", 0))
    c4.metric("📆 本週新增",   stats.get("this_week", 0))
    c5.metric("⭐ 平均評分",   stats.get("avg_score", 0))

    st.markdown("---")

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### 類別分佈")
        by_cat = stats.get("by_cat", {})
        if by_cat:
            cat_df = pd.DataFrame({
                "類別": [CATEGORY_ZH.get(k, k) for k in by_cat.keys()],
                "篇數": list(by_cat.values())
            }).sort_values("篇數", ascending=False)
            st.bar_chart(cat_df.set_index("類別"))

    with col_right:
        st.markdown("### 最近搜尋記錄")
        logs = stats.get("recent_log", [])
        if logs:
            log_df = pd.DataFrame(logs, columns=["執行時間", "搜尋到", "新增"])
            st.dataframe(log_df, use_container_width=True, hide_index=True)

    # 最新 5 篇高分文獻
    st.markdown("---")
    st.markdown("### ⭐ 最新高分文獻（score ≥ 4）")
    df_top = df_all[
        (df_all["is_relevant"] == 1) & (df_all["score"] >= 4)
    ].head(5)

    if df_top.empty:
        st.info("尚無評分 ≥ 4 的文獻")
    else:
        for _, row in df_top.iterrows():
            with st.expander(f"{'⭐' * int(row['score'])} {row['title'][:80]}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**摘要**：{row['one_line']}")
                    st.write(f"**作者**：{row['authors']} | **年份**：{row['year']} | **期刊**：{row['journal']}")
                    tags_html = " ".join(
                        f'<span class="tag-badge">{t}</span>' for t in row["tags_list"]
                    )
                    st.markdown(tags_html, unsafe_allow_html=True)
                with col2:
                    cat_zh = CATEGORY_ZH.get(row["category"], row["category"])
                    st.write(f"**類別**：{cat_zh}")
                    st.write(f"**評分**：{row['score']}/5")
                    if row["url"]:
                        st.link_button("🔗 查看原文", row["url"])


# ════════════════════════════════════════
# Tab 2: 文獻列表
# ════════════════════════════════════════
with tab2:
    # 套用篩選
    df = df_all.copy()

    if show_relevant_only:
        df = df[df["is_relevant"] == 1]

    if min_score > 0:
        df = df[df["score"] >= min_score]

    if selected_cats:
        df = df[df["category"].isin(selected_cats)]

    if date_range != "全部":
        days_map = {"今天": 1, "7天內": 7, "30天內": 30, "90天內": 90}
        days = days_map[date_range]
        cutoff = (datetime.now() - timedelta(days=days)).date()
        df = df[df["created_date"] >= cutoff]

    if search_query:
        mask = (
            df["title"].str.contains(search_query, case=False, na=False) |
            df["one_line"].str.contains(search_query, case=False, na=False) |
            df["tags_str"].str.contains(search_query, case=False, na=False)
        )
        df = df[mask]

    st.markdown(f"### 文獻列表（共 {len(df)} 筆）")

    if df.empty:
        st.info("無符合條件的文獻")
    else:
        # 顯示表格
        display_cols = {
            "title":    "標題",
            "category": "類別",
            "score":    "評分",
            "year":     "年份",
            "tags_str": "標籤",
            "one_line": "一行摘要",
            "source":   "來源",
            "created_date": "加入日期",
        }
        show_df = df[list(display_cols.keys())].copy()
        show_df.columns = list(display_cols.values())
        show_df["類別"] = show_df["類別"].apply(lambda x: CATEGORY_ZH.get(x, x))

        st.dataframe(
            show_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "評分": st.column_config.ProgressColumn(
                    "評分", min_value=0, max_value=5, format="%.1f"
                ),
            }
        )

        # 詳細檢視
        st.markdown("---")
        st.markdown("### 📖 詳細檢視")
        selected_title = st.selectbox(
            "選擇文獻",
            options=df["title"].tolist()[:50],
            format_func=lambda x: x[:80]
        )
        if selected_title:
            row = df[df["title"] == selected_title].iloc[0]
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"#### {row['title']}")
                st.write(f"**作者**：{row['authors']}")
                st.write(f"**期刊**：{row['journal']} ({row['year']})")
                st.write(f"**一行摘要**：{row['one_line']}")
                tags_html = " ".join(
                    f'<span class="tag-badge">{t}</span>' for t in row["tags_list"]
                )
                st.markdown(f"**標籤**：{tags_html}", unsafe_allow_html=True)
                if row.get("doi"):
                    st.write(f"**DOI**：`{row['doi']}`")
            with col2:
                st.metric("評分", f"{row['score']}/5")
                st.write(f"**類別**：{CATEGORY_ZH.get(row['category'], row['category'])}")
                st.write(f"**來源**：{row['source']}")
                st.write(f"**加入時間**：{row['created_at'][:16]}")
                if row["url"]:
                    st.link_button("🔗 查看原文", row["url"])


# ════════════════════════════════════════
# Tab 3: 統計分析
# ════════════════════════════════════════
with tab3:
    st.markdown("### 📈 統計分析")

    df_rel = df_all[df_all["is_relevant"] == 1].copy()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 評分分佈")
        score_dist = df_rel["score"].value_counts().sort_index()
        st.bar_chart(score_dist)

    with col2:
        st.markdown("#### 來源分佈")
        source_dist = df_all["source"].value_counts()
        st.bar_chart(source_dist)

    st.markdown("#### 每日新增趨勢（近30天）")
    df_all["date"] = pd.to_datetime(df_all["created_at"]).dt.date
    cutoff30 = (datetime.now() - timedelta(days=30)).date()
    daily = (
        df_all[df_all["date"] >= cutoff30]
        .groupby("date")
        .size()
        .reset_index(name="新增篇數")
    )
    if not daily.empty:
        st.line_chart(daily.set_index("date"))

    st.markdown("#### 年份分佈（相關文獻）")
    if not df_rel.empty:
        year_dist = df_rel[df_rel["year"].notna()]["year"].astype(int).value_counts().sort_index()
        if not year_dist.empty:
            st.bar_chart(year_dist)

    st.markdown("#### 類別 × 評分交叉分析")
    if not df_rel.empty:
        pivot = df_rel.groupby("category")["score"].agg(["mean", "count"]).round(2)
        pivot.index = [CATEGORY_ZH.get(i, i) for i in pivot.index]
        pivot.columns = ["平均分", "篇數"]
        pivot = pivot.sort_values("平均分", ascending=False)
        st.dataframe(pivot, use_container_width=True)


# ════════════════════════════════════════
# Tab 4: 每日報告
# ════════════════════════════════════════
with tab4:
    st.markdown("### 📅 每日報告")

    report_dir = Path(config.get("report_dir", "daily_reports"))
    reports = sorted(report_dir.glob("report_*.md"), reverse=True) if report_dir.exists() else []

    if not reports:
        st.info("尚無報告。請先執行 `python scheduler.py` 生成報告。")
    else:
        selected_report = st.selectbox(
            "選擇報告",
            options=reports,
            format_func=lambda p: p.stem.replace("report_", "")
        )
        if selected_report:
            content = selected_report.read_text(encoding="utf-8")
            st.markdown(content)

            st.download_button(
                "⬇️ 下載報告",
                data=content.encode("utf-8"),
                file_name=selected_report.name,
                mime="text/markdown"
            )