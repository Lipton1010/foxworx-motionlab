"""Real tensor/container tests; no model weights or inference are used."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/backend-0.42.1/Comfy-Org-ComfyUI-63be2f9'))
import torch
from comfy.nested_tensor import NestedTensor
spec = importlib.util.spec_from_file_location('av_codec', ROOT / 'runtime/custom_nodes/image-studio-av/av_codec.py')
codec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codec)


class AVTests(unittest.TestCase):
    def test_roundtrip_both_branches_masks_and_required_state(self):
        video = torch.randn(1, 24, 2, 4, 4, dtype=torch.float16)
        audio = torch.randn(1, 32, 2, 8, dtype=torch.float32)
        latent = dict(samples=NestedTensor((video, audio)), noise_mask=NestedTensor((torch.ones_like(video), torch.zeros_like(audio))),
                      batch_index=[0], metadata={'frames': 5, 'state': ('preserved', True, None)})
        runtime = {'torch': torch.__version__, 'node': 'fixture', 'model': 'none — synthetic tensors'}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'av.safetensors'
            digest = codec.save(path, latent, runtime, NestedTensor)
            restored = codec.load(path, digest, runtime, NestedTensor)
            for key in ('samples', 'noise_mask'):
                for before, after in zip(latent[key].tensors, restored[key].tensors):
                    self.assertTrue(torch.equal(before, after))
                    self.assertEqual(before.dtype, after.dtype)
            self.assertEqual(latent['metadata'], restored['metadata'])
            with self.assertRaises(ValueError):
                codec.load(path, digest, {'torch': 'wrong runtime'}, NestedTensor)
            corrupted = Path(temporary) / 'corrupted.safetensors'
            corrupted.write_bytes(path.read_bytes()[:-5])
            with self.assertRaises(ValueError):
                codec.load(corrupted, digest, runtime, NestedTensor)

    def test_unsupported_state_fails_closed(self):
        latent = {'samples': NestedTensor((torch.zeros(1, 24, 2, 4, 4), torch.zeros(1, 32, 2, 8))), 'executable': object()}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                codec.save(Path(temporary) / 'bad.safetensors', latent, {'runtime': 'fixture'}, NestedTensor)


if __name__ == '__main__':
    unittest.main()
