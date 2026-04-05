"""
reporter.py — 每日 Markdown 報告生成
檔名包含時間（精確到分鐘），每次執行產生獨立檔案
無論有無新文獻皆產生報告
"""

import json
from datetime import datetime
from pathlib import Path


CATEGORY_ZH = {
    "voc_breath":      "呼氣 VOC",
    "voc_liquid":      "液態 VOC",
    "disease_cancer":  "癌症應用",
    "disease_chronic": "慢性病",
    "infection":       "感染症",
    "subhealth":       "亞健康",
    "sensor_hardware": "感測器",
    "ai_model":        "AI模型",
    "odor_medicine":   "氣味醫學",
    "method_tech":     "分析方法",
    "other":           "其他",
}


def generate_daily_report(conn, report_dir: str,
                           new_count: int, classified: list[dict],
                           reason: str = ""):
    """
    生成每日 Markdown 報告
    new_count  : 本次新增篇數（0 表示無新文獻）
    classified : 本次分類結果列表（無新文獻時為空列表）
    reason     : 無新文獻時的說明原因
    """
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    # 檔名精確到分鐘，避免同日覆蓋
    now_str  = datetime.now().strftime("%Y-%m-%d_%H%M")
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M:%S")
    filename = Path(report_dir) / f"report_{now_str}.md"

    # 資料庫整體統計
    stats_row = conn.execute("""
        SELECT COUNT(*) total,
               SUM(CASE WHEN is_relevant=1 THEN 1 ELSE 0 END) relevant,
               ROUND(AVG(CASE WHEN is_relevant=1 THEN score ELSE NULL END), 2) avg_score
        FROM literature
    """).fetchone()

    db_total   = stats_row[0] or 0
    db_relevant= stats_row[1] or 0
    db_avg     = stats_row[2] or 0

    # 只保留相關文獻
    relevant = [r for r in classified if r.get("is_relevant")]
    relevant.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 類別分組
    by_cat = {}
    for r in relevant:
        cat = r.get("category", "other")
        by_cat.setdefault(cat, []).append(r)

    # ── 報告標題與概覽 ──
    lines = [
        f"# VOC 文獻監控日報 — {date_str}",
        "",
        f"> 執行時間：{time_str} | 新增 **{new_count}** 篇 | 相關 **{len(relevant)}** 篇",
        "",
        "---",
        "",
        "## 📊 本次執行概覽",
        "",
        "| 項目 | 數量 |",
        "|------|------|",
        f"| 本次搜尋新增 | {new_count} |",
        f"| 本次相關文獻 | {len(relevant)} |",
        f"| 資料庫累計總數 | {db_total} |",
        f"| 資料庫相關總數 | {db_relevant} |",
        f"| 相關文獻平均分 | {db_avg} |",
        "",
    ]

    # ── 無新文獻說明 ──
    if new_count == 0:
        display_reason = reason if reason else "所有搜尋結果均已存在於資料庫中"
        lines += [
            "## ℹ️ 本次無新文獻",
            "",
            f"**原因**：{display_reason}",
            "",
            "系統運作正常，去重機制有效過濾重複文獻。",
            "資料庫持續累積中，下次執行可能有新結果。",
            "",
            "---",
            "",
            f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            ""
        ]
        content = "\n".join(lines)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[報告] 已生成（無新文獻記錄）：{filename}")
        return str(filename)

    # ── 高分文獻（score >= 4）──
    high_score = [r for r in relevant if r.get("score", 0) >= 4]
    if high_score:
        lines += [
            "## ⭐ 重點文獻（評分 4–5）",
            "",
        ]
        for r in high_score:
            tags_str = ", ".join(r.get("tags", []))
            doi_str  = f" | DOI: `{r['doi']}`" if r.get("doi") else ""
            url_str  = f" | [連結]({r['url']})" if r.get("url") else ""
            lines += [
                f"### {r.get('title', '')}",
                "",
                f"- **類別**：{CATEGORY_ZH.get(r.get('category','other'), r.get('category',''))}",
                f"- **評分**：{'⭐' * int(r.get('score', 0))} ({r.get('score', 0)}/5)",
                f"- **標籤**：{tags_str}",
                f"- **摘要**：{r.get('one_line', '')}",
                f"- **作者**：{r.get('authors', 'N/A')} | **年份**：{r.get('year', 'N/A')}{doi_str}{url_str}",
                "",
            ]

    # ── 依類別分組列表 ──
    if by_cat:
        lines += [
            "## 📂 依類別分類",
            "",
        ]
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            cat_zh = CATEGORY_ZH.get(cat, cat)
            lines += [
                f"### {cat_zh}（{len(items)} 篇）",
                "",
            ]
            for r in items:
                score_bar = "▓" * int(r.get("score", 0)) + "░" * (5 - int(r.get("score", 0)))
                title     = r.get("title", "")
                url       = r.get("url", "")
                title_str = f"[{title}]({url})" if url else title
                lines.append(
                    f"- {score_bar} **{title_str}**  \n"
                    f"  {r.get('one_line', '')} ｜ {r.get('year','')}"
                )
            lines.append("")

    # ── 不相關文獻統計 ──
    irrelevant = [r for r in classified if not r.get("is_relevant")]
    if irrelevant:
        lines += [
            "---",
            f"## ℹ️ 本次排除文獻：{len(irrelevant)} 篇（LLM 判定不相關）",
            "",
        ]

    lines += [
        "---",
        f"*報告生成時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ""
    ]

    content = "\n".join(lines)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[報告] 已生成：{filename}")
    return str(filename)