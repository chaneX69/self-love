"""Validate original-pixel film crops against the accepted candidate archive."""
import gzip
import json
import re
from pathlib import Path

from film_color import sha256, srgb_image
from texture_features import pixel_hash


def crop_manifest(root, frames):
    root = Path(root)
    path = root/'data/film-crops.json'
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    if doc['schema_version'] != 1 or doc['full_frame_replacement'] is not False:
        raise ValueError('Unsupported crop schema or false full-frame replacement')
    with gzip.open(root/'data/semantic-texture-candidates.jsonl.gz', 'rt') as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    accepted = {r['id']: r for r in records}
    by_scene = {f['scene']: f for f in frames}
    if len(accepted) != len(records):
        raise ValueError('Duplicate accepted candidate ID')
    result = {}
    seen = set()
    for row in doc['crops']:
        rid = row['id']
        if not re.fullmatch(r'[a-z0-9-]+', rid) or rid in seen:
            raise ValueError('Invalid or duplicate crop ID')
        seen.add(rid)
        record = accepted[rid]
        frame = by_scene[row['scene']]
        if record['overlay_review']['status'] != 'accepted_candidate':
            raise ValueError('Crop is not an accepted local candidate')
        for key in ('scene', 'class', 'rect', 'source_sha256', 'source_pixel_sha256', 'crop_pixel_sha256'):
            if row[key] != record[key]:
                raise ValueError('Crop provenance differs from candidate: '+key)
        if row['source_sha256'] != frame['sha256'] or row['source_pixel_sha256'] != frame['pixel_sha256']:
            raise ValueError('Crop source is not in the movie catalog')
        rect = row['rect']
        if len(rect) != 4 or any(type(v) is not int for v in rect):
            raise ValueError('Crop rectangle must use native integer coordinates')
        x, y, w, h = rect
        iw, ih = frame['dimensions']
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > iw or y+h > ih:
            raise ValueError('Crop rectangle outside original frame')
        asset = f'assets/crops/{rid}.webp'
        sx, sy, sw, sh = row.get('storage_rect', rect)
        if (min(sx, sy) < 0 or sx+sw > iw or sy+sh > ih or
                sx > x or sy > y or sx+sw < x+w or sy+sh < y+h):
            raise ValueError('Crop context does not contain its original region')
        if row['asset'] != asset or row['dimensions'] != [sw, sh]:
            raise ValueError('Invalid crop path or dimensions')
        result[asset] = row
    if seen != set(accepted) or doc['count'] != len(result):
        raise ValueError('Accepted crop coverage incomplete')
    return result


def load_crop(root, row, context=False):
    root = Path(root).resolve()
    path = root/row['asset']
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Crop escapes the skill directory')
    if sha256(path) != row['file_sha256']:
        raise ValueError('Crop file hash changed')
    im, _ = srgb_image(path)
    if list(im.size) != row['dimensions'] or pixel_hash(im) != row.get('storage_pixel_sha256', row['crop_pixel_sha256']):
        im.close()
        raise ValueError('Crop original pixels changed')
    x, y, w, h = row['rect']
    sx, sy, _, _ = row.get('storage_rect', row['rect'])
    region = im.crop((x-sx, y-sy, x-sx+w, y-sy+h))
    if pixel_hash(region) != row['crop_pixel_sha256']:
        im.close()
        region.close()
        raise ValueError('Analysis region pixels changed')
    if not context:
        im.close()
        return region
    region.close()
    return im
