"""Fake fal.ai and Poly Haven endpoints shared by the Blender tests."""

calls = []


def fake_fal(method, url, headers=None, body=None, timeout=60):
    if method == "POST":
        model = url.split("queue.fal.run/")[1]
        calls.append((model, body))
        fake_fal.current = model
        return {"status_url": "https://q/r/status", "response_url": "https://q/r"}
    if url.endswith("/status"):
        return {"status": "COMPLETED"}
    model = fake_fal.current
    if "video" in model or "veo" in model:
        return {"video": {"url": "https://x/out.mp4", "content_type": "video/mp4"}}
    if "trellis" in model:
        return {"model_mesh": {"url": "https://x/m.glb"}}
    if "tripo" in model:
        return {"model_mesh": {"url": "https://x/m.fbx"}, "model_urls": {"glb": {"url": "https://x/m.glb"}}}
    if "retexture" in model:
        return {"model_glb": {"url": "https://x/t.glb"}, "model_urls": {"glb": {"url": "https://x/t.glb"}}}
    if "rigging" in model:
        return {"rigged_character_glb": {"url": "https://x/r.glb"}, "basic_animations": {},
                "animation_glb": {"url": "https://x/animation.glb"}}
    if "hunyuan-motion" in model:
        return {"fbx_file": {"url": "https://x/motion.fbx"}}
    return {"images": [{"url": "https://x/i.png", "content_type": "image/png"}]}


def fake_polyhaven(method, url, headers=None, body=None, timeout=60):
    if "/assets" in url:
        return {"sunset_a": {"name": "Sunset A", "tags": ["sunset"], "categories": [], "download_count": 5},
                "brick_b": {"name": "Brick B", "tags": ["brick"], "categories": [], "download_count": 3}}
    asset = url.rsplit("/", 1)[-1]
    if asset == "sunset_a":
        return {"hdri": {"1k": {"hdr": {"url": "https://x/sunset_a_1k.hdr"}}}}
    return {"Diffuse": {"1k": {"jpg": {"url": "https://x/b_diff.png"}}},
            "nor_gl": {"1k": {"jpg": {"url": "https://x/b_nor.png"}}}}


def last_call():
    return calls[-1] if calls else (None, {})
