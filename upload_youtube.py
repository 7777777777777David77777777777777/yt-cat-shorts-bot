import os
import sys
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
TARGET_CHANNEL_ID = "UC5P8yj_8TUhOrFsdp0qn-IQ"


def upload_short():
    client_id = os.environ.get("YT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("YT_REFRESH_TOKEN", "").strip()

    if not (client_id and client_secret and refresh_token):
        print("⚠️ 尚未在 GitHub Secrets 設定 YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN。")
        print("影片已成功產出於 output/final_short.mp4，請於 GitHub Actions Artifacts 下載或補齊金鑰後自動上傳。")
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

    # 安全鎖：驗證當前授權的頻道是否為指定的新頻道 (UC5P8yj_8TUhOrFsdp0qn-IQ)，避免誤發到個人主帳號
    ch_resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = ch_resp.get("items", [])
    if not items:
        print("❌ 找不到對應的 YouTube 頻道，請重新執行 get_refresh_token.py 授權。")
        sys.exit(1)

    current_channel_id = items[0]["id"]
    current_channel_title = items[0]["snippet"]["title"]
    print(f"🔍 目前授權頻道: {current_channel_title} (ID: {current_channel_id})")

    if current_channel_id != TARGET_CHANNEL_ID:
        print(f"🛑 安全攔截！目前 Token 授權的頻道 ID ({current_channel_id}) 與你指定的新頻道 ({TARGET_CHANNEL_ID}) 不符！")
        print("請重新執行 get_refresh_token.py，並在彈出視窗中點選你的新品牌頻道，確保不會誤發到個人主頻道。")
        sys.exit(1)

    with open("output/metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)

    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"],
            "tags": meta.get("tags", ["shorts", "cat", "cute"]),
            "categoryId": "15"  # 15 = Pets & Animals (寵物與動物，全球高流量分類)
        },
        "status": {
            "privacyStatus": "public",
            # 關鍵獲利設定：設為 False (非專為兒童打造)，保住個人化高單價廣告與留言區
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload("output/final_short.mp4", chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"🎉 已成功自動上傳至你的新頻道【{current_channel_title}】！")
    print(f"🎬 影片網址: https://youtube.com/shorts/{response['id']}")


if __name__ == "__main__":
    upload_short()
