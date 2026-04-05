"""
git_sync.py — 自動將 CSV 推送到 GitHub
每次 scheduler.py 執行完後呼叫，讓 Streamlit Cloud 讀到最新資料
"""

import subprocess
import os
from datetime import datetime
from pathlib import Path


def run_cmd(cmd: str, cwd: str = None) -> tuple[bool, str]:
    """執行指令，回傳 (成功與否, 輸出訊息)"""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "指令超時"
    except Exception as e:
        return False, str(e)


def sync_to_github(project_dir: str = None, csv_path: str = None):
    """
    把 CSV 檔案推送到 GitHub
    project_dir: 專案根目錄（預設為目前目錄）
    csv_path: CSV 檔案路徑（預設為 exports/literature_export.csv）
    """
    if project_dir is None:
        project_dir = str(Path(__file__).parent)

    if csv_path is None:
        csv_path = os.path.join(project_dir, "exports", "literature_export.csv")

    print(f"\n[Git Sync] 開始推送至 GitHub...")

    # 確認 CSV 存在
    if not os.path.exists(csv_path):
        print(f"  [Git Sync] 找不到 CSV：{csv_path}，跳過推送")
        return False

    # 確認是 git repo
    ok, _ = run_cmd("git status", cwd=project_dir)
    if not ok:
        print(f"  [Git Sync] 此目錄不是 git repo，請先執行 git init")
        return False

    # git add CSV
    ok, out = run_cmd(f'git add exports/literature_export.csv', cwd=project_dir)
    if not ok:
        print(f"  [Git Sync] git add 失敗：{out}")
        return False

    # 確認是否有變更（避免空 commit）
    ok, out = run_cmd("git diff --cached --stat", cwd=project_dir)
    if not out.strip():
        print(f"  [Git Sync] CSV 無變更，略過本次推送")
        return True

    # git commit
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"更新文獻資料 {now}"
    ok, out = run_cmd(f'git commit -m "{commit_msg}"', cwd=project_dir)
    if not ok:
        print(f"  [Git Sync] git commit 失敗：{out}")
        return False

    # git push
    ok, out = run_cmd("git push origin main", cwd=project_dir)
    if not ok:
        print(f"  [Git Sync] git push 失敗：{out}")
        print(f"  請確認已設定 GitHub 認證（Personal Access Token 或 SSH Key）")
        return False

    print(f"  [Git Sync] 推送成功：{commit_msg}")
    return True


if __name__ == "__main__":
    sync_to_github()