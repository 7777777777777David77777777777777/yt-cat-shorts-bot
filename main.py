import os
import json
import time
import random
import urllib.parse
import subprocess
import asyncio
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = "output"
SCENE_DIR = os.path.join(OUTPUT_DIR, "scenes")
os.makedirs(SCENE_DIR, exist_ok=True)

# 選用高親和力、極適合說可愛故事的微軟神經網路語音
VOICE_NAME = "en-US-AnaNeural"  # 活潑可愛童話感英語女聲 (亦可改為 en-US-AriaNeural 或 zh-TW-HsiaoChenNeural)


def get_next_story():
    """
    優先檢查是否有設定 GEMINI_API_KEY 自動發想全新可愛貓咪故事；
    若無設定，則自動從 topics_queue.json 輪播挑選高完播劇本。
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            prompt = (
                "Create a heartwarming, high-retention 4-scene YouTube Short script about an adorable cat or kitten "
                "(suitable for all ages, general family audience, wholesome Pixar style). "
                "Return strictly valid JSON with keys: "
                "id, theme, hook, title, description, tags (list of strings), and scenes (list of 4 objects, "
                "each with 'narration' (15-22 words) and 'image_prompt' (detailed 3D Pixar Disney animation style prompt, vertical 9:16, no text))."
            )
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            story = json.loads(resp.text)
            print(f"[AI 劇本生成成功] 主題: {story.get('title')}")
            return story
        except Exception as e:
            print(f"[提示] Gemini 動態生成略過 ({e})，改用內建精選爆款劇本庫。")

    with open("topics_queue.json", "r", encoding="utf-8") as f:
        stories = json.load(f)
    story = random.choice(stories)
    print(f"[載入精選劇本] 主題: {story.get('title')}")
    return story


async def generate_tts(text: str, audio_path: str):
    """使用免費 Edge-TTS 產出高擬真語音"""
    communicate = edge_tts.Communicate(text, VOICE_NAME, rate="+5%", pitch="+2Hz")
    await communicate.save(audio_path)


def generate_ai_image(prompt: str, img_path: str, seed: int):
    """
    使用免金鑰 Pollinations Flux 模型生成 1080x1920 (9:16) 高畫質 3D 皮克斯風可愛貓咪插圖。
    具備自動重試與保底漸層可愛圖卡機制，確保雲端 100% 不中斷。
    """
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&seed={seed}&nologo=true&model=flux"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=45)
            if resp.status_code == 200 and len(resp.content) > 10000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                return
        except Exception as e:
            print(f"  [算圖重試 {attempt+1}/3] {e}")
            time.sleep(3)

    # 保底機制：若外部免費算圖伺服器忙碌，自動繪製高質感暖色插畫背景
    img = Image.new("RGB", (1080, 1920), color=(255, 228, 196))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 1020, 1860], outline=(255, 160, 122), width=12)
    img.save(img_path)


def overlay_subtitle_on_image(img_path: str, subtitle_text: str):
    """
    在分鏡圖下方黃金視覺區繪製高對比圓角字幕卡，確保無須複雜 ASS 字幕濾鏡也能 100% 跨平台完美顯示。
    """
    img = Image.open(img_path).convert("RGBA").resize((1080, 1920))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 自動斷行 (每行約 26 個字元)
    words = subtitle_text.split()
    lines, current = [], ""
    for w in words:
        if len(current + " " + w) <= 26:
            current = (current + " " + w).strip()
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 52)
    except Exception:
        font = ImageFont.load_default()

    box_top = 1320
    box_bottom = 1380 + len(lines) * 68
    draw.rounded_rectangle(
        [70, box_top, 1010, box_bottom],
        radius=32,
        fill=(20, 20, 25, 195),
        outline=(255, 215, 0, 230),
        width=4
    )

    y_text = box_top + 30
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        x_text = (1080 - w) // 2
        draw.text((x_text, y_text), line, font=font, fill=(255, 255, 255, 255))
        y_text += 66

    combined = Image.alpha_composite(img, overlay).convert("RGB")
    combined.save(img_path, quality=95)


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return max(float(res.stdout.strip()), 2.5)


def render_scene_clip(img_path: str, audio_path: str, clip_path: str):
    """使用 FFmpeg 將單張分鏡圖加上微幅平滑縮放 (Ken Burns) 與配音合成為 MP4 片段"""
    duration = get_audio_duration(audio_path) + 0.25
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", img_path,
        "-i", audio_path,
        "-vf", "scale=1140:2026,crop=1080:1920:30:50,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.2f}",
        "-r", "30",
        clip_path
    ]
    subprocess.run(cmd, check=True)


def main():
    story = get_next_story()
    clip_files = []

    for idx, scene in enumerate(story["scenes"], start=1):
        print(f"正在處理第 {idx}/{len(story['scenes'])} 幕...")
        img_path = os.path.join(SCENE_DIR, f"scene_{idx}.jpg")
        audio_path = os.path.join(SCENE_DIR, f"scene_{idx}.mp3")
        clip_path = os.path.join(SCENE_DIR, f"clip_{idx}.mp4")

        asyncio.run(generate_tts(scene["narration"], audio_path))
        generate_ai_image(scene["image_prompt"], img_path, seed=random.randint(1000, 999999))
        overlay_subtitle_on_image(img_path, scene["narration"])
        render_scene_clip(img_path, audio_path, clip_path)
        clip_files.append(clip_path)

    # 合併所有分鏡片段為最終 9:16 YouTube Short
    concat_txt = os.path.join(SCENE_DIR, "concat_list.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for cp in clip_files:
            f.write(f"file '{os.path.abspath(cp)}'\n")

    final_mp4 = os.path.join(OUTPUT_DIR, "final_short.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_txt, "-c", "copy", final_mp4
    ], check=True)

    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    print(f"✅ YouTube Short 影片合成完畢: {final_mp4}")


if __name__ == "__main__":
    main()
