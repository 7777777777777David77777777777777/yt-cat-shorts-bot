"""Strict, dependency-free Markdown field parsing for fashion story structure."""

import re


WARDROBE_FIELDS = {"上衣": "top", "下身": "bottom", "連身衣": "one_piece", "襪類": "hosiery",
                   "鞋款": "footwear", "配件": "accessories", "top": "top", "bottom": "bottom",
                   "one_piece": "one_piece", "hosiery": "hosiery", "footwear": "footwear", "accessories": "accessories"}
SETTING_FIELDS = {"地點": "location", "光線": "lighting", "location": "location", "lighting": "lighting"}
SHOT_FIELDS = {"景別": "type", "角度": "angle", "主體": "subject", "入鏡範圍": "coverage",
               "排除": "exclude", "臉部入鏡": "face_visible", "type": "type", "angle": "angle",
               "subject": "subject", "coverage": "coverage", "exclude": "exclude", "face_visible": "face_visible"}
SHOT_TYPES = {"全身": "full_body", "半身": "half_body", "肖像": "portrait", "服飾細節": "detail",
              "full_body": "full_body", "half_body": "half_body", "portrait": "portrait", "detail": "detail"}
SHOT_DEFAULTS = {
    "full_body": "Entire head, torso, legs and both shoes, with natural headroom and floor space.",
    "half_body": "Head and upper body to the waist.",
    "portrait": "Head and shoulders.",
}


def parse_items(text, aliases, label):
    result = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*[-*]\s+([^:：]+)[:：]\s*(.+?)\s*", line)
        if not match or match[1].strip().lower() not in aliases:
            raise ValueError(f"{label}：請使用支援的「- 欄位：內容」，錯誤行 {line!r}")
        key = aliases[match[1].strip().lower()]
        if key in result:
            raise ValueError(f"{label}：欄位 {match[1].strip()} 重複")
        result[key] = match[2]
    if not result:
        raise ValueError(f"{label}不能空白")
    return result


def parse_shot(text):
    shot = parse_items(text, SHOT_FIELDS, "鏡頭")
    kind = SHOT_TYPES.get(shot.get("type", ""))
    if not kind:
        raise ValueError("鏡頭景別請填：全身、半身、肖像、服飾細節")
    shot["type"] = kind
    visible = shot.get("face_visible", "否" if kind == "detail" else "是").lower()
    if visible not in ("是", "否", "true", "false"):
        raise ValueError("臉部入鏡請填是或否")
    shot["face_visible"] = visible in ("是", "true")
    shot.setdefault("angle", "Eye-level with natural perspective")
    if kind in SHOT_DEFAULTS:
        shot.setdefault("coverage", SHOT_DEFAULTS[kind])
        shot.setdefault("subject", "The episode's character and wardrobe")
    shot.setdefault("exclude", "No text, collage or inset portraits")
    return shot


def validate_structure(data):
    """Validate contradictions expressible in fields; visual compliance still needs review."""
    structured = any(field in data for field in ("character_profile", "wardrobe", "setting"))
    if not structured:
        # Explicit camera fields are also checked for otherwise legacy scripts.
        structured = any("shot" in scene for scene in data["scenes"])
    if not structured:
        return
    wardrobe = data.get("wardrobe")
    if not isinstance(wardrobe, dict) or set(wardrobe) - set(WARDROBE_FIELDS.values()):
        raise ValueError("結構化劇本需要本集服裝欄位")
    if any(not isinstance(v, str) or not v.strip() for v in wardrobe.values()):
        raise ValueError("服裝項目必須是非空白文字；沒有的鞋襪請明確填無")
    separate = "top" in wardrobe or "bottom" in wardrobe
    if "one_piece" in wardrobe:
        if separate:
            raise ValueError("服裝請選連身衣，或上衣＋下身，不可同時指定")
    elif not {"top", "bottom"} <= wardrobe.keys():
        raise ValueError("服裝需要上衣＋下身，或連身衣")
    if not {"hosiery", "footwear"} <= wardrobe.keys():
        raise ValueError("服裝需要襪類及鞋款；沒有時請明確填無")
    setting = data.get("setting", {})
    if not isinstance(setting, dict) or set(setting) - {"location", "lighting"}:
        raise ValueError("共同場景只支援地點及光線")
    if any(not isinstance(v, str) or not v.strip() for v in setting.values()):
        raise ValueError("共同場景欄位不能空白")
    for i, scene in enumerate(data["scenes"], 1):
        if not (scene.get("location") or setting.get("location")):
            raise ValueError(f"第 {i} 幕需要地點，或設定共同場景的地點")
        shot = scene.get("shot")
        if not isinstance(shot, dict) or set(shot) - set(SHOT_FIELDS.values()):
            raise ValueError(f"第 {i} 幕需要鏡頭欄位")
        if shot.get("type") not in SHOT_DEFAULTS and shot.get("type") != "detail":
            raise ValueError(f"第 {i} 幕景別無效")
        if not isinstance(shot.get("face_visible"), bool):
            raise ValueError(f"第 {i} 幕需指定臉部入鏡是或否")
        for field in ("subject", "coverage", "angle", "exclude"):
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise ValueError(f"第 {i} 幕鏡頭缺少 {field}")
        if shot["face_visible"] != (shot["type"] != "detail"):
            raise ValueError(f"第 {i} 幕景別與臉部入鏡設定衝突；服飾細節不含臉部")
        if not shot["face_visible"] and scene.get("expression", "").strip():
            raise ValueError(f"第 {i} 幕臉不入鏡，請移除表情欄位")
    if data["scenes"][0]["shot"]["type"] != "full_body":
        raise ValueError("第一幕請使用全身景別，建立當集服裝參考")


def parse_profile(text):
    aliases = {"身分": "identity", "外觀": "appearance", "身形": "build", "參考圖": "references",
               "identity": "identity", "appearance": "appearance", "build": "build", "references": "references"}
    fields, key, title = {}, None, None
    for line in text.splitlines():
        heading = re.fullmatch(r"(#+)\s+(.+?)\s*", line)
        if heading:
            if heading[1] == "#" and title is None and not fields:
                title = heading[2]
                continue
            if heading[1] != "##" or heading[2].lower() not in aliases:
                raise ValueError(f"不支援的角色檔標題：{heading[2]}")
            key = aliases[heading[2].lower()]
            if key in fields:
                raise ValueError("角色檔欄位重複")
            fields[key] = []
        elif key is not None:
            fields[key].append(line)
        elif line.strip():
            raise ValueError("角色檔內容需放在欄位標題下")
    values = {key: "\n".join(lines).strip() for key, lines in fields.items()}
    if not title or any(not values.get(field) for field in aliases.values()):
        raise ValueError("角色檔需有名稱、身分、外觀、身形及參考圖")
    values["references"] = parse_items(values["references"], {
        "肖像": "portrait", "全身": "full_body", "portrait": "portrait", "full_body": "full_body"}, "角色參考圖")
    if "portrait" not in values["references"]:
        raise ValueError("角色檔需要肖像參考圖")
    return dict(values, name=title)


def format_wardrobe(wardrobe):
    labels = {"top": "Top", "bottom": "Bottom", "one_piece": "One-piece outfit",
              "hosiery": "Hosiery", "footwear": "Footwear", "accessories": "Accessories"}
    return "\n".join(f"- {label}: {wardrobe[key]}" for key, label in labels.items() if key in wardrobe)
