"""Render a handwritten Markdown story without the Sheet or YouTube."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import main as factory
from preview_ep01 import make_keyframe, safe_error

ROOT = Path(__file__).resolve().parent
STORIES = ROOT / "stories"
STYLES = {style["id"]: style for style in factory.VISUAL_STYLE_ROTATION}
REFERENCE_INSTRUCTIONS = (
    "Fixed visual reference: The attached image is scene 1 and defines the exact wardrobe, "
    "character identity, studio and lighting for this sequence. Use the same visible person's "
    "face and hairstyle and the exact same garments, not merely similar colors or garment categories. "
    "Preserve knit pattern and texture, neckline, cuffs, hem, garment fit and tuck; "
    "trouser waistband, fastenings, belt loops, pockets, seams, leg width and length; "
    "sock height, ribbing and color; and shoe shape, laces and soles. "
    "Do not invent a new knit pattern, waistband design, sock length or substitute footwear. "
    "Only change the pose, view and framing to follow the scene action. "
    "Show only the body parts needed by the shot; a close-up need not include the entire model."
)


def parse_markdown(text):
    """Parse explicit headings, never ask a language model to interpret the story."""
    aliases = {"標題": "title", "title": "title", "氛圍": "genre", "genre": "genre",
               "標籤": "tags", "tags": "tags", "角色": "characters", "characters": "characters"}
    fields, key, scene, episode_id = {}, None, None, None
    seen_scenes = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        heading = re.match(r"^(#+)\s+(.+?)\s*$", line)
        if heading:
            level, label = len(heading[1]), heading[2].strip()
            if level == 1:
                if episode_id is not None or fields:
                    raise ValueError(f"第 {line_number} 行：只能在開頭指定一次集數 ID")
                episode_id, key = label, None
                continue
            if episode_id is None:
                raise ValueError(f"第 {line_number} 行：請先填 # EP01 等集數 ID")
            match = re.fullmatch(r"(?:第\s*([1-4])\s*幕|Scene\s+([1-4]))", label, re.IGNORECASE)
            if level == 2 and match:
                scene = int(match[1] or match[2])
                if scene in seen_scenes:
                    raise ValueError(f"第 {line_number} 行：第 {scene} 幕重複")
                seen_scenes.add(scene)
                key = None
                continue
            if level == 2 and label.lower() in aliases:
                key, scene = aliases[label.lower()], None
            elif level == 3 and scene is not None and label.lower() in ("旁白", "narration", "畫面", "action"):
                field = "narration" if label.lower() in ("旁白", "narration") else "action"
                key = f"scene{scene}_{field}"
            else:
                raise ValueError(f"第 {line_number} 行：不支援標題 {label!r}，請沿用 stories/EP01.md 格式")
            if key in fields:
                raise ValueError(f"第 {line_number} 行：欄位 {label!r} 重複")
            fields[key] = []
        elif key is not None:
            fields[key].append(line)
        elif line.strip():
            raise ValueError(f"第 {line_number} 行：內容需放在對應的標題下")

    value = lambda name: "\n".join(fields.get(name, [])).strip()
    characters = []
    for line in value("characters").splitlines():
        if not line.strip():
            continue
        if not re.match(r"^\s*[-*]\s+", line):
            raise ValueError("角色請每行一位，以 - 開頭")
        characters.append(re.sub(r"^\s*[-*]\s+", "", line).strip())
    return {"id": episode_id, "title": value("title"), "genre": value("genre"),
            "characters": characters,
            "tags": [tag.strip() for tag in value("tags").split(",") if tag.strip()],
            "scenes": [{"narration": value(f"scene{i}_narration"), "action": value(f"scene{i}_action")}
                       for i in range(1, 5)]}


def validate_script(data):
    if not isinstance(data, dict):
        raise ValueError("劇本解析結果必須是物件")
    allowed = {"id", "title", "genre", "characters", "tags", "scenes", "description"}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"不支援的劇本欄位：{', '.join(sorted(unknown))}")
    for field in ("id", "title", "genre"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"劇本 {field} 不能空白，且必須是文字")
    if not re.fullmatch(r"EP\d+", data["id"], re.IGNORECASE):
        raise ValueError("集數 ID 請使用 EP 加數字，例如 EP01")
    characters = data.get("characters")
    if not isinstance(characters, list) or not 1 <= len(characters) <= 3:
        raise ValueError("目前測試格式支援一至三位角色")
    if any(not isinstance(c, str) or not c.strip() for c in characters):
        raise ValueError("每位角色設定都必須是非空白文字")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 4:
        raise ValueError("目前測試格式需剛好四幕")
    for number, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict) or set(scene) != {"narration", "action"}:
            raise ValueError(f"第 {number} 幕需包含 narration 與 action 兩個欄位")
        for field in ("narration", "action"):
            if not isinstance(scene[field], str) or not scene[field].strip():
                raise ValueError(f"第 {number} 幕 {field} 不能空白")
    if not isinstance(data.get("tags", []), list) or any(not isinstance(t, str) for t in data.get("tags", [])):
        raise ValueError("tags 請使用文字陣列")
    if "description" in data and not isinstance(data["description"], str):
        raise ValueError("description 必須是文字")
    return data


def load_script(script_path, style="photorealistic"):
    path = (ROOT / script_path).resolve()
    if not path.is_relative_to(STORIES.resolve()) or path.suffix.lower() != ".md":
        raise ValueError("劇本必須是 stories/ 資料夾內的 Markdown（.md）檔案")
    source_bytes = path.read_bytes()
    text = source_bytes.decode("utf-8-sig")
    data = validate_script(parse_markdown(text))
    if style not in STYLES:
        raise ValueError("不支援的畫風")
    selected = STYLES[style]
    characters = [factory.clean_prompt_text(c) for c in data["characters"]]
    cameras = ["smooth_push_in", "smooth_pan_right", "smooth_pull_out", "smooth_push_in"]
    scenes = [{"narration": s["narration"], "scene_action": s["action"], "camera_style": cameras[i],
               "full_image_prompt": f"Story genre and mood: {data['genre']}\n" + factory.build_image_prompt(
                   selected["prompt"], characters, factory.clean_prompt_text(s["action"]))}
              for i, s in enumerate(data["scenes"])]
    return {"id": data["id"], "title": data["title"], "story_genre": data["genre"],
            "description": data.get("description", ""), "tags": data.get("tags", []),
            "characters": data["characters"], "scenes": scenes,
            "visual_style_id": style, "visual_style_name": selected["name"],
            "voice_name": "en-US-AriaNeural", "source_path": str(path.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "preview_only": True, "sheet_read": False, "sheet_writeback": False,
            "youtube_upload": False, "script_rewritten": False}


def render_script(story, output, client, image_model):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("輸出資料夾已有檔案；請先保存前次結果，改用空資料夾")
    scenes_dir = output / "scenes"
    scenes_dir.mkdir()
    records = []
    metadata = dict(story, status="running", image_model=image_model, video_generation_requests=0,
                    reference_strategy="fixed_first_scene")
    save = lambda: (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    images, audios = [], []
    try:
        for number, scene in enumerate(story["scenes"], 1):
            print(f"[{number}/4] " + ("建立全身服裝參考圖" if number == 1 else "以第 1 幕圖片作固定參考"), flush=True)
            image, audio = scenes_dir / f"scene_{number}.png", scenes_dir / f"scene_{number}.mp3"
            record = factory.start_image_request(records, "google", image_model, number)
            reference = scenes_dir / "scene_1.png" if number > 1 else None
            prompt = scene["full_image_prompt"]
            if reference is not None:
                prompt += "\n" + REFERENCE_INSTRUCTIONS
                record["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
            record["reference_image"] = str(reference.relative_to(output)) if reference is not None else None
            prompt_path = scenes_dir / f"scene_{number}.prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            record["prompt_file"] = str(prompt_path.relative_to(output))
            make_keyframe(client, image_model, prompt, image, record, image_size=(1080, 1920), reference_image=reference)
            asyncio.run(factory.generate_speech_audio(scene["narration"], str(audio), story["voice_name"]))
            images.append(str(image))
            audios.append(str(audio))
        final = output / "preview.mp4"
        old_scene_dir = factory.SCENE_DIR
        try:
            factory.SCENE_DIR = str(scenes_dir)
            factory.render_continuous_smooth_short(images, audios, story["scenes"], str(final))
        finally:
            factory.SCENE_DIR = old_scene_dir
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                               capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout)["streams"]
        if not any(s["codec_type"] == "video" and s.get("width") == 1080 and s.get("height") == 1920 for s in streams):
            raise RuntimeError("成片未包含 1080×1920 影片軌")
        if not any(s["codec_type"] == "audio" for s in streams):
            raise RuntimeError("成片缺少配音")
        metadata.update(status="completed", final_mp4=final.name)
        return final
    except Exception as exc:
        metadata.update(status="failed", error=safe_error(exc))
        raise
    finally:
        metadata["image_usage"] = factory.summarize_image_usage(records)
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", default="stories/EP01.md")
    parser.add_argument("--style", choices=STYLES, default="photorealistic")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        story = load_script(args.script, args.style)
        print("劇本來源：" + json.dumps(story["source_path"], ensure_ascii=False), flush=True)
        print(f"劇本驗證成功：{story['id']}，{len(story['characters'])} 角色／4 幕，畫風 {story['visual_style_name']}", flush=True)
        if args.validate_only:
            return 0
        from google import genai
        from google.genai import types
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ValueError("請先設定 repository Actions secret GEMINI_API_KEY，用於產圖")
        with genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            model = os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or "gemini-2.5-flash-image"
            final = render_script(story, ROOT / "output/script-preview", client, model)
        print(f"完成，請下載 MP4：{final}")
        return 0
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
