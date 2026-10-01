"""Verify every stored native crop; never infer full-frame semantic ground truth."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from skimage.color import rgb2lab

from film_crops import crop_manifest, load_crop
from palette_evidence import palette_index, load_atlas
from reference_sources import archive_index, load_reference
from texture_features import pixel_hash
from verify_reference_privacy import require_private_workspace_paths

ROOT = Path(__file__).resolve().parents[1]


def measurement_digest(library):
    excluded = {'reference_asset','reference_file_sha256'}
    frames = [{k:v for k,v in frame.items() if k not in excluded} for frame in library['frames']]
    encoded = json.dumps(frames,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify(root=ROOT, compare_originals=False):
    root = Path(root)
    library = json.loads((root/'data/film-library.json').read_text())
    frames = library['frames']
    index = palette_index(root)
    if set(index) != {f['scene'] for f in frames}:
        raise ValueError('Every frame must have a native palette atlas for crop-edition acceptance')
    crops = crop_manifest(root,frames)
    grouped = defaultdict(list)
    for row in crops.values():
        grouped[row['scene']].append(row)
    originals = archive_index() if compare_originals else {}
    checked_patches = checked_textures = original_checks = palette_bytes = texture_bytes = 0
    coverage = []
    for i, frame in enumerate(frames,1):
        sid = frame['scene']
        source = None
        if compare_originals:
            source,_,_ = load_reference(frame,root=root,registry=originals)
            original_checks += 1
        swatches = {s['id']:s for s in frame['palette']}
        iw,ih = frame['dimensions']
        mask = np.zeros((ih,iw),bool)
        with load_atlas(frame,index[sid],root) as atlas:
            palette_bytes += (root/index[sid]['asset']).stat().st_size
            for patch in index[sid]['patches']:
                s = swatches[patch['swatch_id']]
                x,y,w,h = patch['rect']; tx,ty,_,_ = patch['tile']
                px,py = s['xy']
                actual = list(atlas.getpixel((tx+px-x,ty+py-y)))
                if actual != s['rgb'] or s['hex'] != '#'+''.join(f'{v:02X}' for v in actual):
                    raise ValueError(f'{sid}: palette anchor RGB/HEX differs')
                if not np.allclose(rgb2lab(np.array(actual,dtype=float).reshape(1,3)/255)[0],s['lab'],atol=1e-6):
                    raise ValueError(f'{sid}: palette Lab differs')
                if source is not None and pixel_hash(source.crop((x,y,x+w,y+h))) != patch['pixel_sha256']:
                    raise ValueError(f'{sid}: native palette context differs from original')
                mask[y:y+h,x:x+w] = True
                checked_patches += 1
        for row in grouped[sid]:
            with load_crop(root,row,context=True) as context:
                sx,sy,sw,sh = row['storage_rect']
                if source is not None and pixel_hash(source.crop((sx,sy,sx+sw,sy+sh))) != pixel_hash(context):
                    raise ValueError(f'{sid}: native texture context differs from original')
                mask[sy:sy+sh,sx:sx+sw] = True
            texture_bytes += (root/row['asset']).stat().st_size
            checked_textures += 1
        preserved = int(mask.sum())
        if preserved >= iw*ih:
            raise ValueError(f'{sid}: crop edition must not reconstruct an entire frame')
        coverage.append({'scene':sid,'retained_native_pixel_union':preserved,
                         'full_frame_pixels':iw*ih,'retained_fraction':preserved/(iw*ih)})
        if source is not None:
            source.close()
        if i % 100 == 0:
            print(f'Native crop evidence {i}/{len(frames)}',flush=True)
    result = dict(status='passed',frames=len(frames),palette_atlases=len(index),
                  palette_native_patches_checked=checked_patches,palette_anchor_pixels_checked=checked_patches,
                  texture_crops_checked=checked_textures,original_frames_compared=original_checks,
                  external_originals_used=compare_originals,all_crop_pixel_hashes_checked=True,
                  palette_asset_bytes=palette_bytes,texture_asset_bytes=texture_bytes,
                  measurements_sha256=measurement_digest(library),retained_pixel_coverage=coverage,
                  full_frame_reconstruction=False,full_frame_semantic_occupancy_complete=False,
                  boundary='All native crop pixels, coordinates, identities and palette anchors verified. '
                           'This is not a new manual semantic review, full-frame reconstruction, '
                           'cross-host image-generation test or copyright determination.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root',type=Path,default=ROOT)
    parser.add_argument('--compare-originals',action='store_true')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    if args.report:
        require_private_workspace_paths(args.report,root=args.skill_root)
    result = verify(args.skill_root,args.compare_originals)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'retained_pixel_coverage'},ensure_ascii=False))


if __name__ == '__main__':
    main()
