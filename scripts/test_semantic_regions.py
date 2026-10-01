import unittest
import numpy as np
from PIL import Image

from trace_semantic_regions import rle_encode, rle_decode, trace, valid_pixels


class SemanticRegionTraceTests(unittest.TestCase):
    def test_lossless_native_mask_round_trip(self):
        mask = np.array([[0, 0, 1, 1], [2, 0, 2, 2]], dtype=np.uint8)
        self.assertTrue(np.array_equal(mask, rle_decode(rle_encode(mask), mask.shape)))

    def test_invalid_mask_cannot_pass(self):
        for runs in [[[1, 3]], [[3, 4]], [[0, 0], [1, 4]], [[1, 2.5]]]:
            with self.assertRaises(ValueError):
                rle_decode(runs, (2, 2))

    def test_exclusions_are_pixel_based(self):
        valid = valid_pixels((10, 10), [.1, .1, .9, .9], [{'rect': [.3, .3, .5, .5]}])
        self.assertEqual(int(valid.sum()), 60)

    def test_zero_signal_is_untraced_not_negative(self):
        annotation = {'rect':[0,0,16,16], 'class':'halftone', 'mode':'light',
                      'sigma':2, 'low':1, 'high':2}
        states = trace(Image.new('RGB',(16,16),(128,128,128)), annotation)
        self.assertEqual(set(np.unique(states)), {0})

    def test_color_band_interior_not_only_edges(self):
        pixels = np.full((16,16,3), 220, dtype=np.uint8)
        pixels[:,4:12] = [20,220,220]
        annotation = {'rect':[0,0,16,16], 'class':'color_misregistration',
                      'mode':'chroma-range', 'sigma':0, 'low':55, 'high':75}
        states = trace(Image.fromarray(pixels), annotation)
        self.assertTrue((states[:,4:12] == 1).all())
        self.assertEqual(int((states == 1).sum()), 128)

    def test_crop_outside_source_rejected(self):
        annotation = {'rect':[15,0,2,2], 'class':'halftone', 'mode':'light',
                      'sigma':2, 'low':1, 'high':2}
        with self.assertRaises(ValueError):
            trace(Image.new('RGB',(16,16)), annotation)


if __name__ == '__main__':
    unittest.main()
