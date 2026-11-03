"""
【一次性授權小工具（已綁定頻道 ID: UC5P8yj_8TUhOrFsdp0qn-IQ）】
在你電腦執行此檔案一次，登入並選擇你新建立的「YouTube 品牌頻道 (https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ)」，
程式會自動核對頻道 ID 是否為 UC5P8yj_8TUhOrFsdp0qn-IQ，確認無誤後印出 YT_REFRESH_TOKEN！
"""
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
TARGET_CHANNEL_ID = "UC5P8yj_8TUhOrFsdp0qn-IQ"


def main():
    print("=== YouTube 新頻道 Refresh Token 取得與頻道核對工具 ===")
    print(f"目標綁定頻道: https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ")
    print("請先將從 Google Cloud Console 下載的 OAuth JSON 改名為 client_secret.json 放在同資料夾。")
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

    youtube = build("youtube", "v3", credentials=creds)
    ch_resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = ch_resp.get("items", [])

    if items:
        ch_id = items[0]["id"]
        ch_title = items[0]["snippet"]["title"]
        print(f"\n🔍 偵測到你剛才選擇的頻道為：【{ch_title}】 (ID: {ch_id})")
        if ch_id != TARGET_CHANNEL_ID:
            print(f"⚠️ 注意！你剛才選到的頻道 ID ({ch_id}) 不是你的新頻道 (UC5P8yj_8TUhOrFsdp0qn-IQ)！")
            print("請重新執行一次 python get_refresh_token.py，並在瀏覽器跳出「選擇帳戶/品牌頻道」時，點選你新創的頻道！")
            return
        print("✅ 頻道 ID 核對完全正確！已開啟防呆保護，絕不會誤發到個人主帳號。")

    print("\n🎉 授權成功！請將以下 3 個值複製到 GitHub Repository -> Settings -> Secrets and variables -> Actions：\n")
    print(f"YT_CLIENT_ID:     {creds.client_id}")
    print(f"YT_CLIENT_SECRET: {creds.client_secret}")
    print(f"YT_REFRESH_TOKEN: {creds.refresh_token}")


if __name__ == "__main__":
    main()
