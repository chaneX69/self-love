"""Render the offline film library for the selected evidence edition."""
import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path

from palette_evidence import palette_index

ROOT = Path(__file__).resolve().parents[1]


def render(root=ROOT):
    root = Path(root)
    frames = copy.deepcopy(json.loads((root/'data/film-library.json').read_text())['frames'])
    selected = set(json.loads((root/'data/representatives.json').read_text())['selected'])
    edition = json.loads((root/'data/distribution.json').read_text())['edition']
    palettes = palette_index(root) if edition == 'crop-only' else {}
    grouped = defaultdict(list)
    manifest = root/'data/film-crops.json'
    if manifest.exists():
        for crop in json.loads(manifest.read_text())['crops']:
            grouped[crop['scene']].append({k:crop[k] for k in ('id','class','asset','rect','storage_rect')})
    for frame in frames:
        sid = frame['scene']
        frame['is_representative'] = sid in selected
        frame['display_asset'] = palettes[sid]['asset'] if sid in palettes else frame.get('reference_asset')
        frame['evidence_scope'] = 'native-crop' if sid in palettes else 'full-frame'
        frame['texture_crops'] = grouped[sid]
    encoded = json.dumps(frames,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    template = (root/'scripts/library_atlas.html').read_text()
    page = template.replace('__FRAMES__',encoded).replace('__EDITION__',json.dumps(edition))
    (root/'references/library.html').write_text(page)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root',type=Path,default=ROOT)
    render(parser.parse_args().skill_root)
