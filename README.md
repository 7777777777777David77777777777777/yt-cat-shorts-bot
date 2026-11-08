# Cute Cat Shorts Factory

從 Google Sheet 讀取四～六幕劇本，產生配音與分鏡圖片，合成直式 Shorts，再上傳 YouTube 並回寫發送紀錄。

目標頻道：[PET PET](https://www.youtube.com/channel/UC5P8yj_8TUhOrFsdp0qn-IQ)。目前 `upload_youtube.py` 會核對授權頻道 ID，若與 `UC5P8yj_8TUhOrFsdp0qn-IQ` 不符就停止上傳。

## 目前流程

1. 讀取 Sheet 中第一個未完成、發送次數小於 6 的集數。優先嘗試 CSV，失敗後改用 Apps Script Webhook。
2. 沿用該集的三角色設定及四～六幕台詞／動作，依發送次數選擇本版畫風、配音與標題尾綴。
3. 依有效幕數生成四～六張圖片及對應配音，透過 FFmpeg 合成 `output/final_short.mp4`，並保存 `output/metadata.json`（包含 `scene_count`）。
4. YouTube 上傳成功後，透過 Webhook 更新 B 欄狀態、C 欄次數，並將網址、產圖用量、模型與畫風追加到六幕表的 V 欄（舊四幕表為 R 欄）。
5. 同一集完成六次發送後，下一次執行選取下一集。EP11、EP20 等集數也能讀取，沒有只支援前十集的限制。

API 上傳時會自動指定影片原音語言 `defaultAudioLanguage` 為 `en-US`（英文／美國）。
上傳前會用現有 `GEMINI_API_KEY` 呼叫一次 `gemini-3.5-flash-lite`，把標題與說明翻成
中文（台灣）繁體中文，透過 `localizations.zh-TW` 與英文原稿一併上傳。
可用 repository Actions variable `GEMINI_TRANSLATION_MODEL` 指定其他相容文字模型。
API 要求 `defaultLanguage: en` 標記標題／說明的英文原文；這不限制觀看地區。
翻譯失敗或格式無效時會在影片上傳前停止，避免漏掉中文版本。翻譯結果及實際 token 用量保存於
`output/metadata.json`，翻譯 token 也會追加在網址欄的用量摘要中，與產圖 token 分開。
這會增加一次文字 API 請求，依 Google 專案額度計費；不新增中文配音或字幕。
YouTube 自動配音需在 YouTube Studio 中依頻道可用功能啟用；目前上傳程式不控制此功能，
也不保證每支影片都會生成其他語言配音。標題／說明的多語言版本是另一項本地化設定。
只套用之後的上傳；既有影片的語言設定不會因此更新。

若 CSV 與 Webhook 都無法取得有效劇本，程式會停止；不會改用內建 EP01 或 `topics_queue.json`。片單全部完成時，目前也會停止並使產片步驟失敗，尚未實作「成功略過」。

## Google Sheet 欄位

使用第一個工作表，六幕表保留 A～V 欄，也相容舊四幕 A～R 表。現有中控台表頭位於第 7 列，劇本從第 8 列開始；CSV 依欄名定位，Apps Script 依表頭辨識四幕／六幕格式，再按下表讀寫固定位置，不以總欄數猜測。

CSV 來源由 `main.py` 的 `SHEET_ID` 決定，Webhook 來源由 Apps Script 綁定的試算表決定，兩者應指向同一份片單。更換試算表時需一併核對來源及部署網址。

| 欄位 | 內容 |
| --- | --- |
| A | 集數 ID，例如 `EP01`、`EP11` |
| B | 發佈狀態，例如 `待發佈 (Ready)`、`連發中 (Sending)`、`已完成 (Completed)` |
| C | 已發送次數，從 `0` 開始，目標為 `6`；可讀取數字或 `k/6` 格式 |
| D | 該集固定的劇本類型與氛圍，不可空白 |
| E／F／G | 角色 1／2／3 的設定 |
| H／I | 第一幕英文旁白／畫面動作 |
| J／K | 第二幕英文旁白／畫面動作 |
| L／M | 第三幕英文旁白／畫面動作 |
| N／O | 第四幕英文旁白／畫面動作 |
| P／Q | 第五幕英文旁白／畫面動作 |
| R／S | 第六幕英文旁白／畫面動作 |
| T | YouTube 標題 |
| U | SEO 標籤，以半形逗號分隔 |
| V | 已發布影片網址與本次產圖用量紀錄 |

升級現有四幕表時，在原 P 欄標題之前插入四欄；標題／標籤／網址隨之移至 T／U／V。舊四幕表仍使用 P 標題、Q 標籤、R 網址。更新 Apps Script 的原有 Web App 部署，讓讀取與回寫同時套用新位置。

前四幕必填；第五、六幕全空時保留四幕，只填第五幕成對內容時製作五幕，兩幕成對填完時製作六幕。只填旁白或動作其中一項、或跳過第五幕直接填第六幕，會在產圖前停止。程式不會自動補寫新劇情。

旁白欄只填實際台詞，不要放 `Character 3:` 或 `Scene 1:` 等設定標籤。各幕動作應與旁白一致，角色的物種、外觀與相對體型寫在 E～G 欄。六幕表示每支影片的幕數；每日六次發送與畫風輪替是另外的設定。

### D 欄與六版畫風

**D 欄會分成敘事氛圍與共同環境，加入各幕產圖提示詞。** 推薦格式：

```text
懸疑反差喜劇｜固定場景：Dim 3AM modern living room with gray fabric sofa, low oak coffee table, beige rug, and warm amber floor nightlight under cool blue moonlight
```

「固定場景」亦可寫「共同場景」「場景設定」或 `Shared setting:`、`Common setting:`、`Setting:`。場景內容只讀取標籤後、下一個 `｜` 或 `|` 之前的文字，不會從沒有標籤的 D 欄任意猜測環境；有標籤但內容空白時停止，提示補齊。

類型中的喜劇、溫馨、懸疑、冒險、奇幻、科幻、驚悚、浪漫與催淚等關鍵字，會對應到簡短的英文敘事氛圍，不會直接把 D 欄原文整段當美術風格。未識別的類型保留在 metadata 並記錄於日誌，不補造提示詞；舊的 `3D Pixar animation style` 不會蓋過畫風輪替。

提示詞明確規定：**當幕動作中的出場角色、姿勢、表情、景別與角度優先；明寫的地點、時間、天氣與光線也優先於共同環境。** 當幕未另行指定時才沿用共同環境。特寫只呈現構圖範圍內合理可見的環境，不為了湊齊沙發、桌子等物件而改成全景；類型氛圍不能自行新增角色、動作、道具，或把懸疑、催淚自動解讀成夜晚與下雨。

程式不會自動改寫 H～S 台詞或動作，也不增加額外 AI 分析請求。`story_genre` 保存 D 欄原文，`story_context` 保存解析後的氛圍與共同環境，各幕 `full_image_prompt` 可核對真正送出的內容。這些是提供給產圖模型的優先順序，無法保證每張圖片完全遵守。

D 欄表頭可使用「劇本類型」「劇本類型與氛圍」「故事類型」「劇本風格」，也相容舊的「視覺畫風 DNA」。Apps Script 仍以舊欄名 `art_dna` 傳回 D 欄；缺少 `art_dna` 的錯誤也可能只是該格空白。

美術畫風由 `main.py` 的 `VISUAL_STYLE_ROTATION` 控制，與 D 欄分開：

| 本集第幾次發送 | 執行前 C 欄 | 指定畫風 |
| --- | --- | --- |
| 1／6 | 0 | 3D 電影動畫 |
| 2／6 | 1 | 日系 2D 動畫 |
| 3／6 | 2 | 水彩繪本 |
| 4／6 | 3 | 黏土定格 |
| 5／6 | 4 | 立體紙雕 |
| 6／6 | 5 | 真實風格 |

同一版的所有分鏡共用同一種畫風；六版沿用同一集的劇情與角色。原有配音及標題尾綴輪替仍保留。畫風依既有發送次數接續，更新程式不會重置 C 欄。

提示詞會完整傳送，不再截斷為前 280 字元，並要求 9:16 滿版、背景延伸到四邊、無邊框或上下空白帶。字幕區要求延續場景背景且保持低細節，不是留下空白區塊。

### 當幕角色篩選

角色描述請使用 `Agent Oreo, a black-and-white tuxedo cat ...` 這種「名字在前、逗號後描述外觀」的格式；每幕畫面動作盡量直接寫出出場角色名字。程式只比對該幕動作，不會因旁白提到其他角色就強迫其入鏡。完整名字及無歧義的短名皆可比對，忽略大小寫並使用完整詞邊界。

例如 `Extreme close-up of Agent Oreo pushing a pen over the table edge` 只注入 Oreo 的角色描述；若動作同時提及 Don Ginger 與 Rookie Puff，三者仍會注入。要改成單貓特寫，必須同步移除該幕動作中其他角色的出場描述。

`All three`、`everyone` 等群體描述保留全部角色；只寫「橘貓」而未提名字時保守保留原角色表，不猜是哪一隻。若句子寫 `Kenji pets a cat`，已辨識 Kenji 但貓未寫名字，會補入角色表中的貓，避免漏掉互動對象。其他代名詞與描述不能保證準確辨識，建議每幕直接點名。`metadata.json` 每幕的 `character_indices` 保存實際注入的原始角色編號（1～3），`character_selection` 與日誌記錄篩選／備援方式。

這是本機文字規則，不增加 API 請求，也不自動更改角色欄或劇本。角色欄仍應只保留固定外觀，避免「招手」「坐在桌邊」等動作每次出場都重複注入。縮減角色描述能減少干擾，但無法保證模型完全遵守出場名單或正確畫出動作。

這些是對模型的要求，無法保證每張圖片都完全遵守。角色欄的公分、體重與相對比例也是文字約束，不是精確的跨幕幾何鎖定。目前圖片仍直接縮放至 1080×1920，尚未實作等比例裁切或留白自動檢測。

## GitHub Actions 設定

工作流程是 [Hourly 6x Cute Cat YouTube Shorts Factory](<.github/workflows/Hourly 6x Cute Cat YouTube Shorts Factory.yml>)，CI 使用 Python 3.11，單次 job 設定 25 分鐘逾時。

### Secrets 與選填設定

到儲存庫 **Settings → Secrets and variables → Actions** 設定，勿將密鑰寫進程式、Sheet 或提交紀錄。

| 名稱 | 用途 | 目前工作流程 |
| --- | --- | --- |
| `SHEET_WEBHOOK_URL` | Apps Script 的 `/exec` 部署網址，用於私有片單讀取與狀態回寫 | 已傳入產片及上傳步驟 |
| `GEMINI_API_KEY` | Google AI Studio API 金鑰，用於產圖及中文標題／說明翻譯 | 已傳入產片及上傳步驟 |
| `YT_CLIENT_ID` | YouTube OAuth 用戶端 ID | 已傳入上傳步驟 |
| `YT_CLIENT_SECRET` | YouTube OAuth 用戶端密鑰 | 已傳入上傳步驟 |
| `YT_REFRESH_TOKEN` | 目標頻道的 OAuth refresh token | 已傳入上傳步驟 |
| `HF_TOKEN` | 選填，啟用 Hugging Face 分支 | 尚未傳入，需另加至產片步驟的 `env` |
| `GEMINI_IMAGE_MODEL` | 選填，指定其他相容的 Gemini 圖像模型 | 尚未傳入；預設為 `gemini-2.5-flash-image` |
| `GEMINI_TRANSLATION_MODEL` | 選填，指定中文翻譯文字模型（Variable） | 已傳入上傳步驟；預設為 `gemini-3.5-flash-lite` |

只在 GitHub 設定頁新增 Secret 或 Variable，不會自動把它傳入程式；選填設定也需在工作流程的 `env` 明確引用。`GEMINI_IMAGE_MODEL` 是模型名稱，不是密鑰。

YouTube 授權需先啟用 Google Cloud 專案的 YouTube Data API v3、設定 OAuth 同意畫面及桌面應用程式用戶端。將下載的 OAuth JSON 在本機命名為 `client_secret.json`，執行 `python get_refresh_token.py`，登入並選取目標品牌頻道，再將取得的值安全存入 Secrets。不要提交 JSON 或終端印出的密鑰；refresh token 可能因撤銷授權或 OAuth 專案狀態而失效，並非保證永久有效。

### 排程與手動執行

```yaml
on:
  schedule:
    - cron: '7 12-17 * * *'
  workflow_dispatch:
```

UTC 每日 12:07～17:07，換算台灣時間為 **20:07、21:07、22:07、23:07、隔日 00:07、01:07**，每日六個預定時段。

GitHub 排程只在預設分支運作，且可能延遲或丟失事件。07 分用來避開整點高峰，不能保證準時；實際啟動及影片上架時間也會受排隊、產圖、合成與上傳耗時影響。Actions 列表顯示 `Scheduled` 才是排程觸發，`Manually run` 是手動執行。

手動測試請至 **Actions → Hourly 6x Cute Cat YouTube Shorts Factory → Run workflow → 選 main**。重跑舊執行通常沿用舊提交；測試最新程式應新開執行。

**目前工作流程在 YouTube 憑證齊全時會直接公開上傳影片，不是只產片的預覽模式。**

## Apps Script 部署與回填

1. 從 Sheet 開啟 **擴充功能 → Apps Script**。
2. 以 [google_apps_script.gs](google_apps_script.gs) 全文取代舊程式並儲存。它使用綁定試算表的第一個工作表。
3. 至 **部署 → 管理部署 → 編輯 → 新版本 → 部署** 更新原有 Web App，確認執行身分與存取設定可供 GitHub Actions 呼叫。
4. 將該部署的 `/exec` 網址存為 `SHEET_WEBHOOK_URL`。更新同一個部署通常保留網址；如果建立了另一個部署，需同步更新 Secret。

只儲存編輯器內容，不會更新既有 `/exec` 的已部署版本。

### 確認目前部署

在部署網址後加上 `?action=status`，進行唯讀檢查。預期回應包含：

```json
{
  "status": "ok",
  "script_version": "six-scenes-usage-v3",
  "scene_capacity": 6,
  "url_column": 22
}
```

以上是六幕表的回應；舊四幕表會回傳 `scene_capacity: 4`、`url_column: 18`。完整回應還會提供試算表 ID 與工作表 ID，請核對是否為目標片單。主程式讀取及回寫時也會記錄版本資訊；若顯示「未回報部署版本」，應確認部署版本與 Secret 指向的網址。

### 網址紀錄與舊資料修復

目前 `doPost` 在六幕表從 V 欄讀寫網址，保留 H～S 劇情及 T／U 標題／標籤；舊四幕表仍從 R 欄讀寫。它會核對集數與列號，同一網址重送時不重複追加。

舊四幕表歷史上已被寫進 Q 欄的網址，不會因更新部署自動搬移。插入六幕欄位之前，可在 Apps Script 編輯器選取 `repairLegacyUrlRecords` 並手動執行一次：僅搬移可辨識的整行 Shorts 網址到 R 欄、去除重複網址，保留 Q 欄標籤、發送次數與狀態。此函式不發布影片，也不補算舊影片的 token。六幕表的 Q／R 已經是劇本欄，因此此函式會拒絕執行，避免誤搬劇情。

新集數可接續放在現有資料之後；保持三角色與各幕欄位完整，D 欄填固定類型、B 欄填 `待發佈 (Ready)`、C 欄填 `0`。若中控台統計公式仍只涵蓋第 8～17 列，需另外延伸統計範圍。

## 產圖、用量與成品

### 產圖服務順序

1. 若有 `HF_TOKEN`，依序嘗試 Hugging Face 的 `FLUX.1-schnell`、`FLUX.1-dev`。
2. 若有 `GEMINI_API_KEY`，使用 Gemini Developer API 的 `generate_content()`，預設模型為 `gemini-2.5-flash-image`；可用性、權限及配額由 Google 專案決定。
3. 前述分支未啟用或失敗時，改試 Pollinations 的 `flux`。該名稱是服務端模型代稱，程式沒有確認其確切後端版本。

目前工作流程傳入 Gemini 金鑰，但未傳入 HF 金鑰。Gemini 呼叫失敗後仍可能退回 Flux，請以每幕日誌及 `metadata.json` 的 `image_usage` 確認實際模型。

語音優先使用 Edge TTS，失敗時改用 FFmpeg 的 flite。API 產圖、可用性與費用不保證免費或無限制；Gemini 金鑰目前不會用來自動寫新故事。

### token 與模型紀錄

`metadata.json` 保存每次產圖呼叫的模型、場景、採用情況及 API 回報的 token，用量摘要隨影片網址回寫到六幕 V 欄／舊四幕 R 欄，亦包含本版畫風。六幕會依序生成六張圖與六段配音，用量以實際回報累計。

- 只採用 API 實際回報的數字；沒有提供時顯示「產圖 token：未提供」，不填成 0。
- 若部分呼叫未提供用量，顯示「已回報產圖 token」小計及未提供用量的請求數，不將小計當作完整總量。
- API 請求數是程式記錄的產圖呼叫次數，成功圖片數是本次採用的圖片數；不代表服務商帳單。
- 此紀錄限於產圖，不包含語音、FFmpeg 或 YouTube 上傳用量。費用以各供應商帳單為準。

### 成品與已知限制

正常成功執行後，Actions 的 `cat-short-run-<執行編號>` Artifact 會保存下列檔案，保留七天：

```text
output/final_short.mp4
output/metadata.json
```

第 7 步備份使用 `always()`：翻譯或上傳失敗時，仍會備份已生成的 MP4 與 metadata。
翻譯失敗的模型、HTTP 代碼及經遮蔽的原因會寫入日誌及 metadata 的 `translation_error`。

目前產圖服務全部失敗時，程式仍可能以純色圖合成影片。既有圖片檢查只驗證檔案與色彩變化，無法確認角色數量、物種、肢體、體型比例或情節是否正確；公開發布前應檢查成品。YouTube 上傳成功但 Sheet 回寫失敗時，發送次數可能未前進，重新執行有重複發布的風險。

## 常見問題

| 現象 | 意義與處理方式 |
| --- | --- |
| CSV `HTTP 401` | CSV 無法直接存取，程式會嘗試 Webhook；若 Webhook 可正常回傳，不需為此將片單公開。 |
| 缺少 `art_dna` | 先檢查待處理集數的 D 欄是否空白，再確認 Webhook 有回傳 `art_dna`、`genre` 或 `genre_dna`。 |
| 旁白出現 `Character three`、標題變成 `Scene 4` | 舊兩角色欄位讀到了已插入角色 3 的片單。部署最新版 Apps Script；主程式只修復符合已知完整位移模式的舊回應。 |
| 網址仍留在 Q 欄 | 區分歷史資料與新回寫。更新部署、確認版本，再視需要執行舊網址搬移函式。 |
| Gemini 失敗後仍有影片 | 可能改用了 Flux，或最後使用純色備援圖；檢查每幕日誌與採用模型。 |
| 圖片上下留白或角色被拉伸 | 滿版提示詞不能保證模型遵守；目前仍需檢查原圖，尚無自動留白檢測及等比例裁切。 |
| `uploadLimitExceeded` | YouTube 頻道／使用者的上傳數量限制，與 Gemini token 不同。暫停反覆產片重試，依 YouTube 通知等待限制恢復，並檢查頻道功能使用資格。 |
| 上傳成功但沒有網址新紀錄 | 六幕表查看 V 欄、舊四幕表查看 R 欄；檢查回寫錯誤、部署版本、Secret 網址與集數列號，先確認 YouTube 是否已發布再重試。 |
| 流程顯示成功但沒有新影片 | 缺少任一 YouTube OAuth 環境變數時，上傳程式會印出提示並略過；檢查第 6 步日誌，不能只看工作流程綠勾。 |

## 本機開發與檢查

需要 Python 3.11、FFmpeg、ffprobe，以及 Liberation 字型。CI 透過 Ubuntu 套件安裝 `ffmpeg`、`fonts-liberation`、`fonts-noto-cjk`；FFmpeg 的 flite 功能用於語音備援。

在專案根目錄安裝 Python 依賴，虛擬環境可放在 checkout 外：

```bash
python3.11 -m venv ../yt-cat-shorts-venv
source ../yt-cat-shorts-venv/bin/activate
python -m pip install -r requirements.txt
```

透過安全的環境變數提供 Webhook 與 API 金鑰後，分別執行：

```bash
# 只生成影片與 metadata
python main.py

# 會公開上傳影片，並嘗試回寫 Sheet
python upload_youtube.py
```

測試指令：

```bash
python -m unittest discover -s tests -v
node tests/test_apps_script.cjs
```

現有測試涵蓋 Sheet 欄位對應、六版畫風、完整提示詞傳遞、Gemini SDK 請求格式、用量紀錄及 Apps Script 回填／搬移邏輯；外部 API 與 Sheet 寫入使用模擬，通過測試不代表線上金鑰、配額或生成品質已驗證。Node.js 僅用於 Apps Script 的本機測試。

OAuth 檔案、密鑰、虛擬環境及產出的影片不應提交至儲存庫。

## 發布與營利

目前上傳程式固定使用 `privacyStatus: public` 與 `selfDeclaredMadeForKids: false`，尚未實作逐片觀眾屬性設定或人工審核閘門。觀眾屬性需依影片實際內容與目標受眾判斷，確認符合目前設定後再使用自動公開上傳。

「兒童專屬」觀眾設定與「兒童安全」社群規範是不同問題；AI 製作的內容也需符合相關規範。不要為了廣告收益而錯誤設定觀眾屬性。

自動產片、六種畫風或開通頻道功能，都不保證點閱、收益、無上傳限制或通過營利審查。同一故事大量重複發布也需留意內容的原創性與實質差異。
