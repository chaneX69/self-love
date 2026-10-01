"""Verify a film-only skill directory without importing private photo artifacts."""
import argparse
import gzip
import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from PIL import Image, UnidentifiedImageError
from reference_sources import load_reference
from film_crops import crop_manifest, load_crop
from palette_evidence import palette_index, validate_palette_row, load_atlas

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.md', '.py', '.html', '.yaml', '.yml', '.txt', '.csv', '.tsv', '.json', '.jsonl'}
COMPRESSED_DATA = {'data/semantic-texture-candidates.jsonl.gz'}
PRIVATE_MARKERS = {
    'machine-user-path': re.compile(r'/(?:Users|home)/[^/\s<>]+|[A-Za-z]:[\\/]+Users[\\/]+'),
    'local-file-uri': re.compile(r'file:' + r'/{2,3}', re.IGNORECASE),
    'embedded-media': re.compile(r'data\s*:\s*(?:image|video|audio)/', re.IGNORECASE),
}
FORBIDDEN_PARTS = {'.git', '__pycache__', '.venv', 'outputs', 'inputs', 'work', 'backups'}


def require_private_workspace_paths(*paths, root=ROOT):
    """Check both lexical paths and resolved destinations, including other skill copies."""
    roots = {Path(root).absolute(), Path(root).resolve()}
    for value in paths:
        if value is None:
            continue
        path = Path(value).expanduser().absolute()
        for candidate in {path, path.resolve()}:
            if any(candidate == base or candidate.is_relative_to(base) for base in roots):
                raise ValueError('Private photo artifacts must remain outside skill directories')
            if any((parent/'SKILL.md').is_file() for parent in candidate.parents):
                raise ValueError('Private photo artifacts must remain outside skill directories')


def scan_text(stream, relative, issues):
    for line_number, line in enumerate(stream, 1):
        decoded = html.unescape(unquote(line)).replace('\\/', '/')
        for label, pattern in PRIVATE_MARKERS.items():
            if pattern.search(decoded):
                issues.append({'path': relative, 'line': line_number, 'reason': label})


def verify(root=ROOT, git_checkout=False):
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError('Skill root must not be a symbolic link for release inspection')
    entries = sorted(root.rglob('*'))
    if git_checkout and (root/'.git').exists():
        if (root/'.git').is_symlink():
            raise ValueError('Git metadata must not be a symbolic link')
        process = subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'],
                                 capture_output=True,text=True,check=True)
        if Path(process.stdout.strip()).resolve() != root.resolve():
            raise ValueError('Git checkout root mismatch')
        entries = [p for p in entries if p.relative_to(root).parts[0] != '.git']
    symlinks = [p for p in entries if p.is_symlink()]
    if symlinks:
        return {'status': 'failed', 'issues': [{'path': str(p.relative_to(root)),
                'reason': 'symbolic-link'} for p in symlinks]}
    library = json.loads((root/'data/film-library.json').read_text())
    selection = json.loads((root/'data/representatives.json').read_text())
    references = {}
    issues = []
    distribution_path = root/'data/distribution.json'
    distribution = json.loads(distribution_path.read_text()) if distribution_path.exists() else {}
    crop_only = distribution.get('edition') == 'crop-only'
    palette_assets = {}
    try:
        palettes = palette_index(root)
        frames_by_scene = {f['scene']: f for f in library['frames']}
        required = {f['scene'] for f in library['frames'] if not f.get('reference_asset')}
        if (palettes and not required <= set(palettes)) or (crop_only and set(palettes) != set(frames_by_scene)):
            raise ValueError('Palette evidence coverage incomplete')
        for sid, row in palettes.items():
            validate_palette_row(frames_by_scene[sid], row)
            palette_assets[row['asset']] = (frames_by_scene[sid], row)
    except (KeyError, ValueError, OSError, TypeError) as error:
        issues.append({'path': 'data/palette-crops.json', 'reason': 'invalid-palette-crop-manifest',
                       'error': str(error)})
    try:
        crops = crop_manifest(root, library['frames'])
    except (KeyError, ValueError, OSError, TypeError) as error:
        crops = {}
        issues.append({'path': 'data/film-crops.json', 'reason': 'invalid-film-crop-manifest',
                       'error': str(error)})
    for frame in library['frames']:
        asset = frame.get('reference_asset')
        if not asset:
            continue
        expected = f"assets/references/{frame['scene']:03d}.webp"
        if asset != expected or asset in references:
            issues.append({'path': str(asset), 'reason': 'invalid-film-asset-entry'})
            continue
        if frame.get('original') != 'evidence://sha256/' + frame['sha256']:
            issues.append({'path': asset, 'reason': 'nonportable-source-entry'})
        references[asset] = frame
    if crop_only and references:
        issues.append({'path': 'data/film-library.json', 'reason': 'full-frame-in-crop-only-edition'})
    selected = set(selection['selected'])
    if (selection['count'] != len(selected) or
            (crop_only and not selected <= {f['scene'] for f in library['frames']}) or
            (not crop_only and selected != {f['scene'] for f in references.values()})):
        issues.append({'path': 'data/representatives.json', 'reason': 'selection-mismatch'})
    checked = []
    checked_crops = []
    checked_palettes = []
    files = [p for p in entries if p.is_file()]
    for path in files:
        relative = path.relative_to(root).as_posix()
        if (set(path.relative_to(root).parts) & FORBIDDEN_PARTS or
                path.name in {'.DS_Store', 'archive-index.json'} or path.suffix == '.pyc'):
            issues.append({'path': relative, 'reason': 'private-or-runtime-artifact'})
            continue
        try:
            with Image.open(path) as im:
                metadata = {str(key).lower() for key in im.info}
                if metadata & {'exif', 'xmp', 'comment', 'description', 'xml:com.adobe.xmp'}:
                    issues.append({'path': relative, 'reason': 'unreviewed-image-metadata'})
                is_image = True
        except UnidentifiedImageError:
            is_image = False
        except (OSError, ValueError) as error:
            issues.append({'path': relative, 'reason': 'unreadable-media', 'error': type(error).__name__})
            continue
        if is_image:
            if relative in palette_assets:
                try:
                    frame, row = palette_assets[relative]
                    atlas = load_atlas(frame, row, root=root)
                    atlas.close()
                    checked_palettes.append(relative)
                except (ValueError, OSError) as error:
                    issues.append({'path': relative, 'reason': 'palette-crop-pixel-or-hash-mismatch',
                                   'error': str(error)})
                continue
            if relative in crops:
                try:
                    crop = load_crop(root, crops[relative])
                    crop.close()
                    checked_crops.append(relative)
                except (ValueError, OSError) as error:
                    issues.append({'path': relative, 'reason': 'film-crop-pixel-or-hash-mismatch',
                                   'error': str(error)})
                continue
            frame = references.get(relative)
            if frame is None:
                issues.append({'path': relative, 'reason': 'image-not-in-film-manifest'})
                continue
            try:
                # registry={} forbids silently substituting an external evidence file.
                im, _, actual = load_reference(frame, root=root, registry={})
                if actual != path.resolve():
                    raise ValueError('Wrong asset resolution')
                im.close()
                checked.append(relative)
            except (ValueError, OSError) as error:
                issues.append({'path': relative, 'reason': 'film-pixel-or-hash-mismatch',
                               'error': str(error)})
            continue
        if relative in references:
            issues.append({'path': relative, 'reason': 'film-asset-not-an-image'})
            continue
        if relative in COMPRESSED_DATA:
            try:
                with gzip.open(path, 'rt', encoding='utf-8') as stream:
                    for line_number, line in enumerate(stream, 1):
                        json.loads(line)
                        scan_text([line], f'{relative}:record-{line_number}', issues)
            except (ValueError, OSError) as error:
                issues.append({'path': relative, 'reason': 'invalid-compressed-jsonl',
                               'error': type(error).__name__})
        elif path.suffix in TEXT_SUFFIXES or path.name == '.gitignore':
            try:
                with path.open(encoding='utf-8') as stream:
                    scan_text(stream, relative, issues)
            except UnicodeDecodeError:
                issues.append({'path': relative, 'reason': 'unexpected-binary-payload'})
        else:
            issues.append({'path': relative, 'reason': 'unregistered-file-type'})
    for missing in set(references) - set(checked):
        if not any(i['path'] == missing for i in issues):
            issues.append({'path': missing, 'reason': 'missing-film-reference'})
    for missing in set(crops) - set(checked_crops):
        if not any(i['path'] == missing for i in issues):
            issues.append({'path': missing, 'reason': 'missing-film-crop'})
    for missing in set(palette_assets) - set(checked_palettes):
        if not any(i['path'] == missing for i in issues):
            issues.append({'path': missing, 'reason': 'missing-palette-crop'})
    return {'status': 'passed' if not issues else 'failed', 'files_checked': len(files),
            'movie_references_verified': len(checked), 'declared_movie_references': len(references),
            'movie_crops_verified': len(checked_crops), 'declared_movie_crops': len(crops),
            'palette_atlases_verified': len(checked_palettes), 'declared_palette_atlases': len(palette_assets),
            'issues': issues,
            'boundary': 'Manifest, full pixel hashes and common leak channels checked; '
                        'Git history is not inspected; provenance and third-party rights are separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--git-checkout', action='store_true',
                        help='Exclude verified Git checkout metadata only; still scan all working files.')
    args = parser.parse_args()
    if args.report:
        require_private_workspace_paths(args.report, root=args.skill_root)
    result = verify(args.skill_root,args.git_checkout)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
