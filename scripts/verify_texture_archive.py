"""Verify archived candidate masks without claiming semantic ground truth.

Use --check-sources to recompute accepted local traces from full originals or
verified native crops with filter context. Crops never prove full-frame truth.
"""
import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from reference_sources import archive_index, load_reference
from texture_features import pixel_hash
from trace_semantic_regions import CLASSES, rle_decode, valid_pixels
from film_crops import crop_manifest, load_crop


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as file:
        return [json.loads(line) for line in file if line.strip()]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def recompute(im, record, valid, cache):
    key = (record['mode'], float(record['sigma']))
    if key not in cache:
        rgb = cache.setdefault('rgb', np.asarray(im.convert('RGB'), dtype=np.float32))
        if key[0] == 'chroma-range':
            score = rgb.max(axis=2)-rgb.min(axis=2)
        else:
            gray = cache.setdefault('gray', rgb @ np.array([.2126,.7152,.0722], dtype=np.float32))
            score = gaussian_filter(gray, record['sigma'])-gray
            if key[0] == 'light':
                score = -score
        cache[key] = score
    x,y,w,h = record['rect']
    score = cache[key][y:y+h,x:x+w]
    eligible = valid[y:y+h,x:x+w]
    states = np.zeros((h,w),np.uint8)
    states[(score>=record['low']) & eligible] = 2
    states[(score>=record['high']) & eligible] = 1
    return states


def verify(root, check_sources=False, data=None):
    data = data or root/'data'
    library = json.loads((root/'data/film-library.json').read_text())
    frames = {f['scene']:f for f in library['frames']}
    reviews = rows(data/'semantic-texture-reviews.jsonl')
    counts = rows(data/'semantic-texture-counts.jsonl')
    candidates = rows(data/'semantic-texture-candidates.jsonl.gz')
    summary = json.loads((data/'semantic-texture-summary.json').read_text())
    evidence = rows(data/'semantic-view-evidence.jsonl')
    ids = sorted(frames)
    check([r['scene'] for r in reviews] == ids, 'Review coverage/order mismatch')
    check([r['scene'] for r in counts] == ids, 'Count coverage/order mismatch')
    check(summary['category_review_complete'] is True, 'Category review incomplete')
    check(summary['full_frame_semantic_occupancy_complete'] is False, 'Unexpected ground-truth claim')
    check(summary['full_frames_pixel_annotated'] == 0, 'Unexpected full-frame pixel claim')
    check(summary['source_count'] == summary['native_frame_category_reviews'] == len(ids), 'Summary review count mismatch')
    check(summary['candidate_ink_counts_are_ground_truth'] is False, 'False candidate truth claim')
    check(summary['status_not_observed_means_zero_pixels'] is False, 'False absence claim')
    evidence_by_frame = defaultdict(dict)
    for item in evidence:
        check(item['scene'] in frames, 'Evidence for unknown frame')
        check(item['file'] not in evidence_by_frame[item['scene']], 'Duplicate view evidence')
        check(len(item['sha256']) == 64 and item['bytes'] > 0, 'Invalid view receipt')
        evidence_by_frame[item['scene']][item['file']] = item
    by_frame = defaultdict(list)
    for record in candidates:
        check(record['scene'] in frames, 'Mask for unknown frame')
        check(record['overlay_review']['status'] == 'accepted_candidate', 'Rejected trace in usable mask archive')
        by_frame[record['scene']].append(record)
    check(len({r['id'] for r in candidates}) == len(candidates), 'Duplicate trace IDs')
    source_checks = 0
    crop_checks = 0
    full_trace_checks = 0
    native_crops = {r['id']:r for r in crop_manifest(root, library['frames']).values()} if check_sources else {}
    registry = archive_index() if check_sources else None
    totals = Counter()
    overlay_totals = Counter()
    for review, stored_counts in zip(reviews, counts):
        sid = review['scene']
        frame = frames[sid]
        for key, value in [('source_sha256',frame['sha256']), ('source_pixel_sha256',frame['pixel_sha256'])]:
            check(review[key] == stored_counts[key] == value, f'{sid}: source identity mismatch')
        check(review['native_full_frame_reviewed'] is True, f'{sid}: native category review incomplete')
        check(review['full_frame_pixel_annotation_complete'] is False, f'{sid}: false pixel completion')
        check(stored_counts['full_frame_pixel_annotation_complete'] is False, f'{sid}: false count completion')
        check(review['dimensions'] == stored_counts['dimensions'] == frame['dimensions'], f'{sid}: stale dimensions')
        expected_views = {f'{sid:03d}-overview.jpg'} | {
            f'{sid:03d}-native-{i}.png' for i in range((frame['dimensions'][0]+959)//960)}
        check(expected_views <= set(review['evidence_viewed']), f'{sid}: missing declared native view')
        check(set(review['evidence_viewed']) == set(evidence_by_frame[sid]), f'{sid}: view receipt mismatch')
        check(set(review['classes']) == set(CLASSES), f'{sid}: incomplete classes')
        for cls in CLASSES:
            check(review['classes'][cls]['status'] in ('present','uncertain','not_observed'), f'{sid}: invalid visual status')
            check(bool(review['classes'][cls]['basis']), f'{sid}: missing judgment basis')
        valid = valid_pixels(tuple(frame['dimensions']),frame['analysis_region'],frame.get('analysis_exclusions',[]))
        roi = int(valid.sum())
        check(roi == stored_counts['analysis_roi_pixels'], f'{sid}: wrong ROI denominator')
        check(stored_counts['analysis_region'] == frame['analysis_region'], f'{sid}: stale ROI bounds')
        check(stored_counts['analysis_exclusions'] == frame.get('analysis_exclusions',[]), f'{sid}: stale exclusions')
        if check_sources:
            try:
                im,_,_ = load_reference(frame, root=root, registry=registry)
            except FileNotFoundError:
                im = None
            if im is not None:
                check(pixel_hash(im) == frame['pixel_sha256'], f'{sid}: source pixels changed')
                source_checks += 1
        cache = {}
        unions = {cls:{key:np.zeros(valid.shape,bool) for key in ('region','core','trace')} for cls in CLASSES}
        annotation_by_id = {r['id']:r for r in review.get('regions',[])}
        check(len(annotation_by_id) == len(review.get('regions',[])), f'{sid}: duplicate annotation IDs')
        statuses = Counter(r['overlay_review']['status'] for r in annotation_by_id.values())
        check(set(statuses) <= {'accepted_candidate','ambiguous_candidate','rejected_candidate'}, f'{sid}: overlay review incomplete')
        check(dict(statuses) == stored_counts['overlay_review_counts'], f'{sid}: overlay counts mismatch')
        overlay_totals.update(statuses)
        check(set(review['accepted_candidate_ids']) == {r['id'] for r in by_frame[sid]}, f'{sid}: usable ID mismatch')
        check(set(review['accepted_candidate_ids']) == {k for k,r in annotation_by_id.items()
              if r['overlay_review']['status'] == 'accepted_candidate'}, f'{sid}: accepted masks omitted')
        for record in by_frame[sid]:
            annotation = annotation_by_id[record['id']]
            for key in ('class','rect','mode','sigma','low','high','overlay_review'):
                check(record[key] == annotation[key], f'{sid}: stale annotation {key}')
            check(record['source_sha256'] == frame['sha256'], f'{sid}: trace source mismatch')
            check(record['source_pixel_sha256'] == frame['pixel_sha256'], f'{sid}: trace pixel identity mismatch')
            x,y,w,h = record['rect']
            iw,ih = frame['dimensions']
            check(min(x,y)>=0 and min(w,h)>0 and x+w<=iw and y+h<=ih,f'{sid}: invalid native rectangle')
            states = rle_decode(record['mask_rle'],(h,w))
            check(hashlib.sha256(states.tobytes()).hexdigest() == record['mask_sha256'],f'{sid}: mask hash mismatch')
            eligible = valid[y:y+h,x:x+w]
            check(not (states[~eligible] != 0).any(),f'{sid}: excluded pixels in mask')
            check(int((states==1).sum()) == record['core_candidate_pixels'],f'{sid}: core mismatch')
            check(int((states==2).sum()) == record['threshold_band_pixels'],f'{sid}: band mismatch')
            check(int(eligible.sum()) == record['eligible_region_pixels'],f'{sid}: eligibility mismatch')
            check(record['analysis_roi_pixels'] == roi,f'{sid}: trace denominator mismatch')
            check(record['full_frame_semantic_share'] is None,f'{sid}: false semantic percentage')
            if check_sources:
                if im is not None:
                    check(pixel_hash(im.crop((x,y,x+w,y+h))) == record['crop_pixel_sha256'],f'{sid}: crop identity mismatch')
                    actual = recompute(im,record,valid,cache)
                    full_trace_checks += 1
                else:
                    check(record['id'] in native_crops, f'{sid}: native texture evidence unavailable')
                    crop = native_crops[record['id']]
                    check('storage_rect' in crop, f'{sid}: missing native filter context')
                    sx,sy,sw,sh = crop['storage_rect']
                    margin = int(np.ceil(4*record['sigma']))+1
                    check(sx <= max(0,x-margin) and sy <= max(0,y-margin) and
                          sx+sw >= min(iw,x+w+margin) and sy+sh >= min(ih,y+h+margin),
                          f'{sid}: insufficient native filter context')
                    with load_crop(root,crop,context=True) as context:
                        local = dict(record,rect=[x-sx,y-sy,w,h])
                        actual = recompute(context,local,valid[sy:sy+sh,sx:sx+sw],{})
                    crop_checks += 1
                check(np.array_equal(states,actual),f'{sid}: recomputation differs')
            masks = unions[record['class']]
            masks['region'][y:y+h,x:x+w] |= eligible
            masks['core'][y:y+h,x:x+w] |= states==1
            masks['trace'][y:y+h,x:x+w] |= states>0
        for cls, masks in unions.items():
            region,core,all_trace = (int(masks[k].sum()) for k in ('region','core','trace'))
            expected = {'accepted_candidate_region_union_pixels':region,
                        'accepted_candidate_core_union_pixels':core,
                        'accepted_candidate_band_only_union_pixels':all_trace-core,
                        'untraced_inside_accepted_region_pixels':region-all_trace,
                        'outside_accepted_region_pixels':roi-region}
            row = stored_counts['classes'][cls]
            check(row['visual_status'] == review['classes'][cls]['status'], f'{sid}: stale visual status')
            check(all(row[k] == v for k,v in expected.items()),f'{sid}/{cls}: union counts differ')
            check(abs(row['candidate_core_share_of_analysis_roi']-core/roi)<1e-12,f'{sid}: candidate share mismatch')
            expected_shares = {'candidate_region_coverage_of_analysis_roi':region/roi,
                'candidate_core_share_of_accepted_regions':core/region if region else None,
                'candidate_trace_share_of_accepted_regions':all_trace/region if region else None}
            for key,value in expected_shares.items():
                check(row[key] == value, f'{sid}: local candidate share mismatch')
            check(row['semantic_share_of_analysis_roi'] is None and row['full_frame_semantic_share'] is None,
                  f'{sid}: semantic unknown must remain null')
            totals[cls] += core
        if sid % 100 == 0:
            print(f'verified {sid}/{len(frames)}',flush=True)
        if check_sources and im is not None:
            im.close()
    check(dict(totals) == summary['accepted_candidate_core_pixels_by_class'],'Corpus counts mismatch')
    check(dict(overlay_totals) == summary['region_overlay_reviews'], 'Corpus overlay count mismatch')
    check(summary['accepted_candidate_regions'] == len(candidates), 'Accepted region count mismatch')
    check(summary['accepted_candidate_frames'] == len({r['scene'] for r in candidates}), 'Accepted frame count mismatch')
    check(summary['total_analysis_roi_pixels'] == sum(r['analysis_roi_pixels'] for r in counts), 'Corpus denominator mismatch')
    for cls in CLASSES:
        check(dict(Counter(r['classes'][cls]['status'] for r in reviews)) == summary['class_statuses'][cls],
              f'{cls}: summary visual statuses mismatch')
    result = {'status':'passed', 'frame_category_records':len(reviews), 'accepted_local_masks':len(candidates),
              'original_sources_checked':source_checks, 'source_recompute_requested':check_sources,
              'local_traces_recomputed_from_full_frames':full_trace_checks,
              'local_traces_recomputed_from_native_crops':crop_checks,
              'full_frame_semantic_occupancy_complete':False,
              'scope':'Identity, counts, RLE and optional source recomputation; not semantic truth or user approval.'}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root',type=Path,default=ROOT)
    parser.add_argument('--check-sources',action='store_true')
    parser.add_argument('--data-dir',type=Path,help='Verify a staged dataset before installation.')
    parser.add_argument('--report',type=Path)
    args = parser.parse_args()
    result = verify(args.skill_root,args.check_sources,args.data_dir)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
