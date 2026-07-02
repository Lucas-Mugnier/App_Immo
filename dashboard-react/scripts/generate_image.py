#!/usr/bin/env python3
"""
Image generation script for ALPESTATE dashboard.
Uses OpenAI DALL-E 3 / gpt-image-1 for high-quality visuals.

Usage:
  python scripts/generate_image.py "prompt" --output public/images/name.png
  python scripts/generate_image.py "prompt" --style none --size 1536x1024 --quality high --output out.png
"""

import argparse
import base64
import os
import sys
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed. Run: pip install openai", file=sys.stderr)
    sys.exit(1)

# ── Style presets ─────────────────────────────────────────────────────────────

STYLES = {
    "alpine-photo": (
        "Ultra-realistic professional architectural photography, French Alps, "
        "cinematic lighting, shot on Phase One, tack-sharp, f/8 aperture, "
        "natural alpine light, premium real estate aesthetic, "
        "no people, no text overlays"
    ),
    "alpine-aerial": (
        "Aerial drone photography, French Alps mountain landscape, "
        "golden hour or blue hour, cinematic wide angle, "
        "ultra-sharp details, professional real estate photography style, "
        "no people, no text"
    ),
    "alpine-minimal": (
        "Minimalist architectural photography, alpine modern design, "
        "clean lines, dramatic mountain backdrop, moody atmosphere, "
        "dark color palette, premium luxury feel, "
        "shot on Hasselblad, shallow depth of field, no people"
    ),
    "none": "",
    # Legacy skill styles kept for compatibility
    "queer-collage-no-text": "",
    "queer-collage": "",
}

SIZE_MAP = {
    "1024x1024": "1024x1024",
    "1024x1536": "1024x1536",
    "1536x1024": "1536x1024",
}

# ── Main ──────────────────────────────────────────────────────────────────────

def get_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        # Try .env file in project root
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"\'')
                    break
    if not key:
        print("ERROR: OPENAI_API_KEY not set.", file=sys.stderr)
        print("  Set it via:  set OPENAI_API_KEY=sk-...", file=sys.stderr)
        print("  Or add it to .env:  OPENAI_API_KEY=sk-...", file=sys.stderr)
        sys.exit(1)
    return OpenAI(api_key=key)


def build_prompt(user_prompt: str, style: str) -> str:
    style_block = STYLES.get(style, "")
    if style_block:
        return f"{user_prompt}. {style_block}"
    return user_prompt


def generate(client: OpenAI, prompt: str, model: str, size: str, quality: str, count: int, output: Path):
    print(f"  Model  : {model}")
    print(f"  Size   : {size}")
    print(f"  Quality: {quality}")
    print(f"  Count  : {count}")
    print(f"  Prompt : {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    for i in range(count):
        out_path = output
        if count > 1:
            out_path = output.parent / f"{output.stem}_{i}{output.suffix}"

        print(f"\n  Generating {i+1}/{count} → {out_path}")

        if model == "dall-e-3":
            resp = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="hd" if quality == "high" else "standard",
                n=1,
                response_format="b64_json",
            )
            img_data = base64.b64decode(resp.data[0].b64_json)
        elif model == "dall-e-2":
            resp = client.images.generate(
                model="dall-e-2",
                prompt=prompt,
                size="1024x1024",
                n=1,
                response_format="b64_json",
            )
            img_data = base64.b64decode(resp.data[0].b64_json)
        else:
            # gpt-image-1
            quality_map = {"low": "low", "medium": "medium", "high": "high", "auto": "auto"}
            resp = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=size,
                quality=quality_map.get(quality, "high"),
                n=1,
            )
            img_data = base64.b64decode(resp.data[0].b64_json)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_data)
        print(f"  ✓ Saved: {out_path} ({len(img_data) // 1024} KB)")


def main():
    parser = argparse.ArgumentParser(description="ALPESTATE image generator")
    parser.add_argument("prompt", nargs="?", default="", help="Image description")
    parser.add_argument("--style",   default="alpine-photo",
                        choices=list(STYLES.keys()), help="Style preset")
    parser.add_argument("--model",   default="dall-e-3",
                        choices=["gpt-image-1", "dall-e-3", "dall-e-2"])
    parser.add_argument("--size",    default="1536x1024",
                        choices=list(SIZE_MAP.keys()))
    parser.add_argument("--quality", default="high",
                        choices=["low", "medium", "high", "auto"])
    parser.add_argument("--count",   type=int, default=1)
    parser.add_argument("--output",  default="output.png")
    parser.add_argument("--list-styles", action="store_true")

    args = parser.parse_args()

    if args.list_styles:
        print("Available styles:")
        for k, v in STYLES.items():
            print(f"  {k:30s} — {v[:60]}{'...' if len(v) > 60 else ''}")
        return

    if not args.prompt:
        parser.print_help()
        sys.exit(1)

    client   = get_client()
    prompt   = build_prompt(args.prompt, args.style)
    out_path = Path(args.output)
    size     = SIZE_MAP.get(args.size, "1536x1024")

    generate(client, prompt, args.model, size, args.quality, args.count, out_path)
    print("\n  Done.")


if __name__ == "__main__":
    main()
