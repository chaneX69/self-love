import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000
from film_color import color_distribution, palette, rank, sample, sha256
from match_photo_palette import run


class FilmColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = json.loads((Path(__file__).parents[1]/'data/film-library.json').read_text())

    def test_ciede2000_known_pair(self):
        a, b = np.array([50, 2.6772, -79.7751]), np.array([50, 0, -82.7485])
        self.assertAlmostEqual(float(deltaE_ciede2000(a,b)), 2.0425, places=4)
        self.assertAlmostEqual(float(deltaE_ciede2000(a,b)), float(deltaE_ciede2000(b,a)))
        self.assertEqual(float(deltaE_ciede2000(a,a)), 0)

    def test_sample_exclusion_and_palette_pixels(self):
        im = Image.fromarray(np.arange(32*32*3,dtype=np.uint8).reshape(32,32,3))
        rgb, xy = sample(im, [0,0,1,1], [{'rect':[0,0,.5,1]}], 2)
        self.assertTrue((xy[:,0]>=16).all())
        sw, lab = palette(rgb,xy,8)
        self.assertEqual(sum(s['count'] for s in sw),len(rgb))
        for s in sw:
            self.assertEqual(list(im.getpixel(tuple(s['xy']))),s['rgb'])
        dist = color_distribution(lab,xy,im.size)
        self.assertEqual(sum(map(sum,dist['hue_by_tone_counts'])),len(rgb))
        self.assertEqual(sum(c['sample_count'] for c in dist['spatial_grid_3x3']),len(rgb))

    def test_bad_roi(self):
        with self.assertRaises(ValueError):
            sample(Image.new('RGB',(30,30)),[.7,.2,.3,.4])
        with self.assertRaises(ValueError):
            sample(Image.new('RGB',(30,30)),step=0)

    def test_all_frames_are_compared(self):
        f = next(f for f in self.lib['frames'] if f['active'] and not f['review']['gates'])
        s = f['palette'][0]
        r = rank(self.lib,s['rgb'],f['review']['materials'][0],f['review']['lighting'],s['tone'])
        self.assertEqual(r['library_frames_examined'],len(self.lib['frames']))
        self.assertEqual(r['swatches_compared'],sum(len(f['palette']) for f in self.lib['frames']))
        self.assertLess(r['compatible_nearest'][0]['delta_e_2000'],1e-5)

    def test_archive_and_gates_cannot_leak(self):
        f = next(f for f in self.lib['frames'] if f['active'] and f['review']['gates'])
        s = f['palette'][0]
        r = rank({'frames':[f]},s['rgb'],f['review']['materials'][0],f['review']['lighting'],s['tone'])
        self.assertEqual(r['compatible_candidates'],0)
        archived = copy.deepcopy(f)
        archived['active'] = False
        r = rank({'frames':[archived]},s['rgb'],f['review']['materials'][0],f['review']['lighting'],s['tone'],f['review']['gates'])
        self.assertEqual(r['compatible_candidates'],0)

    def test_material_mismatch_no_forced_match(self):
        r = rank(self.lib,[70,80,90],'nonexistent-material','warm-day','shadow')
        self.assertEqual(r['status'],'no-compatible-candidate')
        self.assertFalse(r['compatible_nearest'])

    def test_deterministic_ranking(self):
        a = rank(self.lib,[180,110,76],'brick','warm-day','midtone')
        b = rank(self.lib,[180,110,76],'brick','warm-day','midtone')
        self.assertEqual(a,b)

    def test_invalid_color(self):
        for color in [[-1,0,0],[256,0,0],[float('nan'),0,0]]:
            with self.assertRaises(ValueError):
                rank(self.lib,color,'brick','warm-day','midtone')

    def test_pending_is_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.png'
            Image.new('RGB',(40,40),(100,110,120)).save(path)
            before = sha256(path)
            plan = {'source':str(path),'regions':[{'id':'wall','rect':[0,0,1,1],
                'material':'paint','lighting':'warm-day','source_evidence':'Synthetic test fixture'}]}
            r = run(plan,self.lib,'test-catalog-hash')
            self.assertEqual(r['status'],'pending-pixel-review')
            self.assertFalse(r['photo_modified'])
            self.assertEqual(before,sha256(path))
            with self.assertRaises(ValueError):
                run(plan,self.lib,'test-catalog-hash',{'source_sha256':'stale','decisions':{'wall-01':{}}})

    def test_sense_and_archive_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.png'
            Image.new('RGB',(40,40),(100,110,120)).save(path)
            region = {'id':'wall','rect':[0,0,1,1],'material':'paint','lighting':'warm-day',
                      'source_evidence':'Synthetic fixture','enabled_gates':['sense'],
                      'gate_evidence':{'sense':'Not a real current user command'}}
            plan = {'source':str(path),'regions':[region]}
            with self.assertRaises(ValueError):
                run(plan,self.lib,'hash')
            region['enabled_gates']=['archive']
            with self.assertRaises(ValueError):
                run(plan,self.lib,'hash')

    def test_approved_fixture_and_inversion_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.png'
            pixels = np.full((40,40,3),100,dtype=np.uint8)
            pixels[20:] = 110
            im = Image.fromarray(pixels)
            im.save(path)
            rgb, xy = sample(im,[0,0,1,1],step=2)
            swatches, _ = palette(rgb,xy,2)
            for i,s in enumerate(swatches):
                s['id']=f'fixture-{i}'
            lib={'frames':[{'scene':1,'original':str(path),'sha256':sha256(path),'active':True,
                 'review':{'materials':['paint'],'lighting':'warm-day','gates':[]},'palette':swatches}]}
            plan={'source':str(path),'regions':[{'id':'wall','rect':[0,0,1,1],'colors':2,
                 'material':'paint','lighting':'warm-day','source_evidence':'Explicit synthetic test fixture'}]}
            pending=run(plan,lib,'fixture-hash')
            reviews={'source_sha256':sha256(path),'catalog_sha256':'fixture-hash','decisions':{}}
            for q in pending['queries']:
                c=q['comparison']['compatible_nearest'][0]
                reviews['decisions'][q['query_id']]={'swatch_id':c['swatch_id'],'verified_material':'paint',
                    'verified_lighting':'warm-day','verified_tone':q['source_anchor']['tone'],
                    'pixel_review_evidence':'Known synthetic gray fixture','coherence_review':'Identity mapping fixture'}
            self.assertEqual(run(plan,lib,'fixture-hash',reviews)['status'],'color-mapping-reviewed')
            for q in pending['queries']:
                near, second=q['comparison']['compatible_nearest']
                decision=reviews['decisions'][q['query_id']]
                decision['swatch_id']=second['swatch_id']
                decision['rejected_closer_pixels']={near['swatch_id']:'Intentional inversion fixture'}
            with self.assertRaisesRegex(ValueError,'inverted'):
                run(plan,lib,'fixture-hash',reviews)

    def test_unexplained_closer_rejection_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.png'
            Image.new('RGB',(40,40),(100,100,100)).save(path)
            plan={'source':str(path),'regions':[{'id':'wall','rect':[0,0,1,1],'colors':1,
                 'material':'paint','lighting':'warm-day','source_evidence':'Synthetic fixture'}]}
            q=run(plan,self.lib,'fixture-hash')['queries'][0]
            c=q['comparison']['compatible_nearest'][1]
            review={'source_sha256':sha256(path),'catalog_sha256':'fixture-hash',
                    'decisions':{'wall-01':{'swatch_id':c['swatch_id']}}}
            with self.assertRaisesRegex(ValueError,'closer pixel'):
                run(plan,self.lib,'fixture-hash',review)


if __name__ == '__main__':
    unittest.main(verbosity=2)
