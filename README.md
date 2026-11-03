# 🐱 YouTube Shorts 可愛貓咪全雲端自動化印鈔機 (已綁定新頻道 `UC5P8yj_8TUhOrFsdp0qn-IQ`)

* **你的專屬目標頻道網址**：[https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ](https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ)
* **目標頻道 ID 安全鎖**：`UC5P8yj_8TUhOrFsdp0qn-IQ`（已寫入 `upload_youtube.py` 與 `get_refresh_token.py` 防呆驗證，**100% 確保只會發佈到這個新頻道，絕不誤發到你的個人主號**）

## ✅ 第一步：新頻道後台必做 2 個黃金獲利設定（2 分鐘完成）

既然頻道 [https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ](https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ) 已經創立完成，請先打開 [YouTube Studio (studio.youtube.com)](https://studio.youtube.com/)（確認右上角頭像已切換到此新頻道），點擊左下角 **「設定 (Settings)」→「頻道 (Channel)」**：

1. **設定「非專為兒童打造」以保住 100% 廣告單價**：
   * 切換到 **「進階設定 (Advanced settings)」** 分頁。
   * 在「觀眾 (Audience)」下方，勾選 **「否，不要將這個頻道設定為『專為兒童打造』，我從未上傳專為兒童打造的內容」**。
   * 這能避免 YouTube 因為可愛貓咪畫風而誤關閉你的個人化高單價廣告、留言區與推薦導流。

2. **開啟「中階與進階功能」解鎖 API 自動發片**：
   * 切換到 **「功能使用資格 (Feature eligibility)」** 分頁。
   * 點擊第 2 項「中階功能」完成手機簡訊驗證，並開啟第 3 項「進階功能」，確保 GitHub Actions 每天透過 API 自動上傳暢通無阻。

## 🚀 第二步：3 分鐘把程式包丟上 GitHub Actions（先跑出第一支貓咪短片！）

1. **建立 GitHub 私人儲存庫並上傳檔案**：
   * 前往 [GitHub 建立新儲存庫 (github.com/new)](https://github.com/new)，名稱填寫 `yt-cat-shorts-bot`，勾選 **Private（私人）** 後點擊 **Create repository**。
   * 點擊頁面上的 **「uploading an existing file」**，將解壓縮後的專案檔案（包含 `.github/workflows/daily_shorts.yml`、`main.py`、`upload_youtube.py`、`get_refresh_token.py`、`topics_queue.json`、`requirements.txt`）全部拖曳進去，點擊 **Commit changes**。
   * *(注意：請確保 `.github/workflows/daily_shorts.yml` 的資料夾路徑完整保留，或在 GitHub 點擊 **Actions → set up a workflow yourself** 把 `daily_shorts.yml` 內容貼上)*。

2. **一鍵測試雲端自動產片（免填任何金鑰即可立刻看成品！）**：
   * 點擊 GitHub 上方的 **「Actions」** 分頁 → 點選左側 **「Daily Cute Cat YouTube Shorts Factory」** → 點擊右側 **「Run workflow」** 綠色按鈕。
   * 等待約 2 分鐘，GitHub 就會自動配好英文語音、算好 4 張 9:16 皮克斯 3D 風可愛貓咪圖並壓上圓角字幕。
   * 跑完後拉到頁面最下方 **Artifacts**，即可直接下載 `generated-cat-short-1` 裡面的 `final_short.mp4`，你甚至可以現在直接手動把它上傳到 [https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ](https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ) 當作開台第一支影片！

## 🔑 第三步：綁定 `UC5P8yj_8TUhOrFsdp0qn-IQ` 啟動每日無人值守自動上架

當你要讓 GitHub 每天台灣時間晚上 20:00 自動幫你發片到 [https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ](https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ) 時，只需設定以下 GitHub Secrets（進入儲存庫 **Settings → Secrets and variables → Actions → New repository secret**）：

| Secret 名稱 | 用途說明 | 取得步驟 |
| ----- | ----- | ----- |
| `YT_CLIENT_ID` | Google Cloud OAuth 用戶端 ID | 1. 前往 [Google Cloud Console](https://console.cloud.google.com/) 建立一個新專案<br>2. 搜尋並啟用 **YouTube Data API v3**<br>3. 在「OAuth 同意畫面」將你自己的 Google 信箱加入「測試使用者 (Test users)」<br>4. 在「憑證 (Credentials)」建立 **OAuth 用戶端 ID（應用程式類型選：桌面應用程式 Desktop App）**，下載 JSON 並改名為 `client_secret.json` |
| `YT_CLIENT_SECRET` | Google Cloud OAuth 密鑰 | 同上，建立憑證時一併顯示 |
| `YT_REFRESH_TOKEN` | 綁定 `UC5P8yj_8TUhOrFsdp0qn-IQ` 的永久授權碼 | 在電腦把 `client_secret.json` 與 `get_refresh_token.py` 放在同一個資料夾，執行 `python get_refresh_token.py`；在瀏覽器跳出選擇頻道時，**點選你新創的這個頻道**，程式會自動核對 ID 是否為 `UC5P8yj_8TUhOrFsdp0qn-IQ` 並印出 Token |
| `GEMINI_API_KEY` *(選填)* | 每日無限自動編寫全新貓咪故事 | 前往 [Google AI Studio](https://aistudio.google.com/) 免費申請一組 API Key 貼上；未填時會自動從 `topics_queue.json` 劇本庫挑選 |
