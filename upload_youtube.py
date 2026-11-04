import os
import sys
import json
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
TARGET_CHANNEL_ID = "UC5P8yj_8TUhOrFsdp0qn-IQ"


def report_back_to_google_sheet(meta: dict, youtube_url: str):
    """
    【方案 B：自動回寫 Google Sheet】
    當影片成功發佈到 YouTube 後，自動呼叫 Google Apps Script Webhook (`SHEET_WEBHOOK_URL`)：
    1. 將該集的 `已發送次數` + 1 (例如 0 -> 1, ..., 5 -> 6)
    2. 若未滿 6 次，狀態更新為 `連發中 (k/6)`；一旦滿 6 次，狀態自動改為 `已完成 (Completed)`，下一輪就會自動換下一集！
    3. 將本次新發佈的 YouTube Shorts 網址追加記錄到 Q 欄
    """
    webhook_url = os.environ.get("SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ℹ️ 尚未設定 SHEET_WEBHOOK_URL，略過試算表狀態回寫。")
        return

    payload = {
        "action": "mark_sent",
        "id": meta.get("id", "EP01"),
        "row_index": meta.get("row_index", 0),
        "new_sent_count": int(meta.get("sent_count", 0)) + 1,
        "target_sends": int(meta.get("target_sends", 6)),
        "youtube_url": youtube_url
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=20)
        if resp.status_code == 200:
            print(f"📊 已同步回寫 Google Sheet！集數 {payload['id']} 發送進度: {payload['new_sent_count']}/6")
    except Exception as e:
        print(f"⚠️ 回寫 Google Sheet 失敗 ({e})")


def upload_short():
    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YT_REFRESH_TOKEN", "").strip()

    if not (client_id and client_secret and refresh_token):
        print("⚠️ 尚未在 GitHub Secrets 設定 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN。")
        return

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES
    )

    youtube = build("youtube", "v3", credentials=creds)

    ch_resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = ch_resp.get("items", [])
    if not items:
        print("❌ 找不到對應的 YouTube 頻道，請重新執行 get_refresh_token.py 授權。")
        sys.exit(1)

    current_channel_id = items[0]["id"]
    current_channel_title = items[0]["snippet"]["title"]
    print(f"🔍 目前授權頻道: {current_channel_title} (ID: {current_channel_id})")

    if current_channel_id != TARGET_CHANNEL_ID:
        print(f"🛑 安全攔截！目前授權頻道 ({current_channel_id}) 與目標新頻道 ({TARGET_CHANNEL_ID}) 不符！")
        sys.exit(1)

    with open("output/metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)

    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"],
            "tags": meta.get("tags", ["shorts", "cat", "cute"]),
            "categoryId": "15"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload("output/final_short.mp4", chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    yt_url = f"https://youtube.com/shorts/{response['id']}"
    print(f"🎉 已成功上傳至新頻道【{current_channel_title}】！網址: {yt_url}")

    # 自動回寫發送次數 (1/6 ~ 6/6) 與網址至 Google Sheet
    report_back_to_google_sheet(meta, yt_url)


if __name__ == "__main__":
    upload_short()
