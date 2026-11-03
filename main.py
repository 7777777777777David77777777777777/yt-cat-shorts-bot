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

# 8 大高流量視覺畫風池（每次執行自動隨機抽一種，整支影片 4 幕保持統一畫風，但每支新片風格都不同！）
VISUAL_STYLES = [
    {
        "name": "吉卜力手繪動畫風 (Studio Ghibli Anime)",
        "prompt_prefix": "Studio Ghibli hand-drawn anime style by Hayao Miyazaki, lush painted backgrounds, warm nostalgic sunlight, expressive charming details, vertical 9:16 aspect ratio, masterpiece, no text"
    },
    {
        "name": "8K 超寫實國家地理攝影風 (8K National Geographic Photorealism)",
        "prompt_prefix": "8K ultra-photorealistic National Geographic wildlife photography, shot on 85mm f/1.4 lens, cinematic natural golden hour lighting, razor-sharp fur and eye reflections, shallow depth of field, vertical 9:16, no text"
    },
    {
        "name": "定格黏土動畫風 (Stop-Motion Claymation)",
        "prompt_prefix": "Charming stop-motion plasticine claymation style like Aardman Studio, handcrafted tactile clay textures, miniature studio warm lighting, tilt-shift depth of field, vertical 9:16, no text"
    },
    {
        "name": "羊毛氈與微縮模型風 (Needle-Felted Wool Miniature)",
        "prompt_prefix": "Ultra-cozy needle-felted wool craft style inside a miniature wooden diorama, soft fuzzy felt fibers, warm fairy lights bokeh in background, macro photography, vertical 9:16, no text"
    },
    {
        "name": "溫暖童話水彩繪本風 (Whimsical Watercolor Storybook)",
        "prompt_prefix": "Award-winning children's storybook watercolor and pastel illustration, soft dreamy paper texture, gentle warm brush strokes, magical heartwarming atmosphere, vertical 9:16, no text"
    },
    {
        "name": "賽博龐克奇幻霓虹萌寵風 (Cozy Cyberpunk Neon)",
        "prompt_prefix": "Cozy futuristic cyberpunk street at night, glowing warm neon lanterns reflecting in puddles, cinematic Unreal Engine 5 render, magical bioluminescent accents, vertical 9:16, no text"
    },
    {
        "name": "樂高積木微縮世界風 (Macro LEGO Brick World)",
        "prompt_prefix": "Macro photography of a detailed LEGO brick miniature world, glossy plastic bricks, cinematic studio lighting, shallow depth of field, playful and creative, vertical 9:16, no text"
    },
    {
        "name": "3D 夢工廠皮克斯電影風 (3D Cinema Animation)",
        "prompt_prefix": "3D Pixar and DreamWorks feature film animation style, expressive eyes, subsurface scattering, rich cinematic lighting, vertical 9:16, no text"
    }
]

# 10 大多元療癒與奇幻主角池（不再只有固定貓咪，涵蓋水豚、海獺、小紅貓熊、柯基、企鵝、奇幻生物與貓狗互動）
SUBJECT_THEMES = [
    {
        "subject": "a chill Capybara running a cozy forest hot spring inn with yuzu fruits",
        "tag_group": ["capybara", "cuteanimals", "wholesome", "relaxing", "shorts"]
    },
    {
        "subject": "a clumsy baby Red Panda discovering a glowing magical bamboo lantern in the misty mountains",
        "tag_group": ["redpanda", "cuteanimals", "wildlife", "magical", "shorts"]
    },
    {
        "subject": "two fluffy baby Sea Otters holding paws while floating in a crystal-clear sunset bay",
        "tag_group": ["seaotter", "babyanimals", "oceans", "wholesome", "shorts"]
    },
    {
        "subject": "a chubby Corgi barista serving tiny acorn lattes to woodland squirrels from a vintage food truck",
        "tag_group": ["corgi", "puppy", "doglover", "cozyvibes", "shorts"]
    },
    {
        "subject": "a tiny fluffy Emperor Penguin chick seeing the glowing green Northern Lights for the first time",
        "tag_group": ["penguin", "antarctica", "cuteanimals", "aurora", "shorts"]
    },
    {
        "subject": "a miniature Hedgehog postman wearing a tiny satchel delivering love letters across a mushroom village",
        "tag_group": ["hedgehog", "miniature", "fairycore", "cute", "shorts"]
    },
    {
        "subject": "a Golden Retriever puppy and a tiny yellow duckling sharing a leaf umbrella during a summer sunshower",
        "tag_group": ["goldenretriever", "duckling", "animalfriendship", "wholesome", "shorts"]
    },
    {
        "subject": "a curious stray kitten and a wise baby Barn Owl guarding an ancient floating library",
        "tag_group": ["kitten", "owl", "fantasyart", "cutepets", "shorts"]
    },
    {
        "subject": "a brave Shiba Inu aviator flying a tiny wooden biplane through cotton-candy sunset clouds",
        "tag_group": ["shibainu", "dogvideos", "adventure", "cute", "shorts"]
    },
    {
        "subject": "a tiny baby Sea Turtle swimming alongside friendly glowing bioluminescent jellyfish in a starry ocean",
        "tag_group": ["seaturtle", "oceanlife", "aesthetic", "nature", "shorts"]
    }
]

# 多元微軟高擬真神經網路配音池（依故事隨機搭配不同說書人聲線）
VOICE_POOL = [
    "en-US-AnaNeural",          # 活潑童話感女聲
    "en-US-AriaNeural",         # 溫暖自然故事女聲
    "en-GB-SoniaNeural",        # 優雅英式繪本女聲
    "en-US-BrianNeural"         # 溫柔磁性說書男聲
]


def get_next_story():
    """
    每次執行自動隨機抽取「視覺畫風」+「主角題材」，
    並呼叫免金鑰 AI 接口 (https://text.pollinations.ai/openai，或自訂 OPENAI_API_KEY)
    動態生成全新的 4 幕劇本與對應風格的分鏡圖提示詞！
    """
    chosen_style = random.choice(VISUAL_STYLES)
    chosen_topic = random.choice(SUBJECT_THEMES)
    chosen_voice = random.choice(VOICE_POOL)

    print(f"🎨 本次隨機選中畫風: {chosen_style['name']}")
    print(f"🐾 本次隨機選中題材: {chosen_topic['subject']}")
    print(f"🎙️ 本次搭配配音聲線: {chosen_voice}")

    prompt = (
        f"Create a heartwarming, high-retention 4-scene YouTube Short script about: {chosen_topic['subject']}. "
        f"The visual art style for ALL 4 scenes MUST strictly follow: '{chosen_style['prompt_prefix']}'. "
        "Suitable for a general family & animal-lover audience (wholesome, emotional, engaging). "
        "Return strictly valid JSON (no markdown fences) with keys: "
        "id (string), theme (string), hook (string), title (catchy YouTube Short title under 85 chars with emojis and #shorts), "
        "description (string with hashtags), tags (list of 6 strings), and scenes (list of exactly 4 objects, "
        "each with 'narration' (15-22 words of spoken English storytelling) and "
        "'image_prompt' (must start with the exact visual style prefix and describe the scene vividly in vertical 9:16 with no text))."
    )

    # 1. 優先檢查使用者是否有設定自訂的 OPENAI_API_KEY / GROQ_API_KEY
    custom_key = os.environ.get("AI_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    api_url = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1/chat/completions").strip()
    api_model = os.environ.get("AI_MODEL", "gpt-4o-mini").strip()

    if custom_key:
        try:
            resp = requests.post(
                api_url,
                headers={"Authorization": f"Bearer {custom_key}", "Content-Type": "application/json"},
                json={
                    "model": api_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"}
                },
                timeout=40
            )
            if resp.status_code == 200:
                story = json.loads(resp.json()["choices"][0]["message"]["content"])
                story["voice"] = chosen_voice
                print(f"[自訂 AI 模型劇本生成成功] 標題: {story.get('title')}")
                return story
        except Exception as e:
            print(f"[提示] 自訂 API 呼叫略過 ({e})，切換至免金鑰 AI 接口。")

    # 2. 免金鑰 Pollinations OpenAI 接口 (預設完全免費、免填 Key、不使用 gemini-2.5-flash)
    try:
        resp = requests.post(
            "https://text.pollinations.ai/openai",
            json={
                "model": "openai",
                "seed": random.randint(1, 999999),
                "messages": [
                    {"role": "system", "content": "You are a viral YouTube Shorts creative director. Output raw valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            },
            timeout=40
        )
        if resp.status_code == 200:
            raw_text = resp.json()["choices"][0]["message"]["content"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").removeprefix("json").strip()
            story = json.loads(raw_text)
            story["voice"] = chosen_voice
            # 確保每一幕都帶上隨機抽中的視覺風格前綴
            for sc in story.get("scenes", []):
                if chosen_style["prompt_prefix"][:25].lower() not in sc.get("image_prompt", "").lower():
                    sc["image_prompt"] = f"{chosen_style['prompt_prefix']}, {sc.get('image_prompt', '')}"
            print(f"[免金鑰 AI 動態劇本生成成功] 標題: {story.get('title')}")
            return story
    except Exception as e:
        print(f"[提示] 雲端即時編劇忙碌 ({e})，啟動動態風格模板合成。")

    # 3. 動態風格保底合成器（即使外部文字 API 瞬斷，依然能用本次抽中的畫風與主角生成全新 4 幕劇本）
    sp = chosen_style["prompt_prefix"]
    subj = chosen_topic["subject"]
    return {
        "id": f"AUTO_{int(time.time())}",
        "theme": f"{chosen_style['name']} - {subj}",
        "voice": chosen_voice,
        "title": f"Wait Until the End! Wholesome {chosen_topic['tag_group'][0].capitalize()} Story ✨🐾 #shorts #cute",
        "description": f"Experience this heartwarming story in {chosen_style['name']}! 🐾✨\n\n#shorts #wholesome #cuteanimals #animation #storytime",
        "tags": chosen_topic["tag_group"],
        "scenes": [
            {
                "narration": f"Nobody expected what happened when we discovered {subj} early this morning.",
                "image_prompt": f"{sp}, wide establishing shot of {subj}, magical morning atmosphere, expressive emotion"
            },
            {
                "narration": "At first, everyone watched quietly from a distance, amazed by every tiny gentle movement.",
                "image_prompt": f"{sp}, close-up portrait of {subj}, sparkling eyes, heartwarming and curious expression"
            },
            {
                "narration": "Then came the sweetest moment of pure joy that melted every single heart watching.",
                "image_prompt": f"{sp}, dynamic joyful action shot of {subj}, surrounded by warm golden light and gentle sparkles"
            },
            {
                "narration": "Moments like this remind us how magical the world can be! Subscribe if this made you smile today!",
                "image_prompt": f"{sp}, peaceful cozy finale of {subj} resting happily under warm glowing light"
            }
        ]
    }


async def generate_tts(text: str, audio_path: str, voice_name: str):
    """使用免費 Edge-TTS 產出高擬真語音"""
    communicate = edge_tts.Communicate(text, voice_name, rate="+3%")
    await communicate.save(audio_path)


def generate_ai_image(prompt: str, img_path: str, seed: int):
    """
    使用免金鑰 Pollinations Flux 模型生成 1080x1920 (9:16) 對應隨機畫風的高畫質插圖。
    """
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&seed={seed}&nologo=true&model=flux"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=50)
            if resp.status_code == 200 and len(resp.content) > 10000:
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                return
        except Exception as e:
            print(f"  [算圖重試 {attempt+1}/3] {e}")
            time.sleep(3)

    img = Image.new("RGB", (1080, 1920), color=(35, 40, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, 1020, 1860], outline=(255, 200, 120), width=10)
    img.save(img_path)


def overlay_subtitle_on_image(img_path: str, subtitle_text: str):
    """在分鏡圖下方繪製高對比圓角字幕卡"""
    img = Image.open(img_path).convert("RGBA").resize((1080, 1920))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

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
        fill=(18, 18, 24, 195),
        outline=(255, 215, 100, 230),
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
    """使用 FFmpeg 將單張分鏡圖加上平滑運鏡與配音合成為 MP4 片段"""
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
    voice_name = story.get("voice", "en-US-AnaNeural")
    clip_files = []

    for idx, scene in enumerate(story["scenes"], start=1):
        print(f"正在處理第 {idx}/{len(story['scenes'])} 幕...")
        img_path = os.path.join(SCENE_DIR, f"scene_{idx}.jpg")
        audio_path = os.path.join(SCENE_DIR, f"scene_{idx}.mp3")
        clip_path = os.path.join(SCENE_DIR, f"clip_{idx}.mp4")

        asyncio.run(generate_tts(scene["narration"], audio_path, voice_name))
        generate_ai_image(scene["image_prompt"], img_path, seed=random.randint(1000, 999999))
        overlay_subtitle_on_image(img_path, scene["narration"])
        render_scene_clip(img_path, audio_path, clip_path)
        clip_files.append(clip_path)

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

    print(f"✅ 多元風格 YouTube Short 影片合成完畢: {final_mp4}")


if __name__ == "__main__":
    main()
