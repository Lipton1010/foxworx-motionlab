import json
from pathlib import Path
import sys

import folder_paths
import comfy.nested_tensor
import torch.nn.functional as F

from . import av_codec


class SaveStudioAV:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'samples': ('LATENT',), 'filename_prefix': ('STRING', {'default': 'studio-av/result'}),
                             'runtime_identity': ('STRING', {'default': '{}'})}}
    RETURN_TYPES = ()
    FUNCTION = 'save'
    OUTPUT_NODE = True
    CATEGORY = 'Image Studio/production'

    def save(self, samples, filename_prefix, runtime_identity):
        root = Path(folder_paths.get_output_directory()).resolve()
        target = (root / (filename_prefix + '.safetensors')).resolve()
        if not target.is_relative_to(root):
            raise ValueError('AV path escapes output root')
        digest = av_codec.save(target, samples, json.loads(runtime_identity), comfy.nested_tensor.NestedTensor)
        return {'ui': {'studio_av': [{'filename': target.name, 'subfolder': str(target.parent.relative_to(root)),
                                     'type': 'output', 'sha256': digest, 'kind': 'h3-av-safetensors-v1'}]}}


class LoadStudioAV:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'file': ('STRING', {'default': ''}), 'sha256': ('STRING', {'default': ''}),
                             'runtime_identity': ('STRING', {'default': '{}'})}}
    RETURN_TYPES = ('LATENT',)
    FUNCTION = 'load'
    CATEGORY = 'Image Studio/production'

    def load(self, file, sha256, runtime_identity):
        root = Path(folder_paths.get_input_directory()).resolve()
        target = (root / file).resolve()
        if not target.is_relative_to(root):
            raise ValueError('AV input escapes staged root')
        return (av_codec.load(target, sha256, json.loads(runtime_identity), comfy.nested_tensor.NestedTensor),)

    @classmethod
    def IS_CHANGED(cls, file, sha256, runtime_identity):
        return av_codec.file_hash(Path(folder_paths.get_input_directory()) / file)


class ResizeStudioAV:
    """Explicit interpolation, not a learned upscaler. Audio and latent state remain intact."""
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'samples': ('LATENT',), 'width': ('INT', {'default': 1280, 'min': 64, 'step': 64}),
                             'height': ('INT', {'default': 768, 'min': 64, 'step': 64})}}
    RETURN_TYPES = ('LATENT',)
    FUNCTION = 'resize'
    CATEGORY = 'Image Studio/production'

    def resize(self, samples, width, height):
        if set(samples) != {'samples'}:
            raise ValueError('Resizing extra latent state is not supported; same-size refinement preserves it')
        video, audio = samples['samples'].tensors
        result = F.interpolate(video.float(), size=(video.shape[2], height // 16, width // 16), mode='trilinear', align_corners=False).to(video.dtype)
        return ({'samples': comfy.nested_tensor.NestedTensor((result, audio.clone()))},)


NODE_CLASS_MAPPINGS = {'SaveStudioAV': SaveStudioAV, 'LoadStudioAV': LoadStudioAV, 'ResizeStudioAV': ResizeStudioAV}
