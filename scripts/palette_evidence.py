"""Read exact palette pixels from full representatives or traced native crop atlases."""
import json
from pathlib import Path

from film_color import sha256, srgb_image
from reference_sources import ROOT, load_reference, source_path
from texture_features import pixel_hash


def palette_index(root=ROOT):
    path = Path(root)/'data/palette-crops.json'
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    if doc['schema_version'] != 1 or doc['full_frame_reconstruction'] is not False:
        raise ValueError('Invalid palette crop schema')
    result = {r['scene']: r for r in doc['frames']}
    if len(result) != len(doc['frames']) or doc['count'] != len(result):
        raise ValueError('Duplicate palette frame or count mismatch')
    return result


def validate_palette_row(frame, row):
    if row['source_sha256'] != frame['sha256'] or row['source_pixel_sha256'] != frame['pixel_sha256']:
        raise ValueError('Palette crop source identity changed')
    if row['asset'] != f"assets/palette-crops/{frame['scene']:03d}.webp":
        raise ValueError('Invalid palette crop path')
    patches = {p['swatch_id']: p for p in row['patches']}
    swatches = {s['id']: s for s in frame['palette']}
    if len(patches) != len(row['patches']) or set(patches) != set(swatches):
        raise ValueError('Palette crop coverage changed')
    occupied = []
    for sid, patch in patches.items():
        if any(type(v) is not int for v in patch['rect']+patch['tile']):
            raise ValueError('Palette coordinates must be integers')
        x, y, w, h = patch['rect']
        tx, ty, tw, th = patch['tile']
        iw, ih = frame['dimensions']
        aw, ah = row['dimensions']
        px, py = swatches[sid]['xy']
        if (min(x,y,tx,ty) < 0 or min(w,h) <= 0 or [w,h] != [tw,th] or
                x+w > iw or y+h > ih or tx+w > aw or ty+h > ah or
                not (x <= px < x+w and y <= py < y+h)):
            raise ValueError('Palette crop outside source or atlas')
        # Tile rectangles must not overlap; atlas locations never imply scene adjacency.
        if any(tx < ax+aw and ax < tx+w and ty < ay+ah and ay < ty+h for ax,ay,aw,ah in occupied):
            raise ValueError('Overlapping palette atlas tiles')
        occupied.append((tx,ty,w,h))
    return patches


def load_atlas(frame, row, root=ROOT):
    root = Path(root).resolve()
    validate_palette_row(frame, row)
    path = root/row['asset']
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Palette atlas escapes the skill directory')
    if sha256(path) != row['file_sha256']:
        raise ValueError('Palette atlas file hash changed')
    im, _ = srgb_image(path)
    if list(im.size) != row['dimensions'] or pixel_hash(im) != row['pixel_sha256']:
        im.close()
        raise ValueError('Palette atlas pixels changed')
    for patch in row['patches']:
        x,y,w,h = patch['tile']
        crop = im.crop((x,y,x+w,y+h))
        valid = pixel_hash(crop) == patch['pixel_sha256']
        crop.close()
        if not valid:
            im.close()
            raise ValueError('Palette patch pixels changed')
    return im


def evidence_info(frame, swatch, index, registry=None, root=ROOT):
    path = source_path(frame, required=False, root=root, registry=registry)
    if path:
        return {'evidence_path':str(path), 'evidence_available':True, 'evidence_scope':'full-frame'}
    row = index.get(frame['scene'])
    if row and row['source_sha256'] == frame['sha256']:
        patch = next((p for p in row['patches'] if p['swatch_id'] == swatch['swatch_id']), None)
        path = Path(root)/row['asset']
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError('Palette atlas escapes the skill directory')
        if patch and path.is_file():
            x,y,_,_ = patch['rect']
            tx,ty,_,_ = patch['tile']
            px,py = swatch['xy']
            return {'evidence_path':str(path), 'evidence_available':True, 'evidence_scope':'native-crop',
                    'source_crop_rect':patch['rect'], 'atlas_tile':patch['tile'],
                    'atlas_sample_xy':[tx+px-x,ty+py-y], 'crop_context_review_required':True}
    return {'evidence_path':None, 'evidence_available':False, 'evidence_scope':'unavailable'}


def palette_pixel(frame, swatch, index, registry=None, root=ROOT):
    if source_path(frame, required=False, root=root, registry=registry):
        im, _, _ = load_reference(frame, root=root, registry=registry)
        try:
            return im.getpixel(tuple(swatch['xy']))
        finally:
            im.close()
    row = index.get(frame['scene'])
    if row is None:
        raise FileNotFoundError('Original palette pixel evidence unavailable')
    with load_atlas(frame, row, root=root) as im:
        patch = next(p for p in row['patches'] if p['swatch_id'] == swatch['swatch_id'])
        x,y,_,_ = patch['rect']
        tx,ty,_,_ = patch['tile']
        px,py = swatch['xy']
        return im.getpixel((tx+px-x,ty+py-y))
