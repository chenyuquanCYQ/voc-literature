"""
Git_sync.py — 保留為向後相容的入口
實際的 JSON 匯出與 git push 邏輯已移至 export_to_json.py，
與 odor-dashboard 採用相同的 list-based subprocess 寫法（無 shell=True）。
"""

from export_to_json import main as export_json


def sync_to_github(project_dir: str = None, csv_path: str = None):
    """呼叫 export_to_json.main()，同時匯出 JSON 並推送至 GitHub。"""
    export_json()


if __name__ == "__main__":
    sync_to_github()
