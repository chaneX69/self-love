"""Reproducible native candidate traces and review sheets for semantic annotations.

No trace is promoted to a semantic mask by this program. The operator must inspect
the source/overlay, and exact whole-frame semantic occupancy remains unavailable.
"""
import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from reference_sources import load_reference
from texture_features import pixel_hash
from trace_semantic_regions import CLASSES, rle_decode, rle_encode, valid_pixels

STATUSES = {'present', 'uncertain', 'not_observed'}
OVERLAY_STATUSES = {'not_yet_reviewed', 'accepted_candidate', 'ambiguous_candidate', 'rejected_candidate'}
MASK_WARNING = 'Stored candidate traces, NOT ground truth or exact semantic occupancy. Zero means untraced, not absent.'


def check_review(review, frame):
    sid = int(frame['scene'])
    if review.get('scene') != sid:
        raise ValueError('Frame identity mismatch')
    if set(review.get('classes', {})) != set(CLASSES):
        raise ValueError(f'{sid}: all four semantic classes required')
    if review.get('native_full_frame_reviewed') is not True:
        raise ValueError(f'{sid}: full native scene category review not complete')
    evidence = review.get('evidence_viewed', [])
    expected = {f'{sid:03d}-overview.jpg'} | {f'{sid:03d}-native-{i}.png' for i in range((frame['dimensions'][0]+959)//960)}
    if not expected.issubset({Path(p).name for p in evidence}):
        raise ValueError(f'{sid}: incomplete declared viewed evidence')
    # This validates the declaration, not that a tool was actually used to see it.
    present = set()
    for cls, item in review['classes'].items():
        if item.get('status') not in STATUSES or not item.get('basis', '').strip():
            raise ValueError(f'{sid}: unsupported status or missing visual evidence')
        if item['status'] == 'present':
            present.add(cls)
    ids = []
    for annotation in review.get('regions', []):
        cls = annotation.get('class')
        if cls not in CLASSES or cls not in present:
            raise ValueError(f'{sid}: region without a present class')
        rect = annotation.get('rect', [])
        if len(rect) != 4 or any(type(v) is not int for v in rect):
            raise ValueError(f'{sid}: four native integer coordinates required')
        x, y, w, h = rect
        iw, ih = frame['dimensions']
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > iw or y+h > ih:
            raise ValueError(f'{sid}: region outside original pixels: {rect}')
        if not annotation.get('visual_review') or not annotation.get('restriction'):
            raise ValueError(f'{sid}: missing semantic justification/restriction')
        overlay = annotation.get('overlay_review', {'status': 'not_yet_reviewed'})
        if overlay.get('status') not in OVERLAY_STATUSES:
            raise ValueError(f'{sid}: invalid overlay review status')
        if overlay['status'] != 'not_yet_reviewed' and not overlay.get('basis', '').strip():
            raise ValueError(f'{sid}: overlay review needs a visual basis')
        if not 0 <= annotation['low'] < annotation['high']:
            raise ValueError(f'{sid}: invalid trace thresholds')
        if annotation['mode'] not in ('light', 'dark', 'chroma-range'):
            raise ValueError(f'{sid}: unsupported trace mode')
        if annotation['mode'] == 'chroma-range' and cls != 'color_misregistration':
            raise ValueError(f'{sid}: color-range tracing requires offset semantics')
        if annotation['mode'] != 'chroma-range' and not 0 < annotation['sigma'] <= 20:
            raise ValueError(f'{sid}: invalid smoothing scale')
        ids.append(annotation['id'])
    if len(ids) != len(set(ids)):
        raise ValueError(f'{sid}: duplicate region ids')
    if present - {r['class'] for r in review.get('regions', [])}:
        raise ValueError(f'{sid}: positive class without native evidence rectangle')
    if review.get('full_frame_pixel_annotation_complete') is not False:
        raise ValueError(f'{sid}: candidate format cannot certify exact full-frame pixels')


def get_score(rgb, annotation, cache):
    mode = annotation['mode']
    key = (mode, float(annotation['sigma']))
    if key not in cache:
        if mode == 'chroma-range':
            cache[key] = rgb.max(axis=2) - rgb.min(axis=2)
        else:
            gray = cache.setdefault('gray', rgb @ np.array([.2126, .7152, .0722], dtype=np.float32))
            score = gaussian_filter(gray, annotation['sigma']) - gray
            cache[key] = -score if mode == 'light' else score
    return cache[key]


def trace_native(im, annotation, valid, cache, rgb):
    x, y, w, h = annotation['rect']
    score = get_score(rgb, annotation, cache)[y:y+h, x:x+w]
    eligible = valid[y:y+h, x:x+w]
    states = np.zeros((h, w), dtype=np.uint8)
    states[(score >= annotation['low']) & eligible] = 2
    states[(score >= annotation['high']) & eligible] = 1
    return states, eligible


def review_sheet(im, annotation, states, output):
    x, y, w, h = annotation['rect']
    crop = im.crop((x, y, x+w, y+h)).convert('RGB')
    rgb = np.asarray(crop)
    colors = np.zeros_like(rgb)
    colors[states == 1] = [0, 200, 125]
    colors[states == 2] = [255, 208, 30]
    overlay = rgb.copy()
    marked = states > 0
    overlay[marked] = (.45 * rgb[marked] + .55 * colors[marked]).astype(np.uint8)
    tile_w = max(w, 250)
    sheet = Image.new('RGB', (3*tile_w + 24, h+84), '#e8e8e8')
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), f"{annotation['id']} | native xywh {x},{y},{w},{h}", fill='black')
    draw.text((8, 28), 'CANDIDATE ONLY | green=high threshold, yellow=threshold band, black=untraced NOT absent', fill='black')
    for j, (panel, label) in enumerate([(crop, 'Original 1:1'), (Image.fromarray(colors), 'Stored trace'), (Image.fromarray(overlay), 'Overlay 1:1')]):
        left = 8+j*tile_w
        draw.text((left, 51), label, fill='black')
        sheet.paste(panel, (left, 76))
    sheet.save(output)


def process_frame(review, frame, output, make_sheets=True):
    check_review(review, frame)
    im, status, _ = load_reference(frame)
    rgb = np.asarray(im.convert('RGB'), dtype=np.float32)
    valid = valid_pixels(im.size, frame['analysis_region'], frame.get('analysis_exclusions', []))
    roi_pixels = int(valid.sum())
    cache, traces = {}, []
    # Union counts avoid double-counting overlapping evidence rectangles.
    unions = {cls: {key: np.zeros(valid.shape, bool) for key in
                   ('region', 'core', 'trace', 'accepted_region', 'accepted_core', 'accepted_trace')}
              for cls in CLASSES}
    for annotation in review.get('regions', []):
        states, eligible = trace_native(im, annotation, valid, cache, rgb)
        x, y, w, h = annotation['rect']
        if not eligible.any():
            raise ValueError(f"{annotation['id']}: no eligible analysis pixels")
        runs = rle_encode(states)
        if not np.array_equal(states, rle_decode(runs, states.shape)):
            raise AssertionError('Lossless trace encoding failed')
        cls = annotation['class']
        unions[cls]['region'][y:y+h, x:x+w] |= eligible
        unions[cls]['core'][y:y+h, x:x+w] |= states == 1
        unions[cls]['trace'][y:y+h, x:x+w] |= states > 0
        if annotation.get('overlay_review', {}).get('status') == 'accepted_candidate':
            unions[cls]['accepted_region'][y:y+h, x:x+w] |= eligible
            unions[cls]['accepted_core'][y:y+h, x:x+w] |= states == 1
            unions[cls]['accepted_trace'][y:y+h, x:x+w] |= states > 0
        core, band = int((states == 1).sum()), int((states == 2).sum())
        record = dict(annotation)
        record.update({'scene': frame['scene'], 'source_sha256': frame['sha256'],
                       'source_pixel_sha256': pixel_hash(im), 'crop_pixel_sha256': pixel_hash(im.crop((x,y,x+w,y+h))),
                       'analysis_roi_pixels': roi_pixels, 'eligible_region_pixels': int(eligible.sum()),
                       'excluded_region_pixels': int(w*h-eligible.sum()),
                       'core_candidate_pixels': core, 'threshold_band_pixels': band,
                       'untraced_region_pixels': int(eligible.sum())-core-band,
                       'full_frame_semantic_share': None,
                       'overlay_review': annotation.get('overlay_review', {'status': 'not_yet_reviewed'}),
                       'mask_encoding': 'row-major state-length RLE; 0=untraced; 1=core candidate; 2=threshold band',
                       'mask_sha256': hashlib.sha256(states.tobytes()).hexdigest(), 'mask_rle': runs})
        traces.append(record)
        if make_sheets:
            review_sheet(im, annotation, states, output / f"{annotation['id']}.png")
    counts = {}
    for cls, masks in unions.items():
        region, core, all_trace = (int(masks[key].sum()) for key in ('region','core','trace'))
        accepted_region, accepted_core, accepted_trace = (
            int(masks[key].sum()) for key in ('accepted_region', 'accepted_core', 'accepted_trace'))
        counts[cls] = {'review_status': review['classes'][cls]['status'], 'region_union_pixels': region,
                       'core_candidate_union_pixels': core, 'threshold_band_only_union_pixels': all_trace-core,
                       'untraced_inside_region_union_pixels': region-all_trace,
                       'outside_reviewed_region_union_pixels': roi_pixels-region,
                       'candidate_share_of_analysis_roi': core/roi_pixels,
                       'accepted_candidate_region_union_pixels': accepted_region,
                       'accepted_candidate_core_union_pixels': accepted_core,
                       'accepted_candidate_band_only_union_pixels': accepted_trace-accepted_core,
                       'accepted_candidate_share_of_analysis_roi': accepted_core/roi_pixels,
                       'semantic_share_of_analysis_roi': None, 'full_frame_semantic_share': None}
    result = {'scene': frame['scene'], 'source_sha256': frame['sha256'],
              'source_pixel_sha256': pixel_hash(im), 'dimensions': list(im.size), 'color_management': status,
              'analysis_region': frame['analysis_region'], 'analysis_exclusions': frame.get('analysis_exclusions', []),
              'analysis_roi_pixels': roi_pixels,
              'denominator_warning': 'Existing conservative analysis ROI, NOT all movie-content pixels. Whole-frame semantic occupancy is not computed.',
              'native_frame_category_reviewed': True, 'full_frame_pixel_annotation_complete': False,
              'classes': counts, 'region_count': len(traces),
              'overlay_review_counts': dict(Counter(r['overlay_review']['status'] for r in traces))}
    return result, traces


def run(reviews_path, output, make_sheets=True, scenes=None):
    content = reviews_path.read_text()
    reviews = ([json.loads(line) for line in content.splitlines() if line.strip()]
               if reviews_path.suffix == '.jsonl' else json.loads(content))
    if isinstance(reviews, dict):
        reviews = reviews['frames']
    by_id = {int(f['scene']): f for f in json.loads((ROOT/'data/film-library.json').read_text())['frames']}
    ids = [r['scene'] for r in reviews]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate frame ids')
    if scenes is not None:
        if set(scenes) - set(ids):
            raise ValueError('Requested frame has no review')
        reviews = [r for r in reviews if r['scene'] in scenes]
    output.mkdir(parents=True, exist_ok=True)
    summaries, traces = [], []
    for review in sorted(reviews, key=lambda r:r['scene']):
        summary, records = process_frame(review, by_id[review['scene']], output, make_sheets)
        summaries.append(summary)
        traces.extend(records)
        print(f"traced {review['scene']:03d} regions={len(records)}", flush=True)
    (output/'counts.json').write_text(json.dumps({'warning': MASK_WARNING, 'frames': summaries}, ensure_ascii=False, indent=2)+'\n')
    data = ''.join(json.dumps(r, ensure_ascii=False, separators=(',',':'))+'\n' for r in traces).encode()
    (output/'candidate-traces.jsonl.gz').write_bytes(gzip.compress(data, mtime=0))
    report = {'frame_category_reviews': len(reviews), 'region_proposals': len(traces),
              'schema_version': 2,
              'true_full_frame_semantic_counts_complete': 0,
              'overlay_review_counts': dict(Counter(r['overlay_review']['status'] for r in traces)),
              'class_statuses': {c:dict(Counter(r['classes'][c]['status'] for r in reviews)) for c in CLASSES},
              'mask_file_sha256': hashlib.sha256((output/'candidate-traces.jsonl.gz').read_bytes()).hexdigest(),
              'warning': MASK_WARNING}
    (output/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--no-sheets', action='store_true')
    parser.add_argument('--scene', type=int, action='append', help='Inspect only these frame IDs.')
    args = parser.parse_args()
    run(args.reviews, args.out, not args.no_sheets, args.scene)
