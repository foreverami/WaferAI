"""CoAtNet-0 재학습 — 고정 train/val/test 분할 + (선택) 엔지니어 검토 라벨.

    # 처음: ImageNet 가중치에서 시작해 깨끗한 테스트 정확도를 얻는다
    python3 -m scripts.train

    # 재학습 루프: 서버에서 내려받은 검토 라벨을 학습 데이터에 더한다
    python3 -m scripts.train --reviews reviews.npz --init runs/<이전>/model.pth

    # 동작 확인용 짧은 실행
    python3 -m scripts.train --limit 256 --epochs 1

하이퍼파라미터는 1학기 Colab 학습(training_reference.py)과 같다. 바뀐 것은 데이터 분할뿐이라,
결과 차이는 분할과 데이터의 차이로 읽을 수 있다.

현재 운영 모델(1학기)에서 이어 학습하면 안 된다. 그 모델은 결함 샘플을 전부 학습·검증에
써서, 새 테스트 셋의 샘플도 이미 봤다. 거기서 시작하면 테스트 정확도가 다시 오염된다.
그래서 --init 으로 받은 체크포인트의 split_id 가 지금 분할과 다르면 거부한다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.training_common import (CLASS_NAMES, DEFAULT_DATA, balanced, evaluate_test,
                                     load_training_set, pick_device, probabilities, unpack)
from waferai.backends import MODEL_NAME
from waferai.preprocess import IMAGENET_MEAN, IMAGENET_STD, to_model_input, to_rgb, validate_map

# training_reference.py 와 같은 값
BATCH_SIZE = 32
EPOCHS = 15
LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.05
WARMUP_EPOCHS = 2
LABEL_SMOOTHING = 0.1
FOCAL_GAMMA = 2.0
GRAD_CLIP = 1.0
PATIENCE = 5


def build_datasets(dataset, reviews_path, limit, seed):
    """학습·검증에 쓸 (맵, 라벨) 목록. 테스트 셋은 여기서 절대 건드리지 않는다."""
    train_idx = balanced(dataset.indices('train'), dataset.labels, seed)
    val_idx = balanced(dataset.indices('val'), dataset.labels, seed + 1)
    if limit:
        rng = np.random.default_rng(seed)
        train_idx = np.sort(rng.choice(train_idx, size=min(limit, len(train_idx)), replace=False))
        val_idx = np.sort(rng.choice(val_idx, size=min(max(limit // 4, 32), len(val_idx)),
                                     replace=False))

    train_maps = [dataset.maps[i] for i in train_idx]
    train_labels = list(dataset.labels[train_idx])
    reviewed = 0
    if reviews_path:
        reviews = np.load(reviews_path, allow_pickle=False)
        review_maps = unpack(reviews['flat'], reviews['shapes'])
        index = {name: i for i, name in enumerate(CLASS_NAMES)}
        review_labels = [index[str(name)] for name in reviews['labels']]
        train_maps += review_maps
        train_labels += review_labels
        reviewed = len(review_maps)

    val_maps = [dataset.maps[i] for i in val_idx]
    val_labels = dataset.labels[val_idx]
    return train_maps, np.array(train_labels, dtype=np.int64), val_maps, val_labels, reviewed


def make_loader(maps, labels, train: bool, batch_size: int, workers: int, device: str):
    import torch
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms

    # 학습 증강은 1학기와 같다. 색 변환(LUT)까지는 서빙과 같은 to_rgb 를 쓴다.
    augment = transforms.Compose([
        transforms.ToPILImage(),
        transforms.RandomHorizontalFlip(p=0.5),
        transforms.RandomVerticalFlip(p=0.5),
        transforms.RandomRotation(degrees=15, interpolation=transforms.InterpolationMode.NEAREST),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN.tolist(), std=IMAGENET_STD.tolist()),
    ])

    class WaferDataset(Dataset):
        def __len__(self):
            return len(labels)

        def __getitem__(self, index):
            wafer_map = validate_map(maps[index])
            if train:
                tensor = augment(to_rgb(wafer_map))
            else:
                tensor = torch.from_numpy(to_model_input(wafer_map)[0])
            return tensor, int(labels[index])

    return DataLoader(WaferDataset(), batch_size=batch_size, shuffle=train,
                      num_workers=workers, drop_last=train, pin_memory=(device == 'cuda'))


def check_init_split(origin: str | None, current: str, allow_contaminated: bool) -> None:
    """이어 학습할 가중치가 같은 분할로 학습된 것인지 확인한다.

    다른 분할(또는 분할 기록이 없는 1학기 모델)에서 시작하면, 그 모델이 이번 테스트 셋의
    샘플을 이미 봤을 수 있다. 그러면 테스트 정확도가 다시 오염된다.
    """
    if origin == current or allow_contaminated:
        return
    raise SystemExit(
        f'시작 가중치의 분할({origin or "기록 없음 — 1학기 모델"})이 지금 분할({current})과 '
        '다릅니다.\n  그 모델은 이번 테스트 셋을 학습에 썼을 수 있어 테스트 정확도가 오염됩니다.\n'
        '  ImageNet 에서 시작하거나(--init imagenet), 오염을 감수하려면 '
        '--allow-contaminated-init 을 붙이세요.')


def build_model(init: str, split_id: str, allow_contaminated: bool, device: str):
    import timm

    from waferai.backends import load_checkpoint

    if init == 'imagenet':
        model = timm.create_model(MODEL_NAME, pretrained=True, num_classes=len(CLASS_NAMES))
        return model.to(device), {'init': 'imagenet'}

    state_dict, metadata = load_checkpoint(init)
    origin = metadata.get('split_id')
    check_init_split(origin, split_id, allow_contaminated)
    model = timm.create_model(MODEL_NAME, pretrained=False, num_classes=len(CLASS_NAMES))
    model.load_state_dict(state_dict, strict=True)
    return model.to(device), {'init': str(init), 'init_split_id': origin}


def focal_loss(logits, targets):
    import torch
    import torch.nn.functional as F

    ce = F.cross_entropy(logits, targets, reduction='none', label_smoothing=LABEL_SMOOTHING)
    return ((1 - torch.exp(-ce)) ** FOCAL_GAMMA * ce).mean()


def main() -> None:
    parser = argparse.ArgumentParser(description='WaferAI CoAtNet-0 재학습')
    parser.add_argument('--data', default=DEFAULT_DATA)
    parser.add_argument('--reviews', help='서버에서 내려받은 검토 라벨 (.npz)')
    parser.add_argument('--init', default='imagenet', help="'imagenet' 또는 체크포인트 경로")
    parser.add_argument('--allow-contaminated-init', action='store_true')
    parser.add_argument('--epochs', type=int, default=EPOCHS)
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--workers', type=int, default=0)
    parser.add_argument('--limit', type=int, help='학습 샘플 수 상한 (동작 확인용)')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', help='결과 폴더 (기본 runs/<시각>)')
    args = parser.parse_args()

    # MPS 설정은 PyTorch 가 GPU 메모리를 처음 잡기 전에 들어가야 한다. pick_device 가 torch 를
    # 불러오므로 그보다 먼저 둔다 (CUDA·CPU 에서는 영향이 없다).
    # Apple Silicon 은 GPU 와 RAM 을 같이 쓴다. 기본값(1.7)은 권장 한도를 넘겨 할당하게 두는데,
    # 8GB 맥에서 배치 32 학습이 8GB 넘게 잡아 스왑으로 맥 전체가 멈췄다. 1.0 으로 묶어
    # 한도를 넘으면 스왑 대신 즉시 메모리 오류로 끝나게 한다.
    os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
    os.environ.setdefault('PYTORCH_MPS_HIGH_WATERMARK_RATIO', '1.0')
    # 하한(기본 1.4)은 상한보다 작아야 한다. 상한만 내리면 "invalid low watermark ratio" 로 멈춘다.
    os.environ.setdefault('PYTORCH_MPS_LOW_WATERMARK_RATIO', '0.8')
    device = pick_device(args.device)
    import torch
    from torch.optim.lr_scheduler import LambdaLR

    torch.manual_seed(args.seed)
    output = Path(args.output or f'runs/{datetime.now().strftime("%Y%m%d-%H%M%S")}')
    output.mkdir(parents=True, exist_ok=True)

    print(f'[데이터] {args.data}', flush=True)
    dataset = load_training_set(args.data)
    train_maps, train_labels, val_maps, val_labels, reviewed = build_datasets(
        dataset, args.reviews, args.limit, args.seed)
    print(f'  split_id {dataset.split_id} · 학습 {len(train_labels):,} (검토 라벨 {reviewed:,}) · '
          f'검증 {len(val_labels):,} · 테스트 {len(dataset.indices("test")):,} (학습에 쓰지 않음)',
          flush=True)

    model, init_info = build_model(args.init, dataset.split_id,
                                   args.allow_contaminated_init, device)
    train_loader = make_loader(train_maps, train_labels, True, args.batch_size, args.workers, device)
    print(f'[모델] {MODEL_NAME} · 시작 {init_info["init"]} · 장치 {device}', flush=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    total_steps = max(1, args.epochs * len(train_loader))
    warmup_steps = WARMUP_EPOCHS * len(train_loader)

    def schedule(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        return max(1e-6 / LEARNING_RATE, 0.5 * (1.0 + math.cos(math.pi * progress)))

    scheduler = LambdaLR(optimizer, schedule)
    use_amp = device == 'cuda'
    scaler = torch.amp.GradScaler('cuda') if use_amp else None

    best_acc, patience, history = -1.0, 0, []
    checkpoint_path = output / 'model.pth'
    for epoch in range(1, args.epochs + 1):
        model.train()
        started, seen, correct, loss_sum = time.perf_counter(), 0, 0, 0.0
        for step, (inputs, targets) in enumerate(train_loader, 1):
            inputs, targets = inputs.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            if use_amp:
                with torch.amp.autocast('cuda'):
                    logits = model(inputs)
                    loss = focal_loss(logits, targets)
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
                scaler.step(optimizer)
                scaler.update()
            else:
                logits = model(inputs)
                loss = focal_loss(logits, targets)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
                optimizer.step()
            scheduler.step()

            seen += targets.size(0)
            correct += int((logits.argmax(1) == targets).sum())
            loss_sum += float(loss) * targets.size(0)
            if step % 50 == 0 or step == len(train_loader):
                rate = seen / (time.perf_counter() - started)
                print(f'\r  epoch {epoch}/{args.epochs}  {step}/{len(train_loader)}  '
                      f'loss {loss_sum / seen:.4f}  {rate:.1f}장/초', end='', flush=True)

        # 평가 배치도 학습 배치를 따른다. 고정값(64)이면 학습 배치를 줄여도 여기서 메모리가 튄다.
        val_pred = probabilities(model, val_maps, device, args.batch_size).argmax(axis=1)
        val_acc = float((val_pred == val_labels).mean()) * 100
        elapsed = time.perf_counter() - started
        history.append({'epoch': epoch, 'train_loss': loss_sum / max(seen, 1),
                        'train_acc': correct / max(seen, 1) * 100, 'val_acc': val_acc,
                        'seconds': round(elapsed, 1)})
        print(f'\n  → 검증 {val_acc:.2f}%  ({elapsed / 60:.1f}분)', flush=True)

        if val_acc > best_acc:
            best_acc, patience = val_acc, 0
            torch.save({'epoch': epoch, 'model_state_dict': model.state_dict(),
                        'val_acc': val_acc, 'split_id': dataset.split_id}, checkpoint_path)
            print(f'    최고 기록 저장 ({val_acc:.2f}%)', flush=True)
        else:
            patience += 1
            if patience >= PATIENCE:
                print(f'  {PATIENCE} 에폭 동안 개선이 없어 멈춥니다', flush=True)
                break

    print('[테스트] 학습에 쓰지 않은 고정 테스트 셋으로 평가', flush=True)
    best = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    model.load_state_dict(best['model_state_dict'])
    test_metrics = evaluate_test(model, dataset, device, limit=args.limit and args.limit * 2,
                                 batch_size=args.batch_size)
    for view in ('balanced', 'natural'):
        m = test_metrics[view]
        print(f'  {view:9s} n={m["n"]:,}  정확도 {m["accuracy"]:.4f}  macro-F1 {m["macro_f1"]:.4f}',
              flush=True)

    trained_on = {'train': int(len(train_labels)), 'val': int(len(val_labels)),
                  'reviews': int(reviewed), 'limit': args.limit}
    best.update(test_metrics=test_metrics, trained_on=trained_on, **init_info,
                created_at=datetime.now(timezone.utc).isoformat())
    torch.save(best, checkpoint_path)
    (output / 'metrics.json').write_text(json.dumps(
        {'best_val_acc': best_acc, 'best_epoch': best['epoch'], 'test': test_metrics,
         'trained_on': trained_on, **init_info, 'history': history},
        ensure_ascii=False, indent=2))
    print(f'\n완료: {checkpoint_path}  (최고 검증 {best_acc:.2f}% @ epoch {best["epoch"]})')


if __name__ == '__main__':
    main()
