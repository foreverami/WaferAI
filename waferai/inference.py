"""Inference matching the supplied Colab validation pipeline."""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np
import timm
import torch

CLASSES = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
           'Near-full', 'Random', 'Scratch', 'none']
MODEL_NAME = 'coatnet_0_rw_224.sw_in1k'

def preprocess(wafer_map):
    wm = np.asarray(wafer_map)
    if wm.ndim != 2 or not wm.size or not np.isin(wm, [0, 1, 2]).all():
        raise ValueError('Expected a nonempty 2D wafer map containing only 0, 1, 2')
    h, w = wm.shape
    side = max(h, w)
    ph, pw = (side-h)//2, (side-w)//2
    padded = np.pad(wm.astype(np.uint8), ((ph, side-h-ph), (pw, side-w-pw)))
    resized = cv2.resize(padded, (224, 224), interpolation=cv2.INTER_NEAREST)
    rgb = np.array([[0,0,0], [0,255,0], [255,255,0]], dtype=np.uint8)[resized]
    tensor = torch.from_numpy(rgb.copy()).permute(2,0,1).float()/255
    mean = torch.tensor([.485,.456,.406])[:,None,None]
    std = torch.tensor([.229,.224,.225])[:,None,None]
    return ((tensor-mean)/std).unsqueeze(0)

def load_model(path, device='cpu'):
    if not Path(path).is_file():
        raise FileNotFoundError(f'Model checkpoint missing: {path}')
    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    if not isinstance(checkpoint, dict) or 'model_state_dict' not in checkpoint:
        raise ValueError('Checkpoint must contain model_state_dict')
    model = timm.create_model(MODEL_NAME, pretrained=False, num_classes=9)
    model.load_state_dict(checkpoint['model_state_dict'], strict=True)
    model.to(device).eval()
    metadata = {k: checkpoint.get(k) for k in ('epoch', 'val_acc')}
    return model, metadata

def predict(model, wafer_map):
    device = next(model.parameters()).device
    with torch.inference_mode():
        probabilities = model(preprocess(wafer_map).to(device)).softmax(dim=1)[0].cpu()
    index = int(probabilities.argmax())
    return {'predicted_class': CLASSES[index], 'confidence': float(probabilities[index]),
            'probabilities': dict(zip(CLASSES, probabilities.tolist())),
            'requires_human_review': float(probabilities[index]) < .8}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', default='models/best_coatnet_model_optimized.pth')
    parser.add_argument('--map', help='Path to a .npy array containing 0/1/2 wafer-map values')
    args = parser.parse_args()
    model, metadata = load_model(args.checkpoint)
    result = {'checkpoint': metadata, 'strict_load': True}
    if args.map:
        result['prediction'] = predict(model, np.load(args.map, allow_pickle=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
