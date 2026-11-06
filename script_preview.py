"""Render a handwritten Markdown story without the Sheet or YouTube."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image

import main as factory
from preview_ep01 import make_keyframe, safe_error
from lookbook_render import make_original_bgm, render_lookbook

ROOT = Path(__file__).resolve().parent
STORIES = ROOT / "stories"
STYLES = {style["id"]: style for style in factory.VISUAL_STYLE_ROTATION}
REFERENCE_INSTRUCTIONS = (
    "Episode wardrobe reference: The LAST attached image is scene 1 and defines the exact wardrobe. "
    "Use the exact same garments, not merely similar colors or garment categories. "
    "When identity references are present, their portrait is authoritative for facial identity; "
    "do not replace its face with a different interpretation from scene 1. "
    "Preserve fabric texture and any existing pattern, neckline or collar, buttons, cuffs, "
    "garment fit and tuck; the bottom garment's waistband, fastenings, pockets, seams, silhouette "
    "and hemline; hosiery type, length, color and opacity; and shoe shape, closures, soles "
    "and heel height. Match only details actually visible in the reference. "
    "Do not invent garments, fabric patterns, closures, hosiery types or substitute footwear. "
    "Change pose, expression, view, framing, location and scene lighting as specified by the scene. "
    "The reference image's camera distance, pose and full-body composition are not binding. "
    "Show only the body parts needed by the shot; a close-up need not include the entire model."
)
IDENTITY_INSTRUCTIONS = (
    "Character identity references: The FIRST attached images are the character's portrait and/or "
    "full-body identity reference, in the listed order. The first portrait defines facial structure, "
    "eye shape, nose, lips, jaw width, hairline and hairstyle. The second identity image, when present, "
    "defines natural adult body proportions. Do not average the two faces or substitute another model. "
    "Preserve the compact natural build without slimming the body, lengthening the legs or narrowing the jaw. "
    "Their reference clothes, white socks, studio background "
    "and neutral expression are not this episode's wardrobe or location. Use the episode wardrobe "
    "and scene description instead. Facial expression, gaze and posture follow each scene; "
    "preserve identity without freezing the reference expression."
)


def parse_markdown(text):
    """Parse explicit headings, never ask a language model to interpret the story."""
    aliases = {"標題": "title", "title": "title", "氛圍": "genre", "genre": "genre",
               "標籤": "tags", "tags": "tags", "角色": "characters", "characters": "characters",
               "主角參考": "character_references", "character references": "character_references"}
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
            elif level == 3 and scene is not None and label.lower() in ("旁白", "narration", "畫面", "action", "表情", "expression"):
                field = {"旁白": "narration", "narration": "narration", "畫面": "action", "action": "action",
                         "表情": "expression", "expression": "expression"}[label.lower()]
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
    result = {"id": episode_id, "title": value("title"), "genre": value("genre"),
            "characters": characters,
            "tags": [tag.strip() for tag in value("tags").split(",") if tag.strip()],
            "scenes": [{"narration": value(f"scene{i}_narration"), "action": value(f"scene{i}_action")}
                       for i in range(1, 5)]}
    if "character_references" in fields:
        result["character_references"] = [re.sub(r"^\s*[-*]\s+", "", line).strip()
                                          for line in value("character_references").splitlines() if line.strip()]
    for i, scene in enumerate(result["scenes"], 1):
        if f"scene{i}_expression" in fields:
            scene["expression"] = value(f"scene{i}_expression")
    return result


def validate_script(data):
    if not isinstance(data, dict):
        raise ValueError("劇本解析結果必須是物件")
    allowed = {"id", "title", "genre", "characters", "tags", "scenes", "description", "character_references"}
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
        if not isinstance(scene, dict) or "action" not in scene or set(scene) - {"narration", "action", "expression"}:
            raise ValueError(f"第 {number} 幕需包含 action 欄位")
        if not isinstance(scene["action"], str) or not scene["action"].strip():
            raise ValueError(f"第 {number} 幕 action 不能空白")
        if not isinstance(scene.get("narration", ""), str):
            raise ValueError(f"第 {number} 幕旁白欄位必須是文字；寫真模式不會使用旁白")
        if not isinstance(scene.get("expression", ""), str):
            raise ValueError(f"第 {number} 幕表情欄位必須是文字")
    refs = data.get("character_references", [])
    if not isinstance(refs, list) or len(refs) > 2 or any(not isinstance(r, str) or not r.strip() for r in refs):
        raise ValueError("主角參考需為最多兩個圖片路徑")
    if not isinstance(data.get("tags", []), list) or any(not isinstance(t, str) for t in data.get("tags", [])):
        raise ValueError("tags 請使用文字陣列")
    if "description" in data and not isinstance(data["description"], str):
        raise ValueError("description 必須是文字")
    return data


def resolve_character_references(paths):
    references = []
    for value in paths:
        path = (ROOT / value).resolve()
        if not path.is_relative_to((ROOT / "assets/characters").resolve()) or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("主角參考圖必須在 assets/characters/ 內，使用 PNG、JPG 或 WebP")
        with Image.open(path) as image:
            image.verify()
        references.append(path)
    return references


def load_script(script_path, style="photorealistic"):
    path = (ROOT / script_path).resolve()
    if not path.is_relative_to(STORIES.resolve()) or path.suffix.lower() != ".md":
        raise ValueError("劇本必須是 stories/ 資料夾內的 Markdown（.md）檔案")
    source_bytes = path.read_bytes()
    text = source_bytes.decode("utf-8-sig")
    data = validate_script(parse_markdown(text))
    identity_paths = resolve_character_references(data.get("character_references", []))
    if style not in STYLES:
        raise ValueError("不支援的畫風")
    selected = STYLES[style]
    characters = [factory.clean_prompt_text(c) for c in data["characters"]]
    references = "\n".join(f"{i}. {c}" for i, c in enumerate(characters, 1))
    scenes = [{"narration": s.get("narration", ""), "scene_action": s["action"], "expression": s.get("expression", ""),
               "full_image_prompt": (
                   f"Scene action: {factory.clean_prompt_text(s['action'])}\n"
                   f"Expression and gaze: {s.get('expression', '') or 'Follow the scene naturally; if the face is outside the frame, do not add a face.'}\n"
                   f"Editorial mood: {data['genre']}\nVisual style: {selected['prompt']}\n"
                   f"Character references:\n{references}\n"
                   "One cohesive full-bleed vertical 9:16 fashion photograph, background extending to all four edges. "
                   "Follow the requested pose and framing; preserve the character and wardrobe. "
                   "Natural anatomy and hands, clear clothing details and facial detail where visible, generous framing for a gentle zoom. "
                   "No lettering, captions, logos, watermark, border, inset or collage. "
                   "Use the whole composition naturally; do not reserve an empty subtitle strip. "
                   "SHOT PRIORITY: Follow this scene's requested camera crop and subject placement, "
                   "independently of the attached images' compositions. For a garment-detail shot, "
                   "show only the specified garment region; keep the head, upper body and other "
                   "out-of-frame parts excluded. Do not expand a detail shot into a full-body portrait.")}
              for s in data["scenes"]]
    return {"id": data["id"], "title": data["title"], "story_genre": data["genre"],
            "description": data.get("description", ""), "tags": data.get("tags", []),
            "characters": data["characters"], "scenes": scenes,
            "character_reference_images": [str(path.relative_to(ROOT)) for path in identity_paths],
            "visual_style_id": style, "visual_style_name": selected["name"],
            "source_path": str(path.relative_to(ROOT)), "narration_enabled": False, "subtitles_enabled": False,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "preview_only": True, "sheet_read": False, "sheet_writeback": False,
            "youtube_upload": False, "script_rewritten": False}


def resolve_bgm(bgm_path):
    if not bgm_path:
        return None
    path = (ROOT / bgm_path).resolve()
    if not path.is_relative_to((ROOT / "assets/bgm").resolve()) or path.suffix.lower() not in (".wav", ".mp3", ".m4a"):
        raise ValueError("自訂 BGM 請放在 assets/bgm/，使用 WAV、MP3 或 M4A")
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    if not any(s["codec_type"] == "audio" for s in json.loads(result.stdout)["streams"]):
        raise ValueError("BGM 檔案沒有音訊軌")
    return path


def render_script(story, output, client, image_model, scene_seconds=5, bgm_source=None):
    if not 0 < scene_seconds <= 30:
        raise ValueError("每幕秒數需介於 0～30 秒")
    identity_paths = resolve_character_references(story.get("character_reference_images", []))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("輸出資料夾已有檔案；請先保存前次結果，改用空資料夾")
    scenes_dir = output / "scenes"
    scenes_dir.mkdir()
    identities = []
    for i, path in enumerate(identity_paths, 1):
        destination = output / "references" / f"identity_{i}{path.suffix}"
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, destination)
        identities.append(destination)
    records = []
    metadata = dict(story, status="running", image_model=image_model, video_generation_requests=0,
                    reference_strategy="character_identity_and_fixed_first_scene" if identities else "fixed_first_scene", presentation="photo_lookbook",
                    narration_enabled=False, subtitles_enabled=False, scene_seconds=scene_seconds)
    save = lambda: (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    images = []
    try:
        for number, scene in enumerate(story["scenes"], 1):
            print(f"[{number}/4] " + ("依主角參考建立當集全身服裝圖" if identities and number == 1 else
                                    "建立全身服裝參考圖" if number == 1 else
                                    "以主角圖及第 1 幕圖片作固定參考" if identities else "以第 1 幕圖片作固定參考"), flush=True)
            image = scenes_dir / f"scene_{number}.png"
            record = factory.start_image_request(records, "google", image_model, number)
            reference = scenes_dir / "scene_1.png" if number > 1 else None
            reference_context = []
            references = identities + ([reference] if reference is not None else [])
            if identities:
                reference_context.append(IDENTITY_INSTRUCTIONS + "\nIdentity image order: " + ", ".join(
                    f"{i}: {path.name}" for i, path in enumerate(identity_paths, 1)))
            if reference is not None:
                reference_context.append(REFERENCE_INSTRUCTIONS)
                record["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
            record["reference_image"] = str(reference.relative_to(output)) if reference is not None else None
            record["reference_images"] = [{"path": str(path.relative_to(output)),
                                            "role": "episode_wardrobe" if path == reference else "character_identity",
                                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                           for path in references]
            # Put the current shot last so reference instructions do not override its crop or expression.
            prompt = "\n\n".join(reference_context + [scene["full_image_prompt"]])
            prompt_path = scenes_dir / f"scene_{number}.prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            record["prompt_file"] = str(prompt_path.relative_to(output))
            make_keyframe(client, image_model, prompt, image, record, image_size=(1080, 1920), reference_images=references)
            images.append(str(image))
        final = output / "preview.mp4"
        duration = len(images) * max(1, round(scene_seconds * 30)) / 30
        bgm = output / ("bgm" + bgm_source.suffix if bgm_source is not None else "bgm.wav")
        if bgm_source is None:
            make_original_bgm(bgm, duration)
            metadata["bgm_source"] = "generated_instrumental_96bpm_v1"
        else:
            shutil.copyfile(bgm_source, bgm)
            metadata["bgm_source"] = str(bgm_source.relative_to(ROOT))
        metadata["bgm_sha256"] = hashlib.sha256(bgm.read_bytes()).hexdigest()
        render_lookbook(images, bgm, final, scene_seconds=scene_seconds)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                               capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout)["streams"]
        if not any(s["codec_type"] == "video" and s.get("width") == 1080 and s.get("height") == 1920 for s in streams):
            raise RuntimeError("成片未包含 1080×1920 影片軌")
        if not any(s["codec_type"] == "audio" for s in streams):
            raise RuntimeError("成片缺少 BGM")
        metadata.update(status="completed", final_mp4=final.name, duration_seconds=duration)
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
    parser.add_argument("--scene-seconds", type=float, default=5)
    parser.add_argument("--bgm", default="", help="Optional licensed music file under assets/bgm/")
    args = parser.parse_args()
    try:
        story = load_script(args.script, args.style)
        if not 0 < args.scene_seconds <= 30:
            raise ValueError("每幕秒數需介於 0～30 秒")
        bgm_source = resolve_bgm(args.bgm)
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
            final = render_script(story, ROOT / "output/script-preview", client, model,
                                  scene_seconds=args.scene_seconds, bgm_source=bgm_source)
        print(f"完成，請下載 MP4：{final}")
        return 0
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
