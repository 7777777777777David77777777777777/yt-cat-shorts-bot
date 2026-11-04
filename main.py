import os
import re
import sys
import csv
import io
import math
import json
import time
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
    """移除括號內註記與特殊符號，保留乾淨英文描述"""
    text = re.sub(r"\([^)]*\)", "", str(text))
    text = re.sub(r"[^a-zA-Z0-9, -]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_base_title(raw_title: str) -> str:
    """移除原標題尾端已有的 Wait For It / Emoji / Hashtags，避免標題尾綴重複出現兩次"""
    t = str(raw_title).split("#")[0].strip()
    t = re.sub(r"(\.\.\.)?\s*Wait For It!?.*$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"[^\w\s,'?!-]", "", t).strip()
    return t if t else "Little Girl Brings Stray Kitten Home to Her 90-Pound Husky"


def parse_episode_from_row(row_dict: dict) -> dict:
    ep_id = str(row_dict.get("id", "EP01")).strip()
    sent_count = int(str(row_dict.get("sent_count", "0")).split("/")[0].strip() or 0)
    art_dna = clean_prompt_text(row_dict.get("art_dna", "3D Pixar DreamWorks feature animation style, warm golden sunlight"))
    char1_dna = clean_prompt_text(row_dict.get("char1_dna", "cute 6-year-old little girl in yellow raincoat holding a tiny fluffy ginger kitten"))
    char2_dna = clean_prompt_text(row_dict.get("char2_dna", "giant gentle silver-and-white Siberian Husky"))

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
        # 100% 根據該幕具體動作 (clean_act) 與角色設定 (小女孩 / 貓咪 / 狗狗) 組合算圖指令，確保畫面與台詞完全相符！
        full_prompt = (
            f"{art_dna}, {clean_act}, featuring {char1_dna} and {char2_dna}, "
            "heartwarming expressive faces, vertical 9:16 aspect ratio, clean composition, no text, no watermark"
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
        "character_dna": f"{char1_dna} & {char2_dna}",
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
    webhook_url = os.environ.get("SHEET_WEBHOOK_URL", "").strip()

    if webhook_url:
        try:
            resp = requests.get(f"{webhook_url}?action=get_next", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and data.get("episode"):
                    ep = parse_episode_from_row(data["episode"])
                    print(f"✅ [Google Sheet 方案B 連線成功] 讀取集數: {ep['id']} (今日第 {ep['sent_count'] + 1}/6 次發送)")
                    return ep
        except Exception as e:
            print(f"  [Webhook 讀取提示] {e}，切換為 CSV 直連讀取...")

    try:
        resp = requests.get(SHEET_CSV_URL, timeout=15)
        if resp.status_code == 200 and "EP0" in resp.text:
            reader = csv.reader(io.StringIO(resp.text))
            for r_idx, row in enumerate(reader, start=1):
                if not row:
                    continue
                first_col = str(row[0]).strip()
                if first_col.startswith("EP") and len(row) >= 15:
                    status_str = str(row[1]).strip()
                    sent_str = str(row[2]).split("/")[0].strip()
                    sent_cnt = int(sent_str) if sent_str.isdigit() else 0
                    if "已完成" not in status_str and "Completed" not in status_str and sent_cnt < 6:
                        row_dict = {
                            "row_index": r_idx,
                            "id": first_col,
                            "status": status_str,
                            "sent_count": sent_cnt,
                            "art_dna": row[3],
                            "char1_dna": row[4],
                            "char2_dna": row[5],
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
                        print(f"✅ [Google Sheet CSV 讀取成功] 集數: {ep['id']} (第 {ep['sent_count'] + 1}/6 次發送)")
                        return ep
    except Exception as e:
        print(f"  [Sheet CSV 讀取提示] ({e})")

    default_row = {
        "row_index": 8,
        "id": "EP01",
        "sent_count": 0,
        "art_dna": "3D Pixar DreamWorks feature animation style, warm golden sunlight, expressive eyes, ultra-detailed soft fur",
        "char1_dna": "a cute 6-year-old little girl named Mia with warm brown pigtails wearing a yellow raincoat, holding a tiny fluffy ginger kitten",
        "char2_dna": "a giant gentle silver-and-white Siberian Husky dog with kind brown eyes",
        "s1_narration": "Six-year-old Mia found a tiny shivering ginger kitten in the rain and brought him home to meet her giant Husky, Titan.",
        "s1_action": "cute 6-year-old girl in yellow raincoat kneeling in cozy hallway, holding a tiny wet ginger kitten in front of a giant gentle Siberian Husky",
        "s2_narration": "Everyone worried the ninety-pound dog would scare the kitten, but Titan gently laid down and offered his warm furry paw.",
        "s2_action": "giant Siberian Husky lying flat on living room rug as the tiny ginger kitten climbs onto his huge white paw while the little girl smiles",
        "s3_narration": "Within minutes, little Mochi was fast asleep on Titan's chest while Mia covered them both with her favorite soft blanket.",
        "s3_action": "cute little girl gently placing a knitted blanket over the giant Husky and the tiny ginger kitten sleeping together by a warm fireplace",
        "s4_narration": "Now the three best friends wear matching blue scarves everywhere they go! Subscribe if Mia and Mochi made you smile!",
        "s4_action": "happy little girl, giant Husky, and tiny ginger kitten sitting side by side on a sunny garden lawn wearing matching blue scarves, looking at camera",
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
    """自動切除圖片最底部 5% 與左右 2% 邊緣再縮放回 1080x1920，100% 消除右下角浮水印"""
    with Image.open(img_path) as im:
        im_rgb = im.convert("RGB")
        w, h = im_rgb.size
        cropped = im_rgb.crop((int(w * 0.02), int(h * 0.01), int(w * 0.98), int(h * 0.95)))
        cropped.resize((1080, 1920), Image.Resampling.LANCZOS).save(img_path, quality=95)


def download_ai_keyframe(prompt: str, img_path: str, master_seed: int, scene_idx: int, prev_imgs: list):
    """
    【高畫質 Flux 專屬出圖引擎 — 100% 忠於劇本分鏡描述】
    全程鎖定 Pollinations `flux` 模型（理解複雜多角色互動如「小女孩 + 小橘貓 + 哈士奇」能力最強），
    並自動切除底部邊緣浮水印，移除與劇本不符的隨機真實貓照片備援！
    """
    if os.path.exists(img_path) and is_valid_colorful_image(img_path):
        return

    encoded = urllib.parse.quote(prompt[:260])

    for attempt in range(5):
        seed = master_seed + (scene_idx * 17) + (attempt * 53)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=768&height=1344&seed={seed}&nologo=true&enhance=false&model=flux"
        )
        headers = {"User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/{122 + attempt}.0"}
        try:
            if attempt > 0 or scene_idx > 1:
                time.sleep(5.0)
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 200 and len(resp.content) > 18000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                if is_valid_colorful_image(img_path):
                    crop_bottom_watermark_and_save(img_path)
                    print(f"    ✅ 第 {scene_idx} 幕 Flux 高畫質分鏡產出成功 (已對齊劇本並裁除邊角浮水印)")
                    return
        except Exception as e:
            print(f"    [Flux 算圖重試 {attempt+1}/5] {e}")

    for p_img in reversed(prev_imgs):
        if os.path.exists(p_img) and is_valid_colorful_image(p_img):
            with Image.open(p_img) as im:
                im_rgb = im.convert("RGB").resize((1080, 1920), Image.Resampling.LANCZOS)
                crop_box = (80, 120, 1000, 1760) if scene_idx % 2 == 0 else (45, 70, 1035, 1820)
                reframed = im_rgb.crop(crop_box).resize((1080, 1920), Image.Resampling.LANCZOS)
                reframed.save(img_path, quality=95)
            print(f"    ✅ 第 {scene_idx} 幕採用同集連貫角色特寫分鏡")
            return

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

    print(f"🎬 啟動 Google Sheet 連動產線 | 集數: {story['id']} (第 {story['sent_count'] + 1}/6 次發送)")
    print(f"🎨 畫風 DNA: {story.get('selected_visual_style')}")
    print(f"🐾 角色鎖定 (含小女孩與萌寵): {story.get('character_dna')}")
    print(f"🎙️ 本輪輪替配音: {voice_name}")

    raw_imgs = []
    audio_paths = []

    for idx, sc in enumerate(scenes, start=1):
        r_img = os.path.join(SCENE_DIR, f"raw_{idx}.jpg")
        a_path = os.path.join(SCENE_DIR, f"audio_{idx}.mp3")

        print(f"  [準備第 {idx}/{total_scenes} 幕] 產生語音與高畫質 Flux 分鏡圖片...")
        asyncio.run(generate_speech_audio(sc["narration"], a_path, voice_name))
        download_ai_keyframe(sc["full_image_prompt"], r_img, master_seed=master_seed, scene_idx=idx, prev_imgs=raw_imgs)

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
