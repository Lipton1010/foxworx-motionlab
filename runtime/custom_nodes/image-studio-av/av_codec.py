"""Non-executable, versioned AV latent container. No pickle or executable object loading."""
import hashlib
import json
import math
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

VERSION = 1
DTYPES = {torch.float16, torch.bfloat16, torch.float32, torch.float64, torch.int64,
          torch.int32, torch.int16, torch.int8, torch.uint8, torch.bool}


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, latent, runtime, nested_type):
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('Explicit runtime identity is required')
    tensors = {}
    def pack(value):
        if isinstance(value, torch.Tensor):
            if value.dtype not in DTYPES or value.layout != torch.strided:
                raise ValueError('Unsupported tensor dtype/layout')
            key = 't' + str(len(tensors))
            tensor = value.detach().cpu().contiguous().clone()
            tensors[key] = tensor
            return {'type': 'tensor', 'key': key, 'shape': list(tensor.shape), 'dtype': str(tensor.dtype)}
        if isinstance(value, nested_type):
            if len(value.tensors) != 2:
                raise ValueError('Only paired video/audio nested latents are supported')
            return {'type': 'av', 'items': [pack(v) for v in value.tensors]}
        if isinstance(value, dict):
            if any(not isinstance(k, str) for k in value):
                raise ValueError('String latent keys required')
            return {'type': 'dict', 'items': {k: pack(v) for k, v in value.items()}}
        if isinstance(value, (tuple, list)):
            return {'type': 'tuple' if isinstance(value, tuple) else 'list', 'items': [pack(v) for v in value]}
        if value is None or type(value) in (str, int, bool) or type(value) is float and math.isfinite(value):
            return {'type': 'json', 'value': value}
        raise ValueError('Unsupported latent state: ' + type(value).__name__)
    samples = latent.get('samples')
    if not isinstance(samples, nested_type) or len(samples.tensors) != 2:
        raise ValueError('Expected joint video/audio samples')
    video, audio = samples.tensors
    if video.ndim != 5 or video.shape[1] != 24 or audio.ndim != 4 or audio.shape[1:3] != (32, 2):
        raise ValueError('Expected native H3 video [B,24,T,H,W] and audio [B,32,2,T]')
    manifest = dict(version=VERSION, runtime=runtime, tree=pack(latent))
    destination = Path(path)
    if destination.exists():
        raise ValueError('AV container is immutable; choose a fresh attempt prefix')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # SafeTensors never deserializes Python objects. Exclusive final publication preserves history.
    import tempfile
    import os
    fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.safetensors')
    os.close(fd)
    try:
        save_file(tensors, temporary, metadata={'image_studio_av': json.dumps(manifest, allow_nan=False)})
        with open(temporary, 'rb') as src, destination.open('xb') as dst:
            import shutil
            shutil.copyfileobj(src, dst)
            dst.flush(); os.fsync(dst.fileno())
    finally:
        os.unlink(temporary)
    return file_hash(destination)


def load(path, expected_hash, runtime, nested_type):
    if not expected_hash or file_hash(path) != expected_hash:
        raise ValueError('AV companion is missing or changed')
    with safe_open(path, framework='pt', device='cpu') as container:
        manifest = json.loads((container.metadata() or {})['image_studio_av'])
        if manifest['version'] != VERSION or manifest['runtime'] != runtime:
            raise ValueError('AV container version/runtime mismatch')
        used = set()
        def unpack(node):
            kind = node['type']
            if kind == 'tensor':
                tensor = container.get_tensor(node['key'])
                if list(tensor.shape) != node['shape'] or str(tensor.dtype) != node['dtype']:
                    raise ValueError('AV tensor metadata mismatch')
                used.add(node['key'])
                return tensor
            if kind == 'av':
                if len(node['items']) != 2:
                    raise ValueError('Expected both AV branches')
                return nested_type(tuple(unpack(n) for n in node['items']))
            if kind == 'dict':
                return {k: unpack(v) for k, v in node['items'].items()}
            if kind in ('list', 'tuple'):
                items = [unpack(n) for n in node['items']]
                return tuple(items) if kind == 'tuple' else items
            if kind == 'json':
                return node['value']
            raise ValueError('Unsupported AV tree node')
        latent = unpack(manifest['tree'])
        if set(container.keys()) != used:
            raise ValueError('Undeclared AV tensors')
    if file_hash(path) != expected_hash:
        raise ValueError('AV companion changed during read')
    return latent
