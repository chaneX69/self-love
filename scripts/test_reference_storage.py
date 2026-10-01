import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from film_color import sha256
from reference_sources import source_path,load_reference
from texture_features import measure,pixel_hash


class StorageAndTextureTests(unittest.TestCase):
    def fixture(self, root):
        path=root/'original.png'
        Image.new('RGB',(128,128),(105,85,65)).save(path)
        return {'scene':1,'original':'evidence://sha256/'+sha256(path),
                'sha256':sha256(path),'dimensions':[128,128],'pixel_sha256':pixel_hash(Image.open(path))},path

    def test_archive_resolution_and_missing_block(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frame,path=self.fixture(root)
            self.assertIsNone(source_path(frame,required=False,root=root,registry={}))
            with self.assertRaisesRegex(FileNotFoundError,'evidence unavailable'):
                load_reference(frame,root=root,registry={})
            im,_,resolved=load_reference(frame,root=root,registry={frame['sha256']:str(path)})
            self.assertEqual(resolved,path.resolve())
            self.assertEqual(pixel_hash(im),frame['pixel_sha256'])

    def test_lossless_asset_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frame,path=self.fixture(root)
            asset=root/'reference.webp'
            Image.open(path).save(asset,lossless=True)
            frame['reference_asset']='reference.webp';frame['reference_file_sha256']=sha256(asset)
            im,_,resolved=load_reference(frame,root=root,registry={})
            self.assertEqual(resolved,asset.resolve())
            self.assertEqual(pixel_hash(im),frame['pixel_sha256'])
            Image.new('RGB',(128,128),(0,0,0)).save(asset,lossless=True)
            with self.assertRaisesRegex(ValueError,'file hash'):
                load_reference(frame,root=root,registry={})

    def test_wrong_pixel_hash_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frame,path=self.fixture(root)
            frame['pixel_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'sRGB pixels'):
                load_reference(frame,root=root,registry={frame['sha256']:str(path)})

    def test_asset_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frame,_=self.fixture(root)
            frame['reference_asset']='../outside.png'
            with self.assertRaisesRegex(ValueError,'escapes'):
                source_path(frame,root=root,registry={})

    def test_known_texture_forms_and_semantic_unknown(self):
        y,x=np.mgrid[:256,:256]
        rng=np.random.default_rng(10)
        fixtures=[('low-contrast',np.full((256,256),100)),
                  ('directional-structure',100+60*np.sin(2*np.pi*x/8)),
                  ('periodic-structure',100+30*np.sin(2*np.pi*x/8)+30*np.sin(2*np.pi*y/8)),
                  ('mixed-detail',rng.uniform(40,180,(256,256)))]
        for label,gray in fixtures:
            im=Image.fromarray(np.repeat(gray.astype(np.uint8)[...,None],3,axis=2))
            result=measure(im,[0,0,1,1])
            self.assertGreater(result['forms'][label]['share'],.99)
            self.assertTrue(all(v is None for v in result['semantic_occupancy'].values()))
            self.assertEqual(sum(v['footprint_pixels'] for v in result['forms'].values()),result['measured_footprint_pixels'])

    def test_roi_denominator_and_determinism(self):
        im=Image.new('RGB',(288,288),(70,90,100))
        exclusions=[{'rect':[0,0,.5,1]}]
        a=measure(im,[0,0,1,1],exclusions)
        self.assertEqual(a,measure(im,[0,0,1,1],exclusions))
        self.assertEqual(a['valid_roi_pixels'],144*288)
        self.assertLessEqual(a['measured_footprint_pixels'],a['valid_roi_pixels'])
        self.assertEqual(a['unmeasured_roi_pixels']+a['measured_footprint_pixels'],a['valid_roi_pixels'])


if __name__=='__main__':
    unittest.main(verbosity=2)
