"""Read-only source analysis; measured candidates require human pixel review."""
import argparse
import html
import json
import re
from pathlib import Path
from film_color import palette, rank, sample, save_json, sha256, srgb_image
from reference_sources import archive_index, load_reference, source_path
from palette_evidence import evidence_info, palette_index, palette_pixel
from verify_reference_privacy import require_private_workspace_paths


def run(plan, library, catalog_hash, approvals=None, top=24):
    require_private_workspace_paths(plan['source'])
    source = Path(plan['source']).resolve()
    before = sha256(source)
    if plan.get('source_sha256') and plan['source_sha256'] != before:
        raise ValueError('Source hash changed')
    im, color_management = srgb_image(source)
    regions = plan['regions']
    if not regions or len({r['id'] for r in regions}) != len(regions):
        raise ValueError('Unique, nonempty source regions are required')
    approvals = approvals or {}
    if approvals and (approvals.get('source_sha256') != before or
                      approvals.get('catalog_sha256') != catalog_hash):
        raise ValueError('Pixel reviews belong to another source or catalog')
    decisions = approvals.get('decisions', {})
    records = []
    registry = archive_index()
    crop_index = palette_index()
    by_scene = {f['scene']:f for f in library['frames']}
    for region in regions:
        if not re.fullmatch(r'[a-z0-9-]+', region['id']):
            raise ValueError('Region id must use lowercase ASCII letters, digits, or hyphens')
        if not region.get('source_evidence'):
            raise ValueError('Describe observed source material and illumination')
        gates = region.get('enabled_gates', [])
        known = {g for f in library['frames'] for g in f['review']['gates']}
        if set(gates) - known or 'archive' in gates:
            raise ValueError('Unknown gate or attempt to enable archived frames')
        evidence = region.get('gate_evidence', {})
        if any(not evidence.get(g) for g in gates):
            raise ValueError('Every conditional gate needs current source/request evidence')
        if 'sense' in gates and not plan.get('spider_sense_explicit_current_request'):
            raise ValueError('Spider sense requires an explicit current request')
        if 'caption' in gates and not plan.get('caption_carrier_only'):
            raise ValueError('Caption reference eligibility does not authorize new text')
        rgb, xy = sample(im, region['rect'], region.get('exclusions', []), step=2)
        colors = region.get('colors', 3)
        if not isinstance(colors, int) or not 1 <= colors <= 12:
            raise ValueError('Use 1..12 representative colors per semantic region')
        anchors, _ = palette(rgb, xy, colors)
        for i, anchor in enumerate(anchors, 1):
            qid = f"{region['id']}-{i:02d}"
            result = rank(library, anchor['rgb'], region['material'], region['lighting'],
                          anchor['tone'], gates, region.get('max_lightness_delta', 12), top)
            for candidate in result['compatible_nearest'] + result['raw_nearest']:
                candidate.update(evidence_info(by_scene[candidate['scene']], candidate, crop_index, registry))
            record = {'query_id': qid, 'region': region, 'source_anchor': anchor,
                      'comparison': result, 'status': result['status']}
            decision = decisions.get(qid)
            if decision:
                candidates = result['compatible_nearest']
                matches = [c for c in candidates if c['swatch_id'] == decision.get('swatch_id')]
                if len(matches) != 1:
                    raise ValueError(f'{qid}: selected swatch is not eligible')
                selected = matches[0]
                preceding = candidates[:candidates.index(selected)]
                rejected = decision.get('rejected_closer_pixels', {})
                if any(not rejected.get(c['swatch_id']) for c in preceding):
                    raise ValueError(f'{qid}: explain every closer pixel rejection')
                if (decision.get('verified_material') != region['material'] or
                    decision.get('verified_tone') != anchor['tone'] or
                    decision.get('verified_lighting') != region['lighting'] or
                    not decision.get('pixel_review_evidence') or
                    not decision.get('coherence_review')):
                    raise ValueError(f'{qid}: incomplete pixel/material/light/coherence review')
                frame = next(f for f in library['frames'] if f['scene'] == selected['scene'])
                if selected.get('evidence_scope') == 'native-crop' and decision.get('crop_context_sufficient') is not True:
                    raise ValueError(f'{qid}: crop material/light context must be explicitly reviewed; insufficient context cannot be approved')
                actual = palette_pixel(frame, selected, crop_index, registry=registry)
                if '#' + ''.join(f'{v:02X}' for v in actual) != selected['hex']:
                    raise ValueError(f'{qid}: reference pixel no longer matches')
                record.update({'status': 'pixel-reviewed-color-anchor',
                               'selected': {**selected, 'semantic_pixel_check_required': False},
                               'review': decision})
            records.append(record)
    if set(decisions) - {r['query_id'] for r in records}:
        raise ValueError('Unknown approval query')
    # A region may not invert the source's lightness ordering after substitution.
    for rid in {r['region']['id'] for r in records}:
        accepted = sorted([r for r in records if r['region']['id'] == rid and 'selected' in r],
                          key=lambda r: r['source_anchor']['lab'][0])
        if any(a['selected']['lab'][0] > b['selected']['lab'][0]
               for a, b in zip(accepted, accepted[1:])):
            raise ValueError(f'{rid}: mapped lightness order inverted')
    if sha256(source) != before:
        raise ValueError('Source was modified during analysis')
    complete = all(r['status'] == 'pixel-reviewed-color-anchor' for r in records)
    return {'schema_version': 1, 'source': str(source), 'source_sha256': before,
            'catalog_sha256': catalog_hash, 'color_management': color_management,
            'status': 'color-mapping-reviewed' if complete else 'pending-pixel-review',
            'photo_modified': False, 'generation_authorized_by_this_report': False,
            'boundaries': ['Semantic attestations are manual, not automatic segmentation.',
                           'This is a color plan, not a finished redraw or user aesthetic approval.',
                           'Exact HEX reproduction is not guaranteed by an image generator.',
                           'Four print layers, identity, geometry, light and material remain separate gates.'],
            'queries': records}


def render(report):
    esc = html.escape
    sections = []
    for q in report['queries']:
        rows = []
        for c in q['comparison']['compatible_nearest']:
            evidence = (f'<a href="{html.escape(Path(c["evidence_path"]).as_uri(), quote=True)}">原像素证据</a>'
                        if c.get('evidence_path') else '证据未安装；不可批准')
            rows.append(f'<tr><td>{esc(c["swatch_id"])}</td><td style="background:{c["hex"]}">'
                        f'<span>{c["hex"]}</span></td><td>{c["delta_e_2000"]:.4f}</td>'
                        f'<td>{c["xy"]}</td><td>{evidence}<br>{esc(c.get("evidence_scope", ""))}'
                        f'<br>{esc(str(c.get("atlas_tile", "")))} {esc(str(c.get("atlas_sample_xy", "")))}</td></tr>')
        s = q['source_anchor']
        sections.append(f'<section><h2>{esc(q["query_id"])} · {s["hex"]}</h2>'
                        f'<p>状态：{esc(q["status"])}；已比较 {q["comparison"]["library_frames_examined"]} 帧 / '
                        f'{q["comparison"]["swatches_compared"]} 色；候选 {q["comparison"]["compatible_candidates"]}。</p>'
                        '<table><thead><tr><th>样本</th><th>色值</th><th>ΔE00</th><th>原帧坐标</th><th>证据</th>'
                        '</tr></thead><tbody>'+''.join(rows)+'</tbody></table></section>')
    return ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>原照与电影色卡匹配核对</title><style>body{font:15px/1.6 system-ui;max-width:1100px;margin:24px auto;'
            'padding:0 16px;color:#202325;background:#f5f6f7}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;'
            'padding:7px;text-align:left}td span{background:#fff;padding:2px;color:#000}section{margin-bottom:32px}'
            '@media(max-width:500px){body{font-size:12px;padding:0 8px}th,td{padding:3px}}</style>'
            f'<h1>原照与电影色卡匹配核对</h1><p>{esc(report["status"])}。仅分析与候选核对，不修改原照。'
            '同帧包含某材料不等于该颜色像素属于该材料，生成前须逐项核实。</p>'+''.join(sections))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).parents[1]/'data/film-library.json')
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--top', type=int, default=24)
    args = parser.parse_args(argv)
    require_private_workspace_paths(args.plan, args.reviews, args.output,
                                    args.output.with_suffix('.html'))
    plan = json.loads(args.plan.read_text())
    library = json.loads(args.catalog.read_text())
    protected = {Path(plan['source']).resolve(), args.plan.resolve(), args.catalog.resolve()}
    registry = archive_index()
    protected.update(p for f in library['frames'] if (p := source_path(f, required=False, registry=registry)))
    if args.reviews:
        protected.add(args.reviews.resolve())
    if args.output.resolve() in protected or args.output.with_suffix('.html').resolve() in protected:
        raise ValueError('Output would overwrite an input')
    reviews = json.loads(args.reviews.read_text()) if args.reviews else None
    report = run(plan, library, sha256(args.catalog), reviews, args.top)
    save_json(args.output, report)
    args.output.with_suffix('.html').write_text(render(report))
    print(json.dumps({'status': report['status'], 'queries': len(report['queries']),
                      'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
