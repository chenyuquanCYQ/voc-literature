"""
import_existing.py — 既有文獻一次性匯入
讀取 D:\Reference\文獻分類清單.xlsx + 資料夾結構 → 寫入 literature.db

欄位對應（來自 classify_references-Gemma.py）：
  xlsx 欄位：檔案名稱 | 文獻類型 | 文獻標題 | 主要分類 | 次要分類 | 處理狀態 | 文獻摘要
  目標欄位：filename  | doc_type | title    | category | sub_cat  | status  | abstract

執行方式：
  python import_existing.py
  python import_existing.py --xlsx "D:/Reference/文獻分類清單.xlsx"
  python import_existing.py --dry-run   （只預覽，不寫入）
"""

import sqlite3
import json
import argparse
import os
import re
from pathlib import Path
from datetime import datetime

try:
    import openpyxl
except ImportError:
    print("請先安裝：pip install openpyxl")
    raise

# ─────────────────────────────────────────
# 設定
# ─────────────────────────────────────────

DEFAULT_XLSX   = r"D:\Reference\文獻分類清單.xlsx"
DEFAULT_DB     = "literature.db"
DEFAULT_REF_FOLDER = r"D:\Reference"   # 用於從子資料夾名稱補充分類資訊

# ── 舊分類 → 新系統 category 對應表 ──────
# 22 個子分類 全部明確對應
CATEGORY_MAP = {
    # 01_硬體與儀器
    "01a_呼氣採集系統":           "method_tech",
    "01b_質譜與層析儀器":         "method_tech",
    "01c_光學檢測":               "method_tech",
    "01d_電子鼻與化學感測器":     "sensor_hardware",
    "01e_穿戴式設備":             "sensor_hardware",
    # 02_VOCs與生物標記
    "02a_VOC化合物資料庫":        "voc_breath",
    "02b_呼氣代謝體":             "voc_breath",
    "02c_血液_尿液_汗液揮發體":   "voc_liquid",
    "02d_生物標記探索":           "voc_breath",
    # 03_疾病篩檢與診斷
    "03a_癌症":                   "disease_cancer",
    "03b_呼吸道疾病":             "disease_chronic",
    "03c_代謝疾病":               "disease_chronic",
    "03d_其他疾病":               "disease_chronic",
    # 04_AI與資料分析
    "04a_機器學習與深度學習":     "ai_model",
    "04b_特徵提取與演算法":       "ai_model",
    "04c_數位生物標記":           "ai_model",
    # 05_材料與耗材
    "05a_吸附材料與採樣容器":     "method_tech",
    "05b_過濾與前處理材料":       "method_tech",
    # 06_亞健康與個人化健康
    "06a_運動代謝評估":           "subhealth",
    "06b_健康監測與評估":         "subhealth",
    # 07_其他_待分類
    "07_其他_待分類":             "other",
    # 08_芳香療法與氣味治療
    "08a_精油成分與萃取":         "odor_medicine",
    "08b_芳香療法臨床研究":       "odor_medicine",
    "08c_氣味與情緒_神經科學":    "odor_medicine",
    # 大類 fallback（萬一主要分類只寫大類名稱）
    "01_硬體與儀器":              "sensor_hardware",
    "02_VOCs與生物標記":          "voc_breath",
    "03_疾病篩檢與診斷":          "disease_chronic",
    "04_AI與資料分析":            "ai_model",
    "05_材料與耗材":              "method_tech",
    "06_亞健康與個人化健康":      "subhealth",
    "07_其他_待分類":             "other",
    "08_芳香療法與氣味治療":      "odor_medicine",
}

# 舊分類 → is_relevant 預設值
# 與 VOC / 呼氣代謝體核心主題直接相關 → True；材料/待分類 → False（保守）
RELEVANT_MAP = {
    "voc_breath":      True,
    "voc_liquid":      True,
    "disease_cancer":  True,
    "disease_chronic": True,
    "infection":       True,
    "subhealth":       True,
    "sensor_hardware": True,
    "ai_model":        True,
    "odor_medicine":   True,
    "method_tech":     True,
    "other":           False,   # 待分類保守設為 False，可手動調整
}

# 舊分類 → 預設評分（粗估，可事後調整）
SCORE_MAP = {
    "voc_breath":      4,
    "voc_liquid":      4,
    "disease_cancer":  4,
    "disease_chronic": 3,
    "infection":       3,
    "subhealth":       3,
    "sensor_hardware": 3,
    "ai_model":        3,
    "odor_medicine":   3,
    "method_tech":     3,
    "other":           1,
}

# ─────────────────────────────────────────
# 資料庫初始化（複製自 database.py，獨立可執行）
# ─────────────────────────────────────────

def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS literature (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            doi           TEXT,
            pmid          TEXT,
            title         TEXT NOT NULL,
            abstract      TEXT,
            authors       TEXT,
            year          INTEGER,
            journal       TEXT,
            url           TEXT,
            source        TEXT,
            is_relevant   INTEGER DEFAULT 0,
            category      TEXT,
            score         REAL DEFAULT 0,
            tags          TEXT,
            one_line      TEXT,
            raw_json      TEXT,
            created_at    TEXT DEFAULT (datetime('now')),
            filename      TEXT,
            doc_type      TEXT,
            sub_category  TEXT,
            import_status TEXT,
            UNIQUE(title)
        );
        CREATE INDEX IF NOT EXISTS idx_relevant  ON literature(is_relevant);
        CREATE INDEX IF NOT EXISTS idx_category  ON literature(category);
        CREATE INDEX IF NOT EXISTS idx_score     ON literature(score);
        CREATE TABLE IF NOT EXISTS search_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at     TEXT DEFAULT (datetime('now')),
            query      TEXT,
            source     TEXT,
            found      INTEGER,
            new_added  INTEGER
        );
    """)
    conn.commit()
    return conn


# ─────────────────────────────────────────
# 分類對應邏輯
# ─────────────────────────────────────────

def map_category(raw_category: str) -> str:
    """
    將 xlsx 中的「主要分類」欄位對應到新系統的 category。
    支援完整名稱（01a_呼氣採集系統）或模糊匹配。
    """
    if not raw_category or str(raw_category).strip() in ("", "無", "nan"):
        return "other"

    raw = str(raw_category).strip()

    # 直接完整匹配
    if raw in CATEGORY_MAP:
        return CATEGORY_MAP[raw]

    # 模糊匹配：找包含關鍵詞的鍵
    for key, val in CATEGORY_MAP.items():
        if key in raw or raw in key:
            return val

    # 從代碼前綴推斷
    if raw.startswith("01"):
        return "sensor_hardware"
    elif raw.startswith("02"):
        return "voc_breath"
    elif raw.startswith("03"):
        return "disease_chronic"
    elif raw.startswith("04"):
        return "ai_model"
    elif raw.startswith("05"):
        return "method_tech"
    elif raw.startswith("06"):
        return "subhealth"
    elif raw.startswith("08"):
        return "odor_medicine"

    return "other"


def extract_year_from_filename(filename: str) -> int | None:
    """嘗試從檔名擷取年份（如 Smith_2023_xxx.pdf）"""
    if not filename:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(filename))
    return int(match.group()) if match else None


def build_tags(raw_category: str, sub_category: str, doc_type: str) -> list[str]:
    """從分類資訊建立標籤列表"""
    tags = []
    for val in [raw_category, sub_category, doc_type]:
        if val and str(val).strip() not in ("", "無", "nan", "其他"):
            clean = str(val).strip()
            # 去掉代碼前綴（01a_ → 呼氣採集系統）
            clean = re.sub(r"^\d+[a-z]?_", "", clean)
            if clean and clean not in tags:
                tags.append(clean)
    return tags[:5]


# ─────────────────────────────────────────
# 主匯入邏輯
# ─────────────────────────────────────────

def load_xlsx(xlsx_path: str) -> list[dict]:
    """讀取 xlsx，回傳原始列資料"""
    print(f"[讀取] 開啟 Excel：{xlsx_path}")
    try:
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    except FileNotFoundError:
        print(f"  [錯誤] 找不到檔案：{xlsx_path}")
        print("  請確認路徑正確，或使用 --xlsx 參數指定正確路徑")
        return []

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        print("  [錯誤] Excel 是空的")
        return []

    # 解析標題列
    headers = [str(h).strip() if h else "" for h in rows[0]]
    print(f"  找到欄位：{headers}")
    print(f"  資料列數：{len(rows) - 1}")

    # 欄位索引（對應 classify_references-Gemma.py 的輸出格式）
    col_map = {
        "檔案名稱": None, "文獻類型": None, "文獻標題": None,
        "主要分類": None, "次要分類": None, "處理狀態": None, "文獻摘要": None,
    }
    for idx, h in enumerate(headers):
        if h in col_map:
            col_map[h] = idx

    print(f"  欄位對應：{col_map}")

    records = []
    for row in rows[1:]:
        if not any(row):   # 全空列跳過
            continue
        def get(col_name):
            idx = col_map.get(col_name)
            if idx is None or idx >= len(row):
                return ""
            val = row[idx]
            return str(val).strip() if val is not None else ""

        records.append({
            "檔案名稱": get("檔案名稱"),
            "文獻類型": get("文獻類型"),
            "文獻標題": get("文獻標題"),
            "主要分類": get("主要分類"),
            "次要分類": get("次要分類"),
            "處理狀態": get("處理狀態"),
            "文獻摘要": get("文獻摘要"),
        })

    return records


def convert_record(raw: dict) -> dict:
    """將 xlsx 原始列轉換為 literature 資料表欄位"""
    title = raw.get("文獻標題", "").strip()
    if not title or title in ("分析失敗", "掃描版分析失敗", "無法讀取"):
        # 用檔案名稱作為備用標題
        title = raw.get("檔案名稱", "未知標題").strip()

    raw_cat    = raw.get("主要分類", "")
    raw_subcat = raw.get("次要分類", "")
    category   = map_category(raw_cat)
    is_relevant = RELEVANT_MAP.get(category, False)
    score       = SCORE_MAP.get(category, 1)

    # 若處理狀態是失敗，降低評分
    status = raw.get("處理狀態", "")
    if status in ("讀取失敗", "複製失敗"):
        score = max(0, score - 1)
        is_relevant = False

    tags = build_tags(raw_cat, raw_subcat, raw.get("文獻類型", ""))
    year = extract_year_from_filename(raw.get("檔案名稱", ""))
    abstract = raw.get("文獻摘要", "").strip()

    # one_line：取摘要前 80 字
    one_line = ""
    if abstract and abstract not in ("AI 分析時發生錯誤，請手動檢查。",
                                     "掃描版 PDF 分析時發生錯誤，請手動檢查。",
                                     "無法讀取檔案內容。"):
        one_line = abstract[:80].replace("\n", " ").strip()
        if len(abstract) > 80:
            one_line += "…"

    return {
        "title":         title,
        "abstract":      abstract,
        "authors":       "",           # xlsx 無作者欄位
        "year":          year,
        "journal":       "",
        "url":           "",
        "doi":           "",
        "pmid":          "",
        "source":        "import",
        "is_relevant":   is_relevant,
        "category":      category,
        "score":         score,
        "tags":          tags,
        "one_line":      one_line,
        "filename":      raw.get("檔案名稱", ""),
        "doc_type":      raw.get("文獻類型", ""),
        "sub_category":  raw_subcat,
        "import_status": status,
        "raw_json":      json.dumps(raw, ensure_ascii=False),
    }


def insert_record(conn: sqlite3.Connection, rec: dict) -> bool:
    """插入一筆，回傳是否成功（False = 重複）"""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM literature WHERE title=? LIMIT 1", (rec["title"],))
    if cursor.fetchone():
        return False
    try:
        cursor.execute("""
            INSERT INTO literature
              (title, abstract, authors, year, journal, url, doi, pmid,
               source, is_relevant, category, score, tags, one_line,
               filename, doc_type, sub_category, import_status, raw_json)
            VALUES
              (:title,:abstract,:authors,:year,:journal,:url,:doi,:pmid,
               :source,:is_relevant,:category,:score,:tags,:one_line,
               :filename,:doc_type,:sub_category,:import_status,:raw_json)
        """, {**rec, "tags": json.dumps(rec["tags"], ensure_ascii=False)})
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def run_import(xlsx_path: str, db_path: str, dry_run: bool = False):
    """主匯入流程"""
    print(f"\n{'='*60}")
    print(f"  既有文獻匯入  {'[DRY RUN - 不寫入]' if dry_run else ''}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 讀取 xlsx
    raw_records = load_xlsx(xlsx_path)
    if not raw_records:
        print("無資料可匯入，結束。")
        return

    print(f"\n[轉換] 開始轉換 {len(raw_records)} 筆記錄...")

    # 轉換所有記錄
    converted = []
    skip_no_title = 0
    for raw in raw_records:
        rec = convert_record(raw)
        title = rec.get("title", "")
        if not title or len(title) < 3:
            skip_no_title += 1
            continue
        converted.append(rec)

    print(f"  有效記錄：{len(converted)} 筆（跳過無標題：{skip_no_title} 筆）")

    # Dry Run 預覽
    if dry_run:
        print(f"\n[預覽] 前 10 筆轉換結果：")
        print(f"{'─'*80}")
        for rec in converted[:10]:
            tags_str = ", ".join(rec["tags"])
            print(f"  標題：{rec['title'][:60]}")
            print(f"  分類：{rec['category']} | 相關：{rec['is_relevant']} | 分數：{rec['score']}")
            print(f"  原始分類：{rec['filename']} → {rec.get('sub_category','')}")
            print(f"  標籤：{tags_str}")
            print()

        # 分類統計
        from collections import Counter
        cat_count = Counter(r["category"] for r in converted)
        rel_count = sum(1 for r in converted if r["is_relevant"])
        print(f"[預覽] 分類統計：")
        for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1]):
            print(f"  {cat:<22} {cnt} 筆")
        print(f"\n  預計寫入相關文獻：{rel_count}/{len(converted)} 筆")
        print(f"\n[Dry Run 結束] 確認無誤後移除 --dry-run 正式執行")
        return

    # 初始化資料庫
    conn = init_db(db_path)
    print(f"\n[資料庫] {db_path} 已就緒")

    # 批次寫入
    added = 0
    skipped = 0
    for rec in converted:
        if insert_record(conn, rec):
            added += 1
        else:
            skipped += 1

    conn.close()

    # 完成統計
    from collections import Counter
    cat_count = Counter(r["category"] for r in converted)
    rel_count = sum(1 for r in converted if r["is_relevant"])

    print(f"\n{'='*60}")
    print(f"  匯入完成！")
    print(f"  成功寫入：{added} 筆")
    print(f"  重複跳過：{skipped} 筆")
    print(f"  相關文獻：{rel_count} 筆")
    print(f"\n  分類分佈：")
    for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1]):
        marker = "✓" if RELEVANT_MAP.get(cat) else "○"
        print(f"  {marker} {cat:<22} {cnt} 筆")
    print(f"\n  下一步：執行 python scheduler.py 開始搜尋新文獻")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="將既有 xlsx 文獻分類清單匯入 SQLite 資料庫（一次性執行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python import_existing.py                          # 使用預設路徑
  python import_existing.py --dry-run                # 預覽，不寫入
  python import_existing.py --xlsx "D:/Reference/文獻分類清單.xlsx"
  python import_existing.py --db my_literature.db   # 指定資料庫路徑
        """
    )
    parser.add_argument("--xlsx", default=DEFAULT_XLSX,
                        help=f"xlsx 路徑（預設：{DEFAULT_XLSX}）")
    parser.add_argument("--db",   default=DEFAULT_DB,
                        help=f"資料庫路徑（預設：{DEFAULT_DB}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="預覽模式：只顯示轉換結果，不寫入資料庫")
    args = parser.parse_args()

    run_import(
        xlsx_path=args.xlsx,
        db_path=args.db,
        dry_run=args.dry_run,
    )