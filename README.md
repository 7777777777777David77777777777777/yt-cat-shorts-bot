# 時尚寫真：develop 測試指南

這個分支讀取你手寫的 Markdown，生成四張照片，再合成 **無配音、無字幕、有 BGM** 的直式寫真 MP4。
目前 EP01 是「辦公秘書寫真｜黑絲襪與高跟鞋」，主角是虛構的 28 歲成年女性 Ava，預設使用真實風格。

**修改劇本請編輯 [stories/EP01.md](stories/EP01.md)。README 是操作說明，程式不會把它當劇本讀取。**

## 目前四幕內容

| 幕次 | 展示內容 |
| --- | --- |
| 第 1 幕 | 辦公室窗邊全身站姿，建立人物、穿搭與光線參考 |
| 第 2 幕 | 腰部以上人像，轉肩回望鏡頭、輕觸頭髮 |
| 第 3 幕 | 桌旁側身站姿，展示窄裙、黑絲襪與高跟鞋搭配 |
| 第 4 幕 | 椅上自然坐姿，雙膝靠攏、腳踝輕交叉 |

四幕維持同一位成年模特兒、同一套象牙白緞面襯衫、深灰窄裙、黑色 20 丹絲襪與七公分黑色高跟鞋。
以妝髮、合身剪裁、自信表情和姿勢呈現寫真感。標題可用中文，不會疊加在照片上。

第 1 幕先生成全身圖，第 2～4 幕每次都把**第 1 幕圖片**附在 Gemini 請求中作固定參考，
再指定不同姿勢、角度或細節構圖。參考不會逐幕接續，以免偏差累積。
提示詞會要求保留臉部、髮型、衣料、釦子、腰頭、裙長、絲襪透明度、鞋型與跟高；這能改善一致性，仍不能保證細節完全不變。
目前不會自動判定第 1 幕服裝是否正確；人工檢查時若發現參考圖已經偏離設定，應先修改該幕再重新測試。

## 1. 修改劇本

1. 開啟 [stories/EP01.md](stories/EP01.md)，確認 GitHub 分支是 **develop**。
2. 點編輯鉛筆，修改角色、衣服顏色、氛圍或畫面內容。
3. 保留檔案的標題結構，修改完提交到 **develop**。

| Markdown 區段 | 填寫內容 |
| --- | --- |
| `# EP01` | 集數 ID，使用 EP 加數字 |
| `## 標題` | 影片標題，保留你寫的文字 |
| `## 氛圍` | 展示風格或氛圍，會加入產圖提示詞 |
| `## 標籤` | 半形逗號分隔，可留空 |
| `## 角色` | 每行以 `- ` 開頭；支援 1～3 位，本範本使用 1 位成年女性 |
| `## 第1幕` 至 `## 第4幕` | 固定四張照片，各自需要 `### 畫面` |
| `### 畫面` | 該幕希望生成的構圖、服裝細節與姿勢 |

不需要填旁白；舊 Markdown 即使保留 `### 旁白`，寫真模式也不會朗讀或製成字幕。
程式直接讀取你的內容，不呼叫 AI 改寫劇本或添加標題尾綴。
你也可以新增 `stories/EP02.md` 等檔案；目前只接受 `stories/` 內的 **Markdown（.md）劇本**。

## 2. 手動執行測試

1. 前往 [GitHub Actions](https://github.com/7777777777777David77777777777777/yt-cat-shorts-bot/actions)。
2. 點原有的 **Hourly 6x Cute Cat YouTube Shorts Factory** → **Run workflow**。
3. **Branch 務必選 develop**；`main` 是正式發布流程。
4. `script_path` 填 `stories/EP01.md`，`visual_style` 選 `photorealistic`（真實風格）。
5. `scene_seconds` 預設每張 5 秒，四張共 20 秒；亦可選 4 或 6 秒。
6. `bgm_path` 留空使用程式合成的簡單 96 BPM 無人聲配樂，再執行。

如果表單沒有顯示上述欄位，develop 程式也會使用這些預設值。
其他可選畫風：`cinematic_3d`、`cel_anime`、`watercolor`、`clay_stop_motion`、`paper_diorama`。

develop 的 workflow 名稱是 **Handwritten Script Preview (develop only)**；左側顯示名稱可能仍取自 main。
執行時先檢查劇本及自訂 BGM，成功後才產圖；缺少角色或場景時會先停止。

替換配樂時，將有權使用的 `.wav`、`.mp3` 或 `.m4a` 放進 [assets/bgm/](assets/bgm/README.md)，
提交到 develop，再將 `bgm_path` 填為例如 `assets/bgm/my-track.mp3`。
音樂會循環至片尾，並調整音量及淡入淡出。預設合成伴奏不需要額外音樂 API 或金鑰。

## 3. 下載 MP4

執行完成後，開啟該次紀錄，在 **Artifacts** 下載 `script-preview-…`，解壓縮並播放 **preview.mp4**。

成品為 1080×1920 直式 MP4，照片有輕微推拉與柔和轉場，音軌只有 BGM；沒有配音、字幕、進度條或飄浮粒子。
下載檔也包含每幕圖片、BGM、實際產圖提示詞，以及自動產生的 `metadata.json` 執行紀錄。
紀錄內包含參考檔名、音樂及圖片 SHA-256、秒數與用量，可核對後三幕是否使用相同參考；不需要你編輯 JSON。
失敗時仍會備份已取得的素材與錯誤資訊。

目前是靜態分鏡合成預覽；真正的角色肢體動畫仍在暫緩計畫中。

## 設定與費用

使用既有 repository Actions secret **GEMINI_API_KEY** 生成四張圖片。
預設模型是 `gemini-2.5-flash-image`；如需其他相容圖像模型，可設定 Actions variable `GEMINI_IMAGE_MODEL`。
每幕最多一次產圖請求，失敗就停止，不產生純色備援圖；產圖依 Google 專案計費。
後三幕的請求包含圖片輸入，會增加輸入用量；實際 token 以 API 回報為準，不估算或保證價格。

推送劇本不會自動產圖，只有手動執行才會呼叫產圖 API。本測試不讀寫 Sheet、不上傳 YouTube，也不帶入其 credentials。
公開儲存庫內的劇本、日誌與下載產物可被其他人看到；develop 分支不是私密空間。

只檢查格式、不呼叫 API，可在安裝專案依賴後執行：

```bash
python script_preview.py --script stories/EP01.md --validate-only
```

## 其他計畫與正式產線

- [暫緩的圖生影片計畫](docs/animation-plan.md)：保留研究結果，等頻道有流量後再評估。
- [main 分支正式流程說明](https://github.com/7777777777777David77777777777777/yt-cat-shorts-bot/blob/main/README.md)：目前頻道的排程、上傳及中文標題功能以 main 為準。

本次測試與文件調整不修改 main 正式產線。
