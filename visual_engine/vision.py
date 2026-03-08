import asyncio
import mimetypes
from pathlib import Path

from .auth import get_client

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _detect_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MIME_MAP:
        return MIME_MAP[suffix]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/png"


def _call_gemini(image_paths: list[str], prompt: str, model: str) -> str:
    from google.genai import types

    client = get_client()

    contents = []
    for path_str in image_paths:
        path = Path(path_str)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")
        contents.append(
            types.Part.from_bytes(
                data=path.read_bytes(),
                mime_type=_detect_mime(path),
            )
        )
    contents.append(prompt)

    response = client.models.generate_content(model=model, contents=contents)
    return response.text


async def analyze(image_paths: list[str], prompt: str, model: str) -> str:
    return await asyncio.to_thread(_call_gemini, image_paths, prompt, model)
