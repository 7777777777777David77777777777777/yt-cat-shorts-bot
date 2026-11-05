"""Manual EP01 image-to-video experiment. Never reads or writes the live queue."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from google import genai
from google.genai import types
from PIL import Image, ImageOps

import main as factory


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "tests/fixtures/ep01.json"
DEFAULT_VIDEO_MODEL = "veo-3.1-fast-generate-preview"
CLIP_SECONDS = 8
MOTION = (
    "Mia gently holds the kitten; the kitten blinks and Titan calmly tilts his head.",
    "Titan slowly offers his front paw; Mochi sniffs it while Mia smiles.",
    "Mochi sleeps with subtle breathing; Mia gently settles the blanket over Titan.",
    "The friends sit together; their blue scarves move softly in a light breeze.",
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_episode():
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row = dict(snapshot["episode"])
    if row["id"] != "EP01":
        raise ValueError("This preview is restricted to EP01")
    # Select edition one locally, independently of the live Sheet's completed count.
    row.update(sent_count=0, status="Preview only", row_index=None)
    story = factory.parse_episode_from_row(row)
    story.update(preview_only=True, source=snapshot["source"], youtube_upload=False,
                 sheet_writeback=False)
    return story


def video_prompt(story, index):
    return (
        "Animate the supplied reference image in its existing visual style.\n"
        f"Scene: {story['scenes'][index]['scene_action']}\n"
        f"Character references: {story['character_dna']}\n"
        f"Motion: {MOTION[index]}\n"
        "Preserve the characters' original ages, species, colors, markings, clothing "
        "and relative sizes. Keep the original setting and a stable camera. "
        "Use gentle, natural motion with no cuts or extra characters. "
        "Full-bleed vertical 9:16; extend the background to all four edges, "
        "without borders, margins, letterboxing, text or captions. "
        "Narration will be added separately; no talking or lip sync is needed."
    )


def make_keyframe(client, model, prompt, path, record):
    result = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="9:16")),
    )
    factory.capture_token_usage(record, result)
    images = [part.inline_data for candidate in result.candidates or []
              if candidate.content for part in candidate.content.parts or []
              if not part.thought and part.inline_data and part.inline_data.data
              and (part.inline_data.mime_type or "").startswith("image/")]
    record["returned_images"] = len(images)
    if not images:
        raise RuntimeError("Gemini returned no image; preview stopped without fallback")
    source = path.with_suffix(".source.png")
    source.write_bytes(images[0].data)
    with Image.open(source) as image:
        # Crop to cover the canvas without stretching the source image.
        ImageOps.fit(image.convert("RGB"), (720, 1280),
                     method=Image.Resampling.LANCZOS).save(path)
    record["image_used"] = True


def generate_clip(client, model, prompt, image_path, video_path, record, persist,
                  deadline, clock=time.monotonic, sleep=time.sleep):
    if clock() >= deadline:
        raise TimeoutError("Preview time budget exhausted before generation")
    record.update(status="submitting", requested_seconds=CLIP_SECONDS)
    persist()
    operation = client.models.generate_videos(
        model=model, source=types.GenerateVideosSource(
            prompt=prompt, image=types.Image.from_file(location=str(image_path))),
        config=types.GenerateVideosConfig(
            number_of_videos=1, duration_seconds=CLIP_SECONDS,
            aspect_ratio="9:16", resolution="720p"),
    )
    record.update(operation_name=operation.name, status="waiting")
    persist()
    while not operation.done:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("Veo wait timed out; operation ID saved. Do not blindly resubmit")
        sleep(min(10, remaining))
        operation = client.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"Veo operation failed: {operation.error}")
    result = operation.response or operation.result
    if result is None or not result.generated_videos:
        reasons = getattr(result, "rai_media_filtered_reasons", None)
        raise RuntimeError(f"Veo returned no video (filter/permission may apply): {reasons}")
    video = result.generated_videos[0].video
    if video is None:
        raise RuntimeError("Veo returned an empty video")
    if video.video_bytes:
        video_path.write_bytes(video.video_bytes)
    else:
        client.files.download(file=video, destination=str(video_path))
    if not video_path.is_file() or video_path.stat().st_size == 0:
        raise RuntimeError("Veo download was empty")
    info = probe(video_path)
    if not any(s["codec_type"] == "video" for s in info["streams"]):
        raise RuntimeError("Veo download contains no video stream")
    record.update(status="downloaded", file=video_path.name,
                  returned_seconds=float(info["format"]["duration"]))
    persist()


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def timestamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_subtitles(path, narration, duration):
    phrases = factory.split_into_single_line_phrases(narration)
    path.write_text("\n\n".join(
        f"{i + 1}\n{timestamp(i * duration / len(phrases))} --> "
        f"{timestamp((i + 1) * duration / len(phrases))}\n{phrase}"
        for i, phrase in enumerate(phrases)) + "\n", encoding="utf-8")


def render_preview(directory, scenes, clips, audios):
    """Retain all narration; retime each generated clip to its narration length."""
    segments, timings = [], []
    for index, (scene, clip, audio) in enumerate(zip(scenes, clips, audios), 1):
        audio_duration = float(probe(audio)["format"]["duration"])
        video_duration = float(probe(clip)["format"]["duration"])
        if audio_duration <= 0 or video_duration <= 0:
            raise ValueError("Invalid source duration")
        ratio = audio_duration / video_duration
        subtitles = directory / f"scene_{index}.srt"
        segment = directory / f"segment_{index}.mp4"
        write_subtitles(subtitles, scene["narration"], audio_duration)
        vf = ("scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,"
              f"setpts={ratio:.8f}*(PTS-STARTPTS),fps=24,tpad=stop_mode=clone:stop_duration=1,"
              f"subtitles={subtitles.name}:force_style='FontName=Liberation Sans,"
              "FontSize=24,Outline=2,Alignment=2,MarginV=120'")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
             "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
             "-af", "apad", "-t", f"{audio_duration:.6f}", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-ar", "48000", "-ac", "2", "-b:a", "128k", str(segment)],
            cwd=directory, check=True)
        segments.append(segment)
        timings.append({"scene": index, "narration_seconds": audio_duration,
                        "generated_seconds": video_duration, "video_time_scale": ratio})
    manifest = directory / "segments.txt"
    manifest.write_text("".join(f"file '{path.name}'\n" for path in segments), encoding="utf-8")
    final = directory / "EP01_animation_preview.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(manifest), "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    info = probe(final)
    video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
    if (video["width"], video["height"]) != (720, 1280):
        raise RuntimeError("Final MP4 is not 720x1280")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise RuntimeError("Final MP4 has no narration stream")
    if abs(float(info["format"]["duration"]) - sum(t["narration_seconds"] for t in timings)) > 0.5:
        raise RuntimeError("Final MP4 duration does not match narration")
    return final, timings


def safe_error(error):
    message = str(error)
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        message = message.replace(key, "[REDACTED]")
    message = re.sub(r"(?i)([?&]key=)[^&\s]+", r"\1[REDACTED]", message)
    return f"{type(error).__name__}: {message[:1200]}"


def run_preview(client, directory, scene_count=4, image_model="gemini-2.5-flash-image",
                video_model=DEFAULT_VIDEO_MODEL):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # A rerun in the same folder must not silently submit more paid generations.
    if any(directory.iterdir()):
        raise ValueError("Preview directory must be empty; keep the previous attempt's artifacts")
    if scene_count not in (1, 4):
        raise ValueError("scene_count must be 1 or 4")
    story = load_episode()
    story["scenes"] = story["scenes"][:scene_count]
    state = {"status": "running", "episode": story, "scene_count": scene_count,
             "image_model": image_model, "video_model": video_model,
             "image_requests": [], "video_requests": [],
             "billing_note": "Image tokens are recorded when reported. Video generation is billed "
                             "by the provider; requested seconds are not a token count or price.",
             "snapshot_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest()}
    persist = lambda: write_json(directory / "metadata.json", state)
    persist()
    clips, audios = [], []
    deadline = time.monotonic() + 20 * 60
    try:
        for index, scene in enumerate(story["scenes"]):
            if time.monotonic() >= deadline:
                raise TimeoutError("Preview time budget exhausted before next scene")
            number = index + 1
            state.update(current_scene=number, stage="keyframe")
            print(f"EP01 scene {number}/{scene_count}: image then Veo (one request each)", flush=True)
            image = directory / f"scene_{number}.png"
            image_record = factory.start_image_request(state["image_requests"], "google", image_model, number)
            persist()
            make_keyframe(client, image_model, scene["full_image_prompt"], image, image_record)
            persist()
            prompt = video_prompt(story, index)
            (directory / f"scene_{number}.video-prompt.txt").write_text(prompt, encoding="utf-8")
            record = {"scene": number, "model": video_model}
            state["video_requests"].append(record)
            clip = directory / f"scene_{number}.veo.mp4"
            state["stage"] = "video"
            generate_clip(client, video_model, prompt, image, clip, record, persist,
                          deadline=min(deadline, time.monotonic() + 8 * 60))
            # First-scene failure exits here, before paying for scenes two to four.
            state["stage"] = "narration"
            audio = directory / f"scene_{number}.mp3"
            asyncio.run(factory.generate_speech_audio(scene["narration"], str(audio), story["voice_name"]))
            clips.append(clip)
            audios.append(audio)
        state["stage"] = "render"
        persist()
        final, timings = render_preview(directory, story["scenes"], clips, audios)
        state.update(status="completed", final_mp4=final.name, timings=timings)
        print(f"Download artifact: {final.name}", flush=True)
        return final
    except Exception as error:
        state.update(status="failed", error=safe_error(error))
        if state["video_requests"] and state["video_requests"][-1]["status"] != "downloaded":
            state["video_requests"][-1].update(status="failed", failure=safe_error(error))
        raise
    finally:
        state["image_usage"] = factory.summarize_image_usage(state["image_requests"])
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-count", type=int, choices=(1, 4), default=4)
    args = parser.parse_args()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        parser.error("GEMINI_API_KEY is required (repository Actions secret)")
    client = genai.Client(
        api_key=key, vertexai=False,
        http_options=types.HttpOptions(timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        run_preview(client, ROOT / "output/ep01-preview", scene_count=args.scene_count)
    except Exception as error:
        print(safe_error(error), file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
