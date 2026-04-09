"""
export_to_json.py
從 SQLite 資料庫匯出 data/literature_data.json，並 git push。
每次 scheduler.py 執行完後自動呼叫（或手動執行）。
"""

import sqlite3
import json
import subprocess
from pathlib import Path
from datetime import datetime

REPO_DIR    = Path(__file__).parent
DB_PATH     = REPO_DIR / "literature.db"
OUTPUT_FILE = REPO_DIR / "data" / "literature_data.json"
REPORT_DIR  = REPO_DIR / "daily_reports"
RECENT_REPORTS = 7   # 塞入 JSON 的最近報告份數


# ── 文獻清單 ────────────────────────────────────────────────────────
def load_literature(conn: sqlite3.Connection) -> list:
    rows = conn.execute("""
        SELECT id, title, authors, year, journal, category, score,
               tags, one_line, doi, url, source, is_relevant, created_at
        FROM literature
        ORDER BY created_at DESC
    """).fetchall()
    result = []
    for r in rows:
        tags = json.loads(r["tags"]) if r["tags"] else []
        result.append({
            "id":          r["id"],
            "title":       r["title"]    or "",
            "authors":     r["authors"]  or "",
            "year":        r["year"],
            "journal":     r["journal"]  or "",
            "category":    r["category"] or "other",
            "score":       r["score"]    or 0,
            "tags":        tags,
            "one_line":    r["one_line"] or "",
            "doi":         r["doi"]      or "",
            "url":         r["url"]      or "",
            "source":      r["source"]   or "",
            "is_relevant": bool(r["is_relevant"]),
            "created_at":  r["created_at"] or "",
        })
    return result


# ── 統計資料 ────────────────────────────────────────────────────────
def load_stats(conn: sqlite3.Connection) -> dict:
    stats = {}
    stats["total"]     = conn.execute("SELECT COUNT(*) FROM literature").fetchone()[0]
    stats["relevant"]  = conn.execute("SELECT COUNT(*) FROM literature WHERE is_relevant=1").fetchone()[0]
    stats["today"]     = conn.execute("SELECT COUNT(*) FROM literature WHERE date(created_at)=date('now')").fetchone()[0]
    stats["this_week"] = conn.execute("SELECT COUNT(*) FROM literature WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
    stats["avg_score"] = conn.execute("SELECT ROUND(AVG(score),2) FROM literature WHERE is_relevant=1").fetchone()[0] or 0

    stats["by_category"] = dict(conn.execute("""
        SELECT category, COUNT(*) FROM literature
        WHERE is_relevant=1 GROUP BY category ORDER BY COUNT(*) DESC
    """).fetchall())

    stats["by_source"] = dict(conn.execute(
        "SELECT source, COUNT(*) FROM literature GROUP BY source"
    ).fetchall())

    stats["by_score"] = {
        str(int(k)): v for k, v in conn.execute("""
            SELECT CAST(ROUND(score) AS INT), COUNT(*)
            FROM literature WHERE is_relevant=1
            GROUP BY CAST(ROUND(score) AS INT) ORDER BY 1
        """).fetchall()
    }

    stats["by_year"] = {
        str(k): v for k, v in conn.execute("""
            SELECT year, COUNT(*) FROM literature
            WHERE is_relevant=1 AND year IS NOT NULL
            GROUP BY year ORDER BY year
        """).fetchall()
    }

    rows = conn.execute("""
        SELECT date(created_at) as d, COUNT(*) as cnt
        FROM literature
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY d ORDER BY d
    """).fetchall()
    stats["daily_trend"] = [{"date": r[0], "count": r[1]} for r in rows]

    logs = conn.execute("""
        SELECT run_at, found, new_added FROM search_log
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    stats["recent_log"] = [{"run_at": r[0], "found": r[1], "new_added": r[2]} for r in logs]

    rows = conn.execute("""
        SELECT category, ROUND(AVG(score),2), COUNT(*)
        FROM literature WHERE is_relevant=1
        GROUP BY category ORDER BY AVG(score) DESC
    """).fetchall()
    stats["category_score"] = [
        {"category": r[0], "avg_score": r[1], "count": r[2]} for r in rows
    ]

    return stats


# ── 每日報告 ────────────────────────────────────────────────────────
def load_reports() -> list:
    if not REPORT_DIR.exists():
        return []
    reports = sorted(REPORT_DIR.glob("report_*.md"), reverse=True)[:RECENT_REPORTS]
    result = []
    for p in reports:
        try:
            content = p.read_text(encoding="utf-8")
            result.append({"date": p.stem.replace("report_", ""), "content": content})
        except Exception:
            pass
    return result


# ── Git 推送（list 參數，無 shell=True）────────────────────────────
def git_push():
    print("\n🚀 Git 推送...")
    cmds = [
        ["git", "-C", str(REPO_DIR), "add", "data/literature_data.json"],
        ["git", "-C", str(REPO_DIR), "commit", "-m",
         f"data: auto update {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        ["git", "-C", str(REPO_DIR), "push"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            if "nothing to commit" in r.stdout + r.stderr:
                print("  ⚠️  無變更，跳過 commit")
                return
            print(f"  ❌ 失敗：{r.stderr.strip()}")
            return
        print(f"  ✅ {' '.join(cmd[3:5])}")
    print("🎉 完成！GitHub Pages 約 1 分鐘後更新")


# ── 主流程 ──────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*52}")
    print(f"  export_to_json.py")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*52}")

    if not DB_PATH.exists():
        print(f"❌ 找不到資料庫：{DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    literature = load_literature(conn)
    stats      = load_stats(conn)
    reports    = load_reports()
    conn.close()

    output = {
        "meta": {
            "total":      stats["total"],
            "relevant":   stats["relevant"],
            "today":      stats["today"],
            "this_week":  stats["this_week"],
            "avg_score":  stats["avg_score"],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "stats":         stats,
        "literature":    literature,
        "daily_reports": reports,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"💾 已輸出：{OUTPUT_FILE}（{kb:.1f} KB）")
    print(f"   總文獻 {stats['total']} 篇 | 相關 {stats['relevant']} 篇")

    git_push()


if __name__ == "__main__":
    main()
