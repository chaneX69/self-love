"""Reproduce reviewed-region pixel traces without claiming full-frame semantic truth."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

from reference_sources import load_reference
from texture_features import pixel_hash

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ('halftone', 'hatching', 'screen_mesh', 'color_misregistration')


def rle_encode(array):
    flat = np.asarray(array, dtype=np.uint8).ravel()
    if not len(flat):
        return []
    starts = np.r_[0, np.flatnonzero(flat[1:] != flat[:-1]) + 1]
    ends = np.r_[starts[1:], len(flat)]
    return [[int(flat[a]), int(b-a)] for a, b in zip(starts, ends)]


def rle_decode(runs, shape):
    size = int(np.prod(shape))
    if len(shape) != 2 or min(shape) <= 0:
        raise ValueError('A positive two-dimensional shape is required')
    total = 0
    for value, count in runs:
        if type(value) is not int or value not in (0, 1, 2):
            raise ValueError('Unexpected mask state')
        if type(count) is not int or count <= 0:
            raise ValueError('Invalid run length')
        total += count
    if total != size:
        raise ValueError('Mask run lengths do not match dimensions')
    return np.repeat(np.array([r[0] for r in runs], dtype=np.uint8),
                     np.array([r[1] for r in runs])).reshape(shape)


def valid_pixels(size, region, exclusions):
    width, height = size
    ys, xs = np.mgrid[:height, :width]
    a, b, c, d = region
    valid = (xs >= a*width) & (xs < c*width) & (ys >= b*height) & (ys < d*height)
    for exclusion in exclusions:
        a, b, c, d = exclusion['rect']
        valid &= ~((xs >= a*width) & (xs < c*width) & (ys >= b*height) & (ys < d*height))
    return valid


def trace(im, annotation):
    x, y, width, height = annotation['rect']
    if any(type(v) is not int for v in annotation['rect']):
        raise ValueError('Native integer pixel coordinates required')
    if min(x, y) < 0 or min(width, height) <= 0 or x+width > im.width or y+height > im.height:
        raise ValueError('Annotation outside source image')
    if annotation['class'] not in CLASSES:
        raise ValueError('Unknown semantic class')
    lo, hi = annotation['low'], annotation['high']
    if not 0 <= lo < hi:
        raise ValueError('Require 0 <= low < high')
    rgb = np.asarray(im.convert('RGB'), dtype=np.float32)
    mode = annotation['mode']
    if mode == 'chroma-range':
        if annotation['class'] != 'color_misregistration':
            raise ValueError('Region-restricted color-band trace requires reviewed offset semantics')
        score = rgb.max(axis=2) - rgb.min(axis=2)
    elif mode in ('light', 'dark'):
        sigma = annotation['sigma']
        if not 0 < sigma <= 20:
            raise ValueError('Unexpected smoothing scale')
        gray = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
        score = gaussian_filter(gray, sigma) - gray
        if mode == 'light':
            score = -score
    else:
        raise ValueError('Unsupported trace method')
    score = score[y:y+height, x:x+width]
    states = np.zeros((height, width), dtype=np.uint8)
    states[score >= lo] = 2
    states[score >= hi] = 1
    return states


def build(library, reviews, loader=load_reference):
    by_id = {int(f['scene']): f for f in library['frames']}
    records = []
    ids = set()
    for annotation in reviews['regions']:
        if annotation['id'] in ids:
            raise ValueError('Duplicate annotation ID')
        ids.add(annotation['id'])
        if not annotation.get('visual_review') or not annotation.get('restriction'):
            raise ValueError('Semantic review and use restriction are required')
        frame = by_id[annotation['scene']]
        im, _, _ = loader(frame)
        valid = valid_pixels(im.size, frame['analysis_region'], frame['analysis_exclusions'])
        x, y, w, h = annotation['rect']
        states = trace(im, annotation)
        if not valid[y:y+h, x:x+w].all():
            raise ValueError('Annotation overlaps an excluded or invalid source pixel')
        runs = rle_encode(states)
        assert np.array_equal(states, rle_decode(runs, (h, w)))
        counts = np.bincount(states.ravel(), minlength=3)
        crop = im.crop((x, y, x+w, y+h))
        record = dict(annotation)
        record.update({
            'source_sha256': frame['sha256'], 'source_pixel_sha256': pixel_hash(im),
            'crop_pixel_sha256': pixel_hash(crop), 'source_dimensions': list(im.size),
            'reference_asset': frame.get('reference_asset'),
            'valid_frame_pixels': int(valid.sum()), 'region_pixels': w*h,
            'core_trace_pixels': int(counts[1]), 'threshold_band_pixels': int(counts[2]),
            'untraced_pixels': int(counts[0]),
            'core_trace_share_of_region': float(counts[1]/(w*h)),
            'lower_threshold_trace_share_of_region': float((counts[1]+counts[2])/(w*h)),
            'full_frame_semantic_share': None,
            'review_status': 'region context and trace overlay visually reviewed by model; not ground truth',
            'mask_encoding': 'row-major state-length RLE',
            'mask_states': {'0': 'untraced, NOT confirmed absent', '1': 'high-threshold trace',
                            '2': 'low-to-high threshold band, NOT a statistical confidence interval'},
            'mask_sha256': hashlib.sha256(states.tobytes()).hexdigest(), 'mask_rle': runs,
        })
        records.append(record)
    return {'schema_version': 1, 'full_library_semantic_occupancy_complete': False,
            'full_frames_annotated': 0, 'pilot_frame_count': len({r['scene'] for r in records}),
            'pilot_region_count': len(records),
            'warning': 'Exact counts of stored candidate traces are not exact semantic occupancy. '
                       'Do not extrapolate region ratios or treat untraced pixels as negatives.',
            'source_review_sha256': hashlib.sha256(json.dumps(reviews, sort_keys=True).encode()).hexdigest(),
            'regions': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reviews = json.loads((ROOT/'data/semantic-region-review.json').read_text())
    library = json.loads((ROOT/'data/film-library.json').read_text())
    result = build(library, reviews)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'))+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'regions'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
