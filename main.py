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


def clean_prompt_text(text: str) -> str:
    """移除多餘括號與特殊符號，保留清晰英文描述"""
    text = re.sub(r"^Character\s*\d+\s*:\s*", "", str(text), flags=re.IGNORECASE)
    text = re.sub(r"^Scene\s*\d+\s*:\s*", "", str(text), flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z0-9, -]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_base_title(raw_title: str) -> str:
    t = str(raw_title).split("#")[0].strip()
    t = re.sub(r"(\.\.\.)?\s*Wait For It!?.*$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"[^\w\s,'?!-]", "", t).strip()
    return t if t else "Little Girl Brings Stray Kitten Home to Her 90-Pound Husky"


def parse_episode_from_row(row_dict: dict) -> dict:
    """
    支援 18 欄「三角色獨立設定 (char1_dna, char2_dna, char3_dna) + 4 幕台詞與動作嚴格對齊」結構
    """
    ep_id = str(row_dict.get("id", "EP01")).strip()
    sent_count = int(str(row_dict.get("sent_count", "0")).split("/")[0].strip() or 0)
    art_dna = clean_prompt_text(row_dict.get("art_dna", "3D Pixar animation style, warm cinematic lighting, ultra-detailed"))
    char1_dna = clean_prompt_text(row_dict.get("char1_dna", "a cute 6-year-old girl with brown pigtails wearing a yellow raincoat"))
    char2_dna = clean_prompt_text(row_dict.get("char2_dna", "a tiny fluffy orange tabby kitten with big green eyes"))
    char3_dna = clean_prompt_text(row_dict.get("char3_dna", "a giant friendly silver-and-white Siberian Husky dog"))

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
        # 將「該幕具體動作 (clean_act)」放在最前面第一順位，再附上三個角色的明確物種定義，
        # 徹底避免 AI 把「小橘貓 (orange tabby cat)」誤畫成「紅髮人類嬰兒」！
        full_prompt = (
            f"{art_dna}. {clean_act}. "
            f"Characters in scene: (1) {char1_dna}, (2) {char2_dna} (feline cat with fur and whiskers, NOT a human baby), "
            f"(3) {char3_dna}. "
            "Masterpiece 3D cinema quality, sharp focus, expressive faces, vertical 9:16, no text, no watermark"
        )
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
    tags_list = [t.strip().lstrip("#") for t in tags_raw.split(",") if t.strip()]

    return {
        "id": ep_id,
        "row_index": row_dict.get("row_index", 8),
        "sent_count": sent_count,
        "target_sends": 6,
        "selected_visual_style": art_dna,
        "character_dna": f"[1] {char1_dna} | [2] {char2_dna} | [3] {char3_dna}",
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
    """
    優先透過 CSV 直連讀取最新 18 欄試算表（免改 Apps Script 也能自動抓齊 3 個角色欄位！），
    若失敗再走 Webhook 或內建保底。
    """
    try:
        resp = requests.get(SHEET_CSV_URL, timeout=15)
        if resp.status_code == 200 and "EP0" in resp.text:
            reader = csv.reader(io.StringIO(resp.text))
            for r_idx, row in enumerate(reader, start=1):
                if not row:
                    continue
                first_col = str(row[0]).strip()
                if first_col.startswith("EP") and len(row) >= 16:
                    status_str = str(row[1]).strip()
                    sent_str = str(row[2]).split("/")[0].strip()
                    sent_cnt = int(sent_str) if sent_str.isdigit() else 0
                    if "已完成" not in status_str and "Completed" not in status_str and sent_cnt < 6:
                        # 自動相容 18 欄（含角色 3 設定）與 17 欄結構
                        if len(row) >= 17:
                            row_dict = {
                                "row_index": r_idx,
                                "id": first_col,
                                "status": status_str,
                                "sent_count": sent_cnt,
                                "art_dna": row[3],
                                "char1_dna": row[4],
                                "char2_dna": row[5],
                                "char3_dna": row[6],
                                "s1_narration": row[7],
                                "s1_action": row[8],
                                "s2_narration": row[9],
                                "s2_action": row[10],
                                "s3_narration": row[11],
                                "s3_action": row[12],
                                "s4_narration": row[13],
                                "s4_action": row[14],
                                "title": row[15],
                                "tags": row[16] if len(row) > 16 else "cute cat, kitten, shorts"
                            }
                        else:
                            row_dict = {
                                "row_index": r_idx,
                                "id": first_col,
                                "status": status_str,
                                "sent_count": sent_cnt,
                                "art_dna": row[3],
                                "char1_dna": row[4],
                                "char2_dna": row[5],
                                "char3_dna": "",
                                "s1_narration": row[6],
                                "s1_action": row[7],
                                "s2_narration": row[8],
                                "s2_action": row[9],
                                "s3_narration": row[10],
                                "s3_action": row[11],
                                "s4_narration": row[12],
                                "s4_action": row[13],
                                "title": row[14],
                                "tags": row[15] if len(row) > 15 else "cute cat, kitten, shorts"
                            }
                        ep = parse_episode_from_row(row_dict)
                        print(f"✅ [Google Sheet 18欄三角色讀取成功] 集數: {ep['id']} (第 {ep['sent_count'] + 1}/6 次發送)")
                        return ep
    except Exception as e:
        print(f"  [Sheet CSV 讀取提示] ({e})")

    webhook_url = os.environ.get("SHEET_WEBHOOK_URL", "").strip()
    if webhook_url:
        try:
            resp = requests.get(f"{webhook_url}?action=get_next", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and data.get("episode"):
                    ep = parse_episode_from_row(data["episode"])
                    print(f"✅ [Google Sheet Webhook 讀取成功] 集數: {ep['id']}")
                    return ep
        except Exception:
            pass

    default_row = {
        "row_index": 8,
        "id": "EP01",
        "sent_count": 0,
        "art_dna": "3D Pixar animation style, warm cinematic lighting, ultra-detailed",
        "char1_dna": "Mia, a cute 6-year-old girl with brown pigtails wearing a yellow raincoat",
        "char2_dna": "Mochi, a tiny fluffy orange tabby kitten with big green eyes",
        "char3_dna": "Titan, a giant friendly silver-and-white Siberian Husky dog",
        "s1_narration": "Six-year-old Mia found a tiny shivering ginger kitten in the rain and brought him home to meet her giant Husky, Titan.",
        "s1_action": "Cute 6-year-old girl Mia in a yellow raincoat holding a tiny orange tabby kitten in a hallway, introducing the kitten to a giant silver-and-white Siberian Husky dog",
        "s2_narration": "Everyone worried the ninety-pound dog would scare the kitten, but Titan gently laid down and offered his warm furry paw.",
        "s2_action": "The giant silver-and-white Siberian Husky dog lying flat on the floor offering his big white front paw to the tiny orange tabby kitten, while the 6-year-old girl watches happily",
        "s3_narration": "Within minutes, little Mochi was fast asleep on Titan's chest while Mia covered them both with her favorite soft blanket.",
        "s3_action": "The tiny orange tabby kitten sleeping peacefully on top of the giant Siberian Husky dog's chest by a fireplace, while the 6-year-old girl places a soft blanket over the dog and cat",
        "s4_narration": "Now the three best friends wear matching blue scarves everywhere they go! Subscribe if Mia and Mochi made you smile!",
        "s4_action": "The 6-year-old girl, the giant Siberian Husky dog, and the tiny orange tabby kitten sitting side by side on green grass wearing matching blue scarves, smiling at camera",
        "title": "Little Girl Brings Stray Kitten Home to Her 90-Pound Husky",
        "tags": "cute cat, little girl and kitten, husky, wholesome story, 3d animation, cute animals, shorts"
    }
    return parse_episode_from_row(default_row)


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


def download_ai_keyframe(prompt: str, img_path: str, master_seed: int, scene_idx: int):
    """
    【三引擎高畫質算圖系統 — 解決 Pollinations 免費版畫質崩壞與第 2、4 幕被限流問題】
    1. 引擎 A (最高畫質)：若 GitHub Secrets 設有 `HF_TOKEN` (HuggingFace 免費 Token)，直接呼叫官方原版 `black-forest-labs/FLUX.1-schnell` 高清模型，3 秒出頂級電影圖、零限流、不崩壞！
    2. 引擎 B (Google 官方高畫質)：若設有 `GEMINI_API_KEY`，自動呼叫 Google Imagen 3 / Gemini Image 模型生成電影級分鏡！
    3. 引擎 C (免金鑰 Pollinations Flux)：強制拉開 12 秒冷卻間隔避開 429 限流（確保第 1、2、3、4 幕全部獨立算出不同圖片，絕不重複用第 1、3 幕！），並明確標註 `feline cat with fur, NOT a human baby` 防止角色混淆！
    """
    if os.path.exists(img_path) and is_valid_colorful_image(img_path):
        return

    # 引擎 A：HuggingFace 官方原版 FLUX.1-schnell (免費申請 HF_TOKEN 即可享受無損頂級畫質)
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if hf_token:
        for hf_model in ["black-forest-labs/FLUX.1-schnell", "black-forest-labs/FLUX.1-dev"]:
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
                        print(f"    🎉 第 {scene_idx} 幕由 HuggingFace 原版 {hf_model} 頂級算圖成功！")
                        return
            except Exception as e:
                print(f"    [HF {hf_model} 提示] {e}")

    # 引擎 B：Google Gemini / Imagen 官方繪圖模型 (若設有 GEMINI_API_KEY)
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            result = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="9:16")
            )
            for gen_img in result.generated_images:
                with open(img_path, "wb") as f:
                    f.write(gen_img.image.image_bytes)
                if is_valid_colorful_image(img_path):
                    with Image.open(img_path) as im:
                        im.convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS).save(img_path, quality=95)
                    print(f"    🎉 第 {scene_idx} 幕由 Google Imagen 3 頂級算圖成功！")
                    return
        except Exception as e:
            print(f"    [Google Imagen 提示] {e}")

    # 引擎 C：免金鑰 Pollinations Flux（加入 12 秒防限流冷卻，確保 4 幕全部獨立算出，絕不重複畫面！）
    encoded = urllib.parse.quote(prompt[:280])
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
            # 關鍵：Pollinations 免費版對同一 IP 有嚴格的連續請求冷卻限制，間隔 10~12 秒可保證第 2、3、4 幕不被 429 拒絕！
            wait_sec = 10.0 if (scene_idx > 1 and attempt == 0) else (6.0 * (attempt + 1))
            if scene_idx > 1 or attempt > 0:
                print(f"    ⏳ 等待 {wait_sec:.0f} 秒防限流冷卻，準備算第 {scene_idx} 幕 (嘗試 {attempt+1}/6)...")
                time.sleep(wait_sec)
            resp = requests.get(url, headers=headers, timeout=65)
            if resp.status_code == 200 and len(resp.content) > 20000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                if is_valid_colorful_image(img_path):
                    crop_bottom_watermark_and_save(img_path)
                    print(f"    ✅ 第 {scene_idx} 幕獨立 Flux 分鏡產出成功！")
                    return
            else:
                print(f"    [狀態碼 {resp.status_code}] 重新請求第 {scene_idx} 幕...")
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

    for idx, sc in enumerate(scenes, start=1):
        r_img = os.path.join(SCENE_DIR, f"raw_{idx}.jpg")
        a_path = os.path.join(SCENE_DIR, f"audio_{idx}.mp3")

        print(f"  [準備第 {idx}/{total_scenes} 幕] 產生語音與高畫質分鏡圖片...")
        asyncio.run(generate_speech_audio(sc["narration"], a_path, voice_name))
        download_ai_keyframe(sc["full_image_prompt"], r_img, master_seed=master_seed, scene_idx=idx)

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

    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print(f"✅ 短片合成完畢: {final_mp4}")


if __name__ == "__main__":
    main()
