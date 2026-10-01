"""Measured screenshot colors, not a photo filter or semantic segmenter."""
from pathlib import Path
import hashlib
import io
import json
import numpy as np
from PIL import Image, ImageCms, ImageOps
from skimage.color import rgb2lab, deltaE_ciede2000

TONE_NAMES = ['deep-shadow', 'shadow', 'midtone', 'light', 'highlight']


def color_distribution(lab, xy, dimensions):
    """Lab hue/lightness counts and spatial statistics, not object segmentation."""
    chroma = np.linalg.norm(lab[:, 1:3], axis=1)
    angle = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    hue = np.where(chroma < 8, 12, np.minimum(11, (angle/30).astype(int)))
    tone = np.minimum(4, (np.clip(lab[:, 0], 0, 100)/20).astype(int))
    joint = np.zeros((13, 5), dtype=int)
    np.add.at(joint, (hue, tone), 1)
    grid = np.minimum(2, xy[:, 1]*3//dimensions[1])*3 + np.minimum(2, xy[:, 0]*3//dimensions[0])
    cells = []
    for i in range(9):
        selected = lab[grid == i]
        cells.append({'row': i//3, 'column': i%3, 'sample_count': len(selected),
                      'L5_L50_L95': np.percentile(selected[:, 0], [5, 50, 95]).round(5).tolist() if len(selected) else None,
                      'mean_Lab': selected.mean(axis=0).round(5).tolist() if len(selected) else None,
                      'hue_counts': np.bincount(hue[grid == i], minlength=13).tolist()})
    return {'hue_definition': 'CIELAB atan2(b*,a*), 12 equal 30-degree bins; C*<8 separate neutral bin',
            'neutral_chroma_threshold': 8, 'hue_labels': [f'h{i*30:03d}-{(i+1)*30:03d}' for i in range(12)]+['neutral'],
            'tone_labels': TONE_NAMES, 'hue_by_tone_counts': joint.tolist(),
            'spatial_grid_3x3': cells, 'boundary': 'Numerical group area, not physical pigment, object area, or semantic masks'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def srgb_image(path):
    with Image.open(path) as original:
        im = ImageOps.exif_transpose(original)
        icc = im.info.get('icc_profile')
        if icc:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            status = 'ICC converted to sRGB: ' + ImageCms.getProfileName(profile).strip()
            im = ImageCms.profileToProfile(im, profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
        else:
            status = 'declared sRGB' if 'srgb' in im.info else 'assumed sRGB; source encoding unverified'
            im = im.convert('RGB')
        return im.copy(), status


def sample(im, rect=(.01, .02, .98, .94), exclusions=(), step=4):
    if not isinstance(step, int) or step < 1:
        raise ValueError('Sample step must be a positive integer')
    w, h = im.size
    left, top, right, bottom = rect
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError('Invalid normalized sample rectangle')
    yy, xx = np.mgrid[0:h:step, 0:w:step]
    mask = (xx >= left*w) & (xx < right*w) & (yy >= top*h) & (yy < bottom*h)
    for r in exclusions:
        a, b, c, d = r['rect']
        if not (0 <= a < c <= 1 and 0 <= b < d <= 1):
            raise ValueError('Invalid exclusion')
        mask &= ~((xx >= a*w) & (xx < c*w) & (yy >= b*h) & (yy < d*h))
    rgb = np.asarray(im)[::step, ::step][mask]
    xy = np.stack([xx[mask], yy[mask]], axis=1)
    if len(rgb) < 16:
        raise ValueError('Insufficient sampled pixels')
    return rgb, xy


def palette(rgb, xy, colors=32):
    """Median-cut clusters; snap each Lab centroid to a real member pixel."""
    quantized = Image.fromarray(rgb.reshape(1, -1, 3)).quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    cluster = np.asarray(quantized).ravel()
    lab = rgb2lab(rgb.astype(float)/255, illuminant='D65', observer='2')
    swatches = []
    for k in np.unique(cluster):
        indices = np.flatnonzero(cluster == k)
        points = lab[indices]
        chosen = indices[np.argmin(((points - points.mean(axis=0))**2).sum(axis=1))]
        swatches.append({
            'rgb': rgb[chosen].tolist(),
            'hex': '#' + ''.join(f'{v:02X}' for v in rgb[chosen]),
            'lab': lab[chosen].round(6).tolist(),
            'xy': xy[chosen].tolist(),
            'count': len(indices),
            'share': round(len(indices)/len(rgb), 8),
            'tone': TONE_NAMES[min(4, int(lab[chosen, 0]/20))],
            'material_binding': 'unverified-pixel; frame tags are not pixel segmentation',
        })
    swatches.sort(key=lambda s: (-s['count'], s['hex'], s['xy']))
    return swatches, lab


def rank(library, rgb, material, lighting, tone, enabled_gates=(), max_lightness_delta=12, top=12):
    """Compute distance to EVERY swatch first, then enforce eligibility."""
    if len(rgb) != 3 or any(not np.isfinite(v) or not 0 <= v <= 255 for v in rgb):
        raise ValueError('Query must be a finite sRGB triplet in 0..255')
    if tone not in TONE_NAMES or not np.isfinite(max_lightness_delta) or max_lightness_delta < 0:
        raise ValueError('Invalid tone role or lightness guardrail')
    if not isinstance(top, int) or top < 1:
        raise ValueError('Candidate limit must be positive')
    query = rgb2lab(np.array(rgb, dtype=float).reshape(1, 3)/255)[0]
    entries = [(f, s) for f in library['frames'] for s in f['palette']]
    labs = np.array([s['lab'] for _, s in entries])
    distances = deltaE_ciede2000(labs, np.broadcast_to(query, labs.shape))
    candidates = []
    rejections = {}
    compatible = 0
    for (frame, swatch), distance in zip(entries, distances):
        reasons = []
        if not frame['active']:
            reasons.append('archive')
        missing = set(frame['review']['gates']) - set(enabled_gates)
        if missing:
            reasons.append('gate:' + ','.join(sorted(missing)))
        if material not in frame['review']['materials']:
            reasons.append('frame-material')
        if lighting != frame['review']['lighting']:
            reasons.append('illumination')
        if swatch['tone'] != tone:
            reasons.append('tone-role')
        if abs(swatch['lab'][0] - query[0]) > max_lightness_delta:
            reasons.append('lightness-delta')
        if not reasons:
            compatible += 1
        for reason in reasons:
            rejections[reason] = rejections.get(reason, 0) + 1
        candidates.append({'scene': frame['scene'], 'swatch_id': swatch['id'],
                           'hex': swatch['hex'], 'lab': swatch['lab'], 'xy': swatch['xy'],
                           'delta_e_2000': float(distance), 'rejected_for': reasons,
                           'original': frame['original'], 'semantic_pixel_check_required': True})
    candidates.sort(key=lambda x: (x['delta_e_2000'], x['scene'], x['swatch_id']))
    return {'source_rgb': list(rgb), 'source_lab': query.tolist(),
            'library_frames_examined': len(library['frames']), 'swatches_compared': len(entries),
            'compatible_candidates': compatible, 'rejection_counts': rejections,
            'raw_nearest': candidates[:top],
            'compatible_nearest': [c for c in candidates if not c['rejected_for']][:top],
            'status': 'candidates-need-pixel-review' if compatible else 'no-compatible-candidate'}


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
