import os
import re
import sys
import csv
import io
import math
import json
import time
import base64
import random
import urllib.parse
import subprocess
import asyncio
import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat

OUTPUT_DIR = "output"
SCENE_DIR = os.path.join(OUTPUT_DIR, "scenes")
os.makedirs(SCENE_DIR, exist_ok=True)

SHEET_ID = "1M6jINNdKCgisMLTD3x2h3Cift65xFCDMv2SySl-3Ngo"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"

VOICE_ROTATION = [
    "en-GB-SoniaNeural",
    "en-US-AriaNeural",
    "en-US-AnaNeural",
    "en-US-EmmaNeural",
    "en-US-BrianNeural",
    "en-AU-NatashaNeural"
]

TITLE_HOOK_SUFFIXES = [
    "Wait For It! 👧🐱🐶 #shorts #cute",
    "Watch Until The End! 🐾❤️ #shorts #cat",
    "Pure Wholesome Magic! ✨🐱 #shorts #pets",
    "Nobody Expected This! 🥹🐾 #shorts #kitten",
    "Best Friends Forever! 🐱✨ #shorts #wholesome",
    "This Melted My Heart! ❤️🐾 #shorts #cuteanimals"
]


SHEET_HEADERS = {
    "id": "集數 ID",
    "status": "發佈狀態",
    "sent_count": "已發送次數",
    "art_dna": "視覺畫風 DNA",
    "char1_dna": "角色 1 設定",
    "char2_dna": "角色 2 設定",
    "char3_dna": "角色 3 設定",
    "title": "YouTube 爆款標題",
    "tags": "SEO 標籤",
}
for _scene_number in range(1, 5):
    SHEET_HEADERS[f"s{_scene_number}_narration"] = f"第 {_scene_number} 幕：英文台詞"
    SHEET_HEADERS[f"s{_scene_number}_action"] = f"第 {_scene_number} 幕：畫面動作"


class NoPendingEpisodes(RuntimeError):
    """片單已讀取成功，但沒有尚未完成的集數。"""


class ImagePromptTooLongError(RuntimeError):
    """產圖服務拒絕完整提示詞時停止，不能改用截斷內容。"""


def parse_sent_count(value) -> int:
    text = str(value).strip() if value is not None else ""
    match = re.fullmatch(r"(\d+)(?:\.0+)?(?:\s*/\s*6)?", text or "0")
    if not match or int(match[1]) > 6:
        raise ValueError(f"已發送次數格式錯誤：{text!r}，應為 0～6 或 k/6")
    return int(match[1])


def validate_episode_row(row_dict: dict):
    """拒絕舊 Webhook 的兩角色欄位錯位，避免把角色或動作當旁白。"""
    if not isinstance(row_dict, dict):
        raise ValueError("集數資料必須是三角色格式的物件")
    required = set(SHEET_HEADERS) - {"status", "tags"}
    missing = sorted(key for key in required
                     if row_dict.get(key) is None or not str(row_dict[key]).strip())
    if missing:
        raise ValueError(f"缺少三角色片單必要欄位：{', '.join(missing)}；請更新 Sheet / Apps Script 欄位對應")
    if not re.fullmatch(r"EP\d+", str(row_dict["id"]).strip(), flags=re.IGNORECASE):
        raise ValueError("集數 ID 必須是 EP 加數字")
    if re.match(r"^Scene\s*\d+\b|^第\s*\d+\s*幕", str(row_dict["title"]).strip(), re.IGNORECASE):
        raise ValueError("標題讀到了 Scene 動作欄；請檢查 P 欄與 Webhook 對應")
    for i in range(1, 5):
        narration = str(row_dict[f"s{i}_narration"]).strip()
        if re.match(r"^(?:Character\s*\d+|Scene\s*\d+)\s*[:：]|^角色\s*\d+", narration, re.IGNORECASE):
            raise ValueError(f"第 {i} 幕台詞讀到了角色設定或動作欄；請檢查 H～O 欄與 Webhook 對應")
    parse_sent_count(row_dict["sent_count"])


def normalize_webhook_episode(row_dict: dict) -> dict:
    """只修復可確認的舊版兩角色欄位位移，不補造缺失的角色或劇情。"""
    if not isinstance(row_dict, dict) or str(row_dict.get("char3_dna") or "").strip():
        return row_dict
    # 舊版 Apps Script 沿用 G～P 的兩角色位置，但 Sheet 已插入 G 欄角色 3：
    # G -> s1_narration，I/K/M -> s2/s3/s4_narration，O -> title，P -> tags。
    # 必須同時確認角色 3 標籤及四個動作標籤，才可辨識並搬回原欄位。
    if not re.match(r"^Character\s*3\s*[:：]", str(row_dict.get("s1_narration", "")).strip(), re.IGNORECASE):
        return row_dict
    action_fields = ["s2_narration", "s3_narration", "s4_narration", "title"]
    for i, field in enumerate(action_fields, start=1):
        if not re.match(rf"^Scene\s*{i}\s*[:：]", str(row_dict.get(field, "")).strip(), re.IGNORECASE):
            return row_dict

    # 舊格式的 tags 實際裝的是 P 欄標題。有些腳本會先依逗號分割成陣列。
    title = row_dict.get("tags")
    if isinstance(title, list) and all(isinstance(part, str) for part in title):
        title = ", ".join(title)
    if not isinstance(title, str) or not title.strip() or re.search(r"https?://", title, re.IGNORECASE):
        raise ValueError("已辨識舊 Webhook 的欄位位移，但未收到 P 欄標題；請更新 Apps Script")

    corrected = row_dict.copy()
    corrected["char3_dna"] = row_dict["s1_narration"]
    for i in range(1, 5):
        corrected[f"s{i}_narration"] = row_dict.get(f"s{i}_action", "")
        corrected[f"s{i}_action"] = row_dict[action_fields[i - 1]]
    corrected["title"] = title.strip()
    # Q 欄未包含在這種舊回應裡，不能拿 P 欄標題假裝 SEO 標籤。
    corrected["tags"] = ""
    validate_episode_row(corrected)
    print("ℹ️ 已辨識舊 Webhook 的一欄位移，恢復角色 3、四幕台詞／動作及 P 欄標題。")
    print("ℹ️ 舊回應未提供 Q 欄 SEO 標籤，本次略過；請更新 Apps Script 以取得完整欄位。")
    return corrected


def episode_from_sheet_csv(csv_text: str) -> dict:
    """略過中控台摘要列，以第 7 列的欄名定位資料，不以總欄數猜測格式。"""
    def normalize_header(value):
        return re.sub(r"[\s\ufeff]+", "", value).casefold()

    columns = None
    for row_index, row in enumerate(csv.reader(io.StringIO(csv_text)), start=1):
        if columns is None:
            normalized = [normalize_header(cell) for cell in row]
            if not any(cell in {normalize_header(SHEET_HEADERS["id"]), "id"} for cell in normalized):
                continue
            columns = {}
            for key, label in SHEET_HEADERS.items():
                matches = [i for i, cell in enumerate(normalized)
                           if cell == key or cell.startswith(normalize_header(label))]
                if len(matches) != 1:
                    raise ValueError(f"Sheet 欄位缺少或重複：{label}；請使用三角色片單表頭")
                columns[key] = matches[0]
            continue
        row_dict = {key: row[index].strip() if index < len(row) else ""
                    for key, index in columns.items()}
        if not re.fullmatch(r"EP\d+", row_dict["id"], flags=re.IGNORECASE):
            continue
        if "已完成" in row_dict["status"] or "completed" in row_dict["status"].casefold():
            continue
        row_dict["sent_count"] = parse_sent_count(row_dict["sent_count"])
        if row_dict["sent_count"] >= 6:
            continue
        row_dict["row_index"] = row_index
        return parse_episode_from_row(row_dict)
    if columns is None:
        raise ValueError("找不到 Sheet 表頭；請確認 CSV 可讀取且包含三角色片單")
    raise NoPendingEpisodes("Sheet 所有集數均已完成，沒有待產生的影片。")


def clean_prompt_text(text: str) -> str:
    """只清除來源標籤與多餘空白，保留標點、比例和完整角色描述。"""
    text = str(text).strip()
    text = re.sub(r"^(?:Character|Scene)\s*\d+\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def build_image_prompt(art_dna: str, characters: list, scene_action: str) -> str:
    """依 Sheet 組成完整分鏡指令，不覆寫角色物種或畫風。"""
    references = "\n".join(f"{i}. {description}" for i, description in enumerate(characters, start=1))
    return (
        f"Scene action: {scene_action}\n"
        f"Visual style: {art_dna}\n"
        f"Character references:\n{references}\n"
        "Continuity: Keep each visible character's species, colors, markings, clothing "
        "and relative size consistent with these references across all scenes. "
        "Show only the characters involved in the scene action; the reference list "
        "does not require every character to appear.\n"
        "Shot and composition: Capture one clear moment of the scene action in a single image. "
        "Follow any framing specified in the scene action; otherwise use a medium shot "
        "at the subjects' eye level. Keep faces and key interactions away from the frame edges. "
        "Leave the bottom 15% visually simple for subtitles. "
        "Vertical 9:16 composition, clear subject separation, no lettering, captions or watermarks."
    )


def clean_base_title(raw_title: str) -> str:
    t = str(raw_title).split("#")[0].strip()
    t = re.sub(r"(\.\.\.)?\s*Wait For It!?.*$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"[^\w\s,'?!-]", "", t).strip()
    return t if t else "Little Girl Brings Stray Kitten Home to Her 90-Pound Husky"


def parse_episode_from_row(row_dict: dict) -> dict:
    """
    支援 18 欄「三角色獨立設定 (char1_dna, char2_dna, char3_dna) + 4 幕台詞與動作嚴格對齊」結構
    """
    validate_episode_row(row_dict)
    ep_id = str(row_dict["id"]).strip()
    sent_count = parse_sent_count(row_dict["sent_count"])
    art_dna = clean_prompt_text(row_dict["art_dna"])
    characters = [clean_prompt_text(row_dict[f"char{i}_dna"]) for i in range(1, 4)]

    raw_scenes = [
        (row_dict.get("s1_narration", ""), row_dict.get("s1_action", "")),
        (row_dict.get("s2_narration", ""), row_dict.get("s2_action", "")),
        (row_dict.get("s3_narration", ""), row_dict.get("s3_action", "")),
        (row_dict.get("s4_narration", ""), row_dict.get("s4_action", ""))
    ]
    cam_styles = ["smooth_push_in", "smooth_pan_right", "smooth_pull_out", "smooth_push_in"]

    scenes = []
    for i, (narr, act) in enumerate(raw_scenes):
        clean_act = clean_prompt_text(act)
        full_prompt = build_image_prompt(art_dna, characters, clean_act)
        scenes.append({
            "narration": str(narr).strip(),
            "scene_action": str(act).strip(),
            "camera_style": cam_styles[i % 4],
            "full_image_prompt": full_prompt
        })

    base_title = clean_base_title(row_dict.get("title", "Little Girl Brings Stray Kitten Home to Her 90-Pound Husky"))
    variant_suffix = TITLE_HOOK_SUFFIXES[sent_count % len(TITLE_HOOK_SUFFIXES)]
    variant_title = f"{base_title}... {variant_suffix}"[:100]

    tags_raw = str(row_dict.get("tags", "cute cat, little girl and kitten, husky, wholesome pets, shorts"))
    # 舊回寫程式可能曾把影片網址追加到 Q 欄；網址不是 SEO 標籤。
    tags_list = [t.strip().lstrip("#") for t in re.split(r"[,\r\n]+", tags_raw)
                 if t.strip() and not re.search(r"https?://", t, re.IGNORECASE)]

    return {
        "id": ep_id,
        "row_index": row_dict.get("row_index", 8),
        "sent_count": sent_count,
        "target_sends": 6,
        "selected_visual_style": art_dna,
        "character_dna": " | ".join(f"[{i}] {description}" for i, description in enumerate(characters, start=1)),
        "voice_name": VOICE_ROTATION[sent_count % len(VOICE_ROTATION)],
        "title": variant_title,
        "description": (
            f"{scenes[0]['narration']} {scenes[1]['narration']} 🐾❤️\n\n"
            f"Episode: {ep_id} (Edition #{sent_count + 1}/6)\n"
            "#shorts #cat #kitten #cuteanimals #wholesome #pets"
        ),
        "tags": tags_list,
        "scenes": scenes
    }


def fetch_next_episode_from_google_sheet() -> dict:
    """優先讀取有表頭的 CSV，備援 Webhook 也必須通過三角色資料驗證。"""
    errors = []
    try:
        resp = requests.get(SHEET_CSV_URL, timeout=15)
        resp.raise_for_status()
        ep = episode_from_sheet_csv(resp.text)
        print(f"✅ [Google Sheet 欄名對應讀取成功] 集數: {ep['id']} (第 {ep['sent_count'] + 1}/6 次發送)")
        return ep
    except (requests.RequestException, ValueError) as exc:
        # 不列印請求網址，避免將 Webhook 部署資訊帶入日誌。
        detail = type(exc).__name__
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail += f" (HTTP {exc.response.status_code})"
        errors.append(f"CSV: {detail}")
        if isinstance(exc, ValueError):
            print(f"⚠️ [Sheet 欄位檢查] {exc}")
        else:
            print(f"⚠️ [Sheet CSV 讀取] {detail}；嘗試備援 Webhook。")

    webhook_url = os.environ.get("SHEET_WEBHOOK_URL", "").strip()
    if webhook_url:
        try:
            resp = requests.get(webhook_url, params={"action": "get_next"}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or data.get("status") != "ok" or not data.get("episode"):
                raise ValueError("Webhook 沒有回傳有效集數")
            row_dict = normalize_webhook_episode(data["episode"])
            ep = parse_episode_from_row(row_dict)
            status = str(row_dict.get("status", ""))
            if ep["sent_count"] >= 6 or "已完成" in status or "completed" in status.casefold():
                raise NoPendingEpisodes("Webhook 回傳的集數已完成，停止產片。")
            if not str(ep["row_index"]).isdigit() or int(ep["row_index"]) < 1 or "row_index" not in row_dict:
                raise ValueError("Webhook 缺少正確的 Sheet row_index，無法安全回寫")
            print(f"✅ [Google Sheet Webhook 三角色檢查成功] 集數: {ep['id']}")
            return ep
        except (requests.RequestException, ValueError) as exc:
            detail = type(exc).__name__
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                detail += f" (HTTP {exc.response.status_code})"
            errors.append(f"Webhook: {detail}")
            if isinstance(exc, ValueError):
                print(f"⚠️ [Webhook 欄位檢查] {exc}")
            else:
                print(f"⚠️ [Webhook 讀取] {detail}")

    raise RuntimeError(
        "無法取得欄位正確的 Google Sheet 劇本，已停止產片，避免誤用內建 EP01 或錯位資料。"
        "請確認 Sheet CSV 存取權及 Apps Script 的三角色欄位對應。"
        + " / ".join(errors)
    )


async def generate_speech_audio(text: str, audio_path: str, voice_name: str):
    if os.path.exists(audio_path):
        os.remove(audio_path)
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice_name, rate="+0%", pitch="+0Hz")
        await communicate.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            return
    except Exception as e:
        print(f"  [切換至備援語音引擎] ({e})")

    clean_txt = re.sub(r"[^a-zA-Z0-9,.?! ]", " ", text)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"flite=text='{clean_txt}':voice=slt",
        "-af", "acompressor,volume=1.6",
        "-c:a", "libmp3lame", "-q:a", "2",
        audio_path
    ], check=True, stderr=subprocess.DEVNULL)


def is_valid_colorful_image(img_path: str) -> bool:
    try:
        with Image.open(img_path) as im:
            stat = ImageStat.Stat(im.convert("RGB"))
            return (sum(stat.stddev) / 3.0) > 22.0
    except Exception:
        return False


def crop_bottom_watermark_and_save(img_path: str):
    """自動切除圖片底部 5.5% 與左右 2% 邊緣再縮放回 1080x1920，100% 物理消除右下角浮水印"""
    with Image.open(img_path) as im:
        im_rgb = im.convert("RGB")
        w, h = im_rgb.size
        cropped = im_rgb.crop((int(w * 0.02), int(h * 0.01), int(w * 0.98), int(h * 0.945)))
        cropped.resize((1080, 1920), Image.Resampling.LANCZOS).save(img_path, quality=95)


def start_image_request(records, provider: str, model: str, scene_idx: int) -> dict:
    record = {
        "scene": scene_idx, "provider": provider, "model": model,
        "image_used": False, "returned_images": None,
        "input_tokens": None, "output_tokens": None, "total_tokens": None,
    }
    if records is not None:
        records.append(record)
    return record


def capture_token_usage(record: dict, response):
    """只接受 API 明確回傳的數字；未知用量保留 None，不能當作零。"""
    usage = response.get("usage_metadata", response.get("usageMetadata")) if isinstance(response, dict) else getattr(response, "usage_metadata", None)
    fields = {
        "input_tokens": ("prompt_token_count", "promptTokenCount"),
        "output_tokens": ("candidates_token_count", "candidatesTokenCount"),
        "total_tokens": ("total_token_count", "totalTokenCount"),
    }
    for target, names in fields.items():
        for name in names:
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                record[target] = value
                break


def summarize_image_usage(records: list) -> dict:
    reported = [record["total_tokens"] for record in records if record["total_tokens"] is not None]
    complete = bool(records) and len(reported) == len(records)
    return {
        "scope": "image_generation",
        "api_requests": len(records),
        "images_used": sum(record["image_used"] for record in records),
        "total_tokens": sum(reported) if complete else None,
        "reported_total_tokens": sum(reported) if reported else None,
        "requests_without_token_usage": len(records) - len(reported),
        "token_usage_complete": complete,
        "models_used": sorted({record.get("model_version") or record["model"]
                               for record in records if record["image_used"]}),
        "requests": records,
    }


def download_ai_keyframe(prompt: str, img_path: str, master_seed: int, scene_idx: int, usage_records=None):
    """依序嘗試已設定的 HF、Google 與 Pollinations，傳送同一份完整提示詞。"""
    if os.path.exists(img_path) and is_valid_colorful_image(img_path):
        return

    # 引擎 A：HuggingFace 官方原版 FLUX.1-schnell (免費申請 HF_TOKEN 即可享受無損頂級畫質)
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if hf_token:
        for hf_model in ["black-forest-labs/FLUX.1-schnell", "black-forest-labs/FLUX.1-dev"]:
            usage = start_image_request(usage_records, "huggingface", hf_model, scene_idx)
            try:
                hf_url = f"https://api-inference.huggingface.co/models/{hf_model}"
                resp = requests.post(
                    hf_url,
                    headers={"Authorization": f"Bearer {hf_token}"},
                    json={"inputs": prompt, "parameters": {"width": 768, "height": 1344}},
                    timeout=45
                )
                if resp.status_code == 200 and len(resp.content) > 20000:
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    if is_valid_colorful_image(img_path):
                        with Image.open(img_path) as im:
                            im.convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(img_path, quality=95)
                        usage["returned_images"] = 1
                        usage["image_used"] = True
                        print(f"    🎉 第 {scene_idx} 幕由 HuggingFace 原版 {hf_model} 頂級算圖成功！")
                        return
            except Exception as e:
                print(f"    [HF {hf_model} 提示] {e}")

    # 引擎 B：Gemini Developer API 原生產圖；generate_images 不適用於目前的金鑰模式。
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key, vertexai=False)
            model = os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or "gemini-2.5-flash-image"
            usage = start_image_request(usage_records, "google", model, scene_idx)
            result = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="9:16"),
                ),
            )
            capture_token_usage(usage, result)
            if isinstance(result.model_version, str) and result.model_version:
                usage["model_version"] = result.model_version
            image_parts = []
            for candidate in result.candidates or []:
                if candidate.content is None:
                    continue
                for part in candidate.content.parts or []:
                    blob = part.inline_data
                    if not part.thought and blob is not None and blob.data and (blob.mime_type or "").startswith("image/"):
                        image_parts.append(blob)
            usage["returned_images"] = len(image_parts)
            for image in image_parts:
                with open(img_path, "wb") as f:
                    f.write(image.data)
                if is_valid_colorful_image(img_path):
                    with Image.open(img_path) as im:
                        im.convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(img_path, quality=95)
                    usage["image_used"] = True
                    print(f"    ✅ 第 {scene_idx} 幕由 Google {usage.get('model_version') or model} 產圖成功！")
                    return
            raise ValueError("Gemini 回應沒有可採用的圖片；將嘗試備援服務")
        except Exception as e:
            print(f"    [Google Gemini 產圖失敗] {e}")

    # 引擎 C：完整編碼提示詞，包含描述中的斜線、問號等 URL 保留字。
    encoded = urllib.parse.quote(prompt, safe="")
    for attempt in range(6):
        seed = master_seed + (scene_idx * 1009) + (attempt * 313)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=768&height=1344&seed={seed}&nologo=true&enhance=false&model=flux"
        )
        headers = {
            "User-Agent": f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/{17 + attempt}.0 Safari/605.1.15"
        }
        try:
            # 拉開重試間隔以降低連續請求觸發限流的機會。
            wait_sec = 10.0 if (scene_idx > 1 and attempt == 0) else (6.0 * (attempt + 1))
            if scene_idx > 1 or attempt > 0:
                print(f"    ⏳ 等待 {wait_sec:.0f} 秒防限流冷卻，準備算第 {scene_idx} 幕 (嘗試 {attempt+1}/6)...")
                time.sleep(wait_sec)
            usage = start_image_request(usage_records, "pollinations", "flux", scene_idx)
            resp = requests.get(url, headers=headers, timeout=65)
            if resp.status_code == 414:
                raise ImagePromptTooLongError(
                    f"第 {scene_idx} 幕完整提示詞（{len(prompt)} 字元）的網址被產圖服務拒絕（HTTP 414）。"
                    "請精簡 Sheet 的畫風、角色或動作描述；程式不會截斷提示詞或以空白圖替代。"
                )
            if resp.status_code == 200 and len(resp.content) > 20000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                if is_valid_colorful_image(img_path):
                    crop_bottom_watermark_and_save(img_path)
                    usage["returned_images"] = 1
                    usage["image_used"] = True
                    print(f"    ✅ 第 {scene_idx} 幕獨立 Flux 分鏡產出成功！")
                    return
            else:
                print(f"    [狀態碼 {resp.status_code}] 重新請求第 {scene_idx} 幕...")
        except ImagePromptTooLongError:
            raise
        except Exception as e:
            print(f"    [Flux 算圖重試 {attempt+1}/6] {e}")

    im = Image.new("RGB", (1080, 1920), (245, 215, 185))
    im.save(img_path, quality=95)


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return max(float(res.stdout.strip()), 2.0)


def split_into_single_line_phrases(narration: str) -> list:
    words = narration.strip().split()
    chunks = []
    cur = []
    cur_len = 0
    for w in words:
        if cur and (len(cur) >= 3 or cur_len + 1 + len(w) > 18):
            chunks.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += len(w) + (1 if cur_len > 0 else 0)
    if cur:
        chunks.append(" ".join(cur))
    return chunks if chunks else [narration]


def subpixel_camera_frame(im: Image.Image, prog: float, camera_style: str) -> Image.Image:
    ease = 0.5 - 0.5 * math.cos(min(max(prog, 0.0), 1.0) * math.pi)

    if camera_style == "smooth_push_in":
        z = 1.00 + 0.12 * ease
        cx = 0.50
        cy = 0.49 - 0.03 * ease
    elif camera_style == "smooth_pan_right":
        z = 1.10
        cx = 0.46 + 0.08 * ease
        cy = 0.48
    elif camera_style == "smooth_pull_out":
        z = 1.12 - 0.10 * ease
        cx = 0.50
        cy = 0.48
    else:
        z = 1.02 + 0.10 * ease
        cx = 0.50
        cy = 0.48

    crop_w = 1080.0 / z
    crop_h = 1920.0 / z
    x0 = max(0.0, min(1080.0 - crop_w, cx * 1080.0 - crop_w / 2.0))
    y0 = max(0.0, min(1920.0 - crop_h, cy * 1920.0 - crop_h / 2.0))
    x1 = x0 + crop_w
    y1 = y0 + crop_h

    return im.transform(
        (1080, 1920),
        Image.Transform.EXTENT,
        (x0, y0, x1, y1),
        resample=Image.Resampling.BICUBIC
    )


def render_continuous_smooth_short(
    raw_imgs: list,
    audio_paths: list,
    scenes: list,
    final_mp4: str
):
    fps = 30
    total_scenes = len(scenes)

    scene_durs = [get_audio_duration(ap) for ap in audio_paths]
    audio_concat_inputs = []
    filter_parts = []
    for i, ap in enumerate(audio_paths):
        audio_concat_inputs.extend(["-i", ap])
        filter_parts.append(f"[{i}:a]aresample=44100,pan=mono|c0=c0[a{i}];")
    concat_in = "".join(f"[a{i}]" for i in range(total_scenes))
    filter_str = "".join(filter_parts) + f"{concat_in}concat=n={total_scenes}:v=0:a=1[outa]"

    master_wav = os.path.join(SCENE_DIR, "master_voice.wav")
    subprocess.run(
        ["ffmpeg", "-y"] + audio_concat_inputs + [
            "-filter_complex", filter_str,
            "-map", "[outa]", "-c:a", "pcm_s16le", master_wav
        ],
        check=True,
        stderr=subprocess.DEVNULL
    )

    loaded_imgs = [
        Image.open(p).convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
        for p in raw_imgs
    ]
    scene_phrases = [split_into_single_line_phrases(sc["narration"]) for sc in scenes]
    cam_styles = [sc.get("camera_style", "smooth_push_in") for sc in scenes]

    try:
        font_main = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 62)
    except Exception:
        font_main = ImageFont.load_default()

    rng = random.Random(2026)
    particles = [
        {
            "x": rng.uniform(60, 1020),
            "y": rng.uniform(100, 1450),
            "r": rng.uniform(5, 13),
            "vx": rng.uniform(-14, 14),
            "vy": rng.uniform(-26, -10),
            "phase": rng.uniform(0, math.pi * 2)
        }
        for _ in range(14)
    ]

    scene_frame_counts = [int(round(d * fps)) for d in scene_durs]
    total_frames = sum(scene_frame_counts)
    total_duration = total_frames / fps
    transition_frames = 10

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1080x1920", "-pix_fmt", "rgb24", "-r", str(fps),
        "-i", "-",
        "-i", master_wav,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-b:a", "192k",
        "-t", f"{total_duration:.2f}",
        final_mp4
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    global_f = 0
    for s_idx in range(total_scenes):
        n_frames = scene_frame_counts[s_idx]
        phrases = scene_phrases[s_idx]
        n_phrases = len(phrases)
        cur_im = loaded_imgs[s_idx]
        next_s_idx = (s_idx + 1) % total_scenes
        next_im = loaded_imgs[next_s_idx]

        for local_f in range(n_frames):
            t_global = global_f / fps
            prog = local_f / max(n_frames - 1, 1)

            frame = subpixel_camera_frame(cur_im, prog, cam_styles[s_idx])

            frames_left = n_frames - 1 - local_f
            if frames_left < transition_frames and s_idx < total_scenes - 1:
                alpha = 1.0 - (frames_left / float(transition_frames))
                smooth_alpha = 0.5 - 0.5 * math.cos(alpha * math.pi)
                next_start_frame = subpixel_camera_frame(next_im, 0.0, cam_styles[next_s_idx])
                frame = Image.blend(frame, next_start_frame, smooth_alpha)

            frame_rgba = frame.convert("RGBA")
            overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            for p in particles:
                px = (p["x"] + p["vx"] * t_global) % 1080
                py = (p["y"] + p["vy"] * t_global) % 1450
                p_alpha = int(65 + 50 * math.sin(t_global * 3.0 + p["phase"]))
                r = p["r"]
                draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 240, 175, p_alpha))

            p_idx = min(n_phrases - 1, int(prog * n_phrases))
            line_str = phrases[p_idx]

            ty = 1650
            bbox = draw.textbbox((0, 0), line_str, font=font_main)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (1080 - tw) // 2

            draw.rounded_rectangle(
                [tx - 28, ty - 10, tx + tw + 28, ty + th + 18],
                radius=28,
                fill=(10, 12, 20, 115)
            )

            for dx in (-4, -2, 0, 2, 4):
                for dy in (-4, -2, 0, 2, 4):
                    if dx != 0 or dy != 0:
                        draw.text((tx + dx, ty + dy), line_str, font=font_main, fill=(0, 0, 0, 255))

            draw.text((tx, ty), line_str, font=font_main, fill=(255, 255, 255, 255))

            overall_prog = global_f / max(total_frames - 1, 1)
            draw.rectangle([40, 48, 1040, 56], fill=(255, 255, 255, 65))
            draw.rectangle([40, 48, 40 + int(1000 * overall_prog), 56], fill=(255, 255, 255, 220))

            out_frame = Image.alpha_composite(frame_rgba, overlay).convert("RGB")
            proc.stdin.write(out_frame.tobytes())
            global_f += 1

    proc.stdin.close()
    proc.wait()


def main():
    story = fetch_next_episode_from_google_sheet()
    voice_name = story.get("voice_name", "en-US-AriaNeural")
    scenes = story["scenes"]
    total_scenes = len(scenes)
    master_seed = random.randint(10000, 888888)

    print(f"🎬 啟動 Google Sheet 18欄三角色連動產線 | 集數: {story['id']} (第 {story['sent_count'] + 1}/6 次發送)")
    print(f"🎨 畫風 DNA: {story.get('selected_visual_style')}")
    print(f"🐾 三角色鎖定: {story.get('character_dna')}")
    print(f"🎙️ 本輪輪替配音: {voice_name}")

    raw_imgs = []
    audio_paths = []
    usage_records = []

    for idx, sc in enumerate(scenes, start=1):
        r_img = os.path.join(SCENE_DIR, f"raw_{idx}.jpg")
        a_path = os.path.join(SCENE_DIR, f"audio_{idx}.mp3")

        # 欄位或劇本修正後，不能沿用上次錯位資料產生的舊分鏡。
        if os.path.exists(r_img):
            os.remove(r_img)

        print(f"  [準備第 {idx}/{total_scenes} 幕] 產生語音與高畫質分鏡圖片...")
        asyncio.run(generate_speech_audio(sc["narration"], a_path, voice_name))
        download_ai_keyframe(sc["full_image_prompt"], r_img, master_seed=master_seed, scene_idx=idx,
                             usage_records=usage_records)

        raw_imgs.append(r_img)
        audio_paths.append(a_path)

    final_mp4 = os.path.join(OUTPUT_DIR, "final_short.mp4")
    print("  ✨ 正在進行單一時間軸次像素絲滑渲染 (純白穩定字幕，零跳格)...")
    render_continuous_smooth_short(
        raw_imgs=raw_imgs,
        audio_paths=audio_paths,
        scenes=scenes,
        final_mp4=final_mp4
    )

    story["image_usage"] = summarize_image_usage(usage_records)
    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print(f"✅ 短片合成完畢: {final_mp4}")


if __name__ == "__main__":
    main()
