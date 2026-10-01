"""Independently reopen every source and recompute measurement invariants."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from skimage.color import rgb2lab
from film_color import color_distribution, sample, save_json, sha256, srgb_image
from reference_sources import archive_index, load_reference


def verify(catalog, output):
    doc=json.loads(catalog.read_text())
    frames=doc['frames']
    assert [f['scene'] for f in frames]==list(range(1,len(frames)+1))
    assert len({f['sha256'] for f in frames})==len(frames)
    total=0
    images=0
    registry=archive_index()
    for i,f in enumerate(frames,1):
        im,_,_=load_reference(f,registry=registry)
        assert list(im.size)==f['dimensions']
        assert all(f['review'].get(k) for k in ['scene_type','lighting','materials','observation'])
        rgb,xy=sample(im,f['analysis_region'],f['analysis_exclusions'],f['sample_step'])
        assert len(rgb)==f['sampled_pixels']
        labs=rgb2lab(rgb.astype(float)/255)
        hist=np.histogram(np.clip(labs[:,0],0,100),bins=np.linspace(0,100,101))[0]
        assert hist.tolist()==f['L_histogram_100']
        for c in range(3):
            assert np.bincount(rgb[:,c],minlength=256).tolist()==f['RGB_histograms_256'][c]
        assert color_distribution(labs,xy,im.size)==f['color_distribution']
        assert sum(f['tone_band_counts'])==len(rgb)
        assert len(f['palette'])==32 and sum(s['count'] for s in f['palette'])==len(rgb)
        assert abs(sum(s['share'] for s in f['palette'])-1)<1e-6
        for s in f['palette']:
            assert list(im.getpixel(tuple(s['xy'])))==s['rgb']
            assert np.allclose(rgb2lab(np.array(s['rgb'],dtype=float).reshape(1,3)/255)[0],s['lab'],atol=1e-6)
            assert s['hex']=='#'+''.join(f'{v:02X}' for v in s['rgb'])
        for key in ['chart','palette_card','relation_chart','preview']:
            if doc.get('storage_profile') == 'slim-with-external-evidence':
                continue
            with Image.open(output/f[key]) as generated:
                generated.load()
                assert generated.width>100 and generated.height>100
                assert np.asarray(generated.convert('RGB')).std()>3
                images+=1
        total+=len(f['palette'])
        if i%100==0:
            print(f'Independent verification {i}/{len(frames)}',flush=True)
    record={'status':'passed','frames':len(frames),'source_hashes_verified':len(frames),
            'unique_sources':len(frames),'palettes_verified':len(frames),'swatch_pixels_verified':total,
            'histogram_arrays_recomputed':4*len(frames),'color_position_tables_recomputed':len(frames),
            'derived_images_decoded_nonblank':images,'catalog_sha256':sha256(catalog),
            'boundary':'Numerical/file validation; semantic pixel material review remains a per-photo requirement.'}
    save_json(output/'data-verification.json',record)
    print(json.dumps(record))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--catalog',type=Path,default=Path(__file__).parents[1]/'data/film-library.json')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    verify(args.catalog,args.output)
