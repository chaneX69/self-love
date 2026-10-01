"""Resolve portable reference assets or a separately configured local evidence archive."""
import json
import os
from pathlib import Path
from film_color import sha256, srgb_image
from texture_features import pixel_hash

ROOT = Path(__file__).resolve().parents[1]


def archive_index():
    path = Path(os.environ.get('SELF_LOVE_ARCHIVE_INDEX',
                str(Path.home()/'.config/self-love/archive-index.json')))
    return json.loads(path.read_text()) if path.is_file() else {}


def source_path(frame, required=True, root=None, registry=None):
    root = Path(root or ROOT).resolve()
    asset = frame.get('reference_asset')
    if asset:
        path = (root/asset).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Reference asset escapes the skill directory')
        if path.is_file():
            return path
    original = frame.get('original', '')
    if original and not original.startswith('evidence://'):
        path = Path(original)
        path = path if path.is_absolute() else root/path
        if path.is_file():
            return path.resolve()
    index = archive_index() if registry is None else registry
    archived = index.get(frame['sha256'])
    if archived and Path(archived).is_file():
        return Path(archived).resolve()
    if required:
        raise FileNotFoundError(f"Frame {frame['scene']}: original-pixel evidence unavailable; "
                                "configure SELF_LOVE_ARCHIVE_INDEX or restore its verified reference asset. "
                                "A palette alone cannot approve pixel material or texture.")
    return None


def load_reference(frame, root=None, registry=None):
    path = source_path(frame, root=root, registry=registry)
    base = Path(root or ROOT).resolve()
    core = bool(frame.get('reference_asset')) and path == (base/frame['reference_asset']).resolve()
    expected = frame.get('reference_file_sha256') if core else frame['sha256']
    if not expected or sha256(path) != expected:
        raise ValueError(f"Frame {frame['scene']}: reference file hash changed")
    im, status = srgb_image(path)
    if frame.get('dimensions') and list(im.size) != frame['dimensions']:
        raise ValueError('Reference dimensions changed')
    if frame.get('pixel_sha256') and pixel_hash(im) != frame['pixel_sha256']:
        raise ValueError('Reference sRGB pixels changed')
    return im, status, path
