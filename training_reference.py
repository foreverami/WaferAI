# ==========================================
# WM-811K Wafer Defect CoAtNet Classifier
# [Google Colab 전용 / Drive 연동 & 속도 극대화판]
# ==========================================

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
import timm  # CoAtNet 로드
import pandas as pd
import numpy as np
import cv2
import os
import gc
import math
import shutil
from sklearn.model_selection import train_test_split
from torch.optim.lr_scheduler import LambdaLR
from google.colab import drive

print("🏭 [AI 팩토리 Colab 가동] T4 GPU 및 CoAtNet 엔진 점화...\n")

# ==========================================
# 0. Google Drive 마운트
# ==========================================
drive.mount('/content/drive')

# ==========================================
# 1. 하이퍼파라미터 및 Colab 환경 설정
# ==========================================
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🖥️ 사용 중인 디바이스: {device}")
if device.type == 'cpu':
    print("⚠️ 경고: [런타임] - [런타임 유형 변경]에서 하드웨어 가속기를 T4 GPU로 변경하세요!")

torch.backends.cudnn.benchmark = True

# CoAtNet_0은 파라미터가 적어 BATCH_SIZE 32도 Colab T4(15GB)에서 넉넉히 수용 가능합니다.
BATCH_SIZE = 32
EPOCHS = 15
LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.05
WARMUP_EPOCHS = 2
LABEL_SMOOTHING = 0.1
GRAD_CLIP = 1.0
PATIENCE = 5
TARGET_SIZE = (224, 224)
NUM_CLASSES = 9
NUM_WORKERS = 0 # RAM 방어막 (fork 복제 차단)

# 경로 설정
data_path = '/content/drive/MyDrive/캡스톤 디자인/LSWMD.pkl'
local_model_path = '/content/best_coatnet_model.pth'
drive_model_path = '/content/drive/MyDrive/WM-811K_Model/best_coatnet_model_optimized.pth'
os.makedirs(os.path.dirname(drive_model_path), exist_ok=True)

class_names = ['Center', 'Donut', 'Edge-Loc', 'Edge-Ring', 'Loc',
               'Near-full', 'Random', 'Scratch', 'none']
label_to_idx = {name: i for i, name in enumerate(class_names)}

# ==========================================
# 2. 고급 손실 함수 (Focal Loss)
# ==========================================
class FocalLossWithSmoothing(nn.Module):
    def __init__(self, alpha=1, gamma=2, label_smoothing=0.1, reduction='mean'):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.label_smoothing = label_smoothing
        self.reduction = reduction

    def forward(self, inputs, targets):
        ce_loss = F.cross_entropy(inputs, targets, reduction='none',
                                  label_smoothing=self.label_smoothing)
        pt = torch.exp(-ce_loss)
        focal_loss = self.alpha * (1 - pt) ** self.gamma * ce_loss
        return focal_loss.mean() if self.reduction == 'mean' else focal_loss.sum()

# ==========================================
# 3. 데이터 로드 및 RAM 최적화
# ==========================================
print("\n📥 Google Drive에서 데이터를 찾는 중...")
if not os.path.exists(data_path):
    print(f"❌ [치명적 오류] 파일을 찾을 수 없습니다: {data_path}")
    import sys; sys.exit()

df_raw = pd.read_pickle(data_path)

def extract_label(x):
    if x is None or len(x) == 0: return 'Unlabeled'
    val = x[0]
    if isinstance(val, (list, np.ndarray)) and len(val) > 0: return val[0]
    return val

df_raw['failure_type'] = df_raw.failureType.apply(extract_label)
df_labeled = df_raw[df_raw['failure_type'] != 'Unlabeled'].copy()

df_defects = df_labeled[df_labeled['failure_type'] != 'none']
df_none = df_labeled[df_labeled['failure_type'] == 'none'].sample(
    n=len(df_defects), random_state=42)
df_balanced = pd.concat([df_defects, df_none]).reset_index(drop=True)

train_df, val_df = train_test_split(
    df_balanced, test_size=0.2, stratify=df_balanced['failure_type'], random_state=42)

print(f"📊 밸런싱 완료! 총 학습 데이터 개수: {len(df_balanced)}개")

def to_uint8(arr):
    return arr.astype(np.uint8)

print("🔄 waferMap을 uint8로 압축 변환 중... (Colab RAM 폭발 방지)")
train_maps  = [to_uint8(m) for m in train_df['waferMap'].tolist()]
train_labels = train_df['failure_type'].map(label_to_idx).tolist()

val_maps   = [to_uint8(m) for m in val_df['waferMap'].tolist()]
val_labels  = val_df['failure_type'].map(label_to_idx).tolist()

del df_raw, df_labeled, df_defects, df_none, df_balanced, train_df, val_df
gc.collect()
print("🧹 Pandas DataFrame 메모리 해제 완료.")

# ==========================================
# 4. 데이터셋 및 데이터로더
# ==========================================
class WaferDataset(Dataset):
    def __init__(self, maps, labels, transform=None):
        self.maps = maps
        self.labels = labels
        self.transform = transform
        self.COLOR_LUT = np.array([
            [0,   0,   0],
            [0,   255, 0],
            [255, 255, 0],
        ], dtype=np.uint8)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        wm = self.maps[idx]
        h, w = wm.shape
        max_dim = max(h, w)
        pad_h = (max_dim - h) // 2
        pad_w = (max_dim - w) // 2
        padded = np.pad(wm,
                        ((pad_h, max_dim - h - pad_h),
                         (pad_w, max_dim - w - pad_w)),
                        mode='constant', constant_values=0)

        resized = cv2.resize(padded, TARGET_SIZE, interpolation=cv2.INTER_NEAREST)
        rgb_img = self.COLOR_LUT[resized]

        if self.transform:
            rgb_img = self.transform(rgb_img)

        return rgb_img, int(self.labels[idx])

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD  = [0.229, 0.224, 0.225]

train_transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomVerticalFlip(p=0.5),
    transforms.RandomRotation(degrees=15, interpolation=transforms.InterpolationMode.NEAREST),
    transforms.ToTensor(),
    transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
])

val_transform = transforms.Compose([
    transforms.ToPILImage(),
    transforms.ToTensor(),
    transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
])

train_loader = DataLoader(
    WaferDataset(train_maps, train_labels, transform=train_transform),
    batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS,
    pin_memory=(device.type == 'cuda'), drop_last=True
)
val_loader = DataLoader(
    WaferDataset(val_maps, val_labels, transform=val_transform),
    batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS,
    pin_memory=(device.type == 'cuda')
)

# ==========================================
# 5. 모델 / 옵티마이저 / 스케줄러 설정
# ==========================================
print("🧠 CoAtNet (C-C-T-T) 구조로 신경망 재배치 중...")
model = timm.create_model('coatnet_0_rw_224.sw_in1k', pretrained=True, num_classes=NUM_CLASSES)
model = model.to(device)

criterion = FocalLossWithSmoothing(gamma=2.0, label_smoothing=LABEL_SMOOTHING)
optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

# Colab GPU 전용 가속 (NVIDIA AMP)
scaler = torch.amp.GradScaler('cuda')

total_steps  = EPOCHS * len(train_loader)
warmup_steps = WARMUP_EPOCHS * len(train_loader)

def lr_lambda(step):
    if step < warmup_steps:
        return step / max(1, warmup_steps)
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    return max(1e-6 / LEARNING_RATE, 0.5 * (1.0 + math.cos(math.pi * progress)))

scheduler = LambdaLR(optimizer, lr_lambda)

# ==========================================
# 6. 학습 루프 (NVIDIA AMP 적용)
# ==========================================
best_val_acc = 0.0
patience_counter = 0

print("\n🚀 [학습 시작] T4 GPU 텐서 코어 가동!")
for epoch in range(EPOCHS):
    model.train()
    running_loss, correct, total = 0.0, 0, 0

    for inputs, labels in train_loader:
        inputs = inputs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)

        # 혼합 정밀도 연산 (속도 향상 및 VRAM 절약)
        with torch.amp.autocast('cuda'):
            outputs = model(inputs)
            loss = criterion(outputs, labels)

        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), GRAD_CLIP)
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        running_loss += loss.item() * inputs.size(0)
        _, predicted  = outputs.max(1)
        total        += labels.size(0)
        correct      += predicted.eq(labels).sum().item()

    train_loss = running_loss / total
    train_acc  = 100. * correct / total
    current_lr = scheduler.get_last_lr()[0]

    model.eval()
    val_loss, val_correct, val_total = 0.0, 0, 0
    with torch.no_grad():
        for inputs, labels in val_loader:
            inputs = inputs.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)

            with torch.amp.autocast('cuda'):
                outputs = model(inputs)
                loss    = criterion(outputs, labels)

            val_loss    += loss.item() * inputs.size(0)
            _, predicted = outputs.max(1)
            val_total   += labels.size(0)
            val_correct += predicted.eq(labels).sum().item()

    val_loss /= val_total
    val_acc   = 100. * val_correct / val_total

    print(f"Epoch [{epoch+1}/{EPOCHS}] LR: {current_lr:.2e} | "
          f"Train Loss: {train_loss:.4f}, Acc: {train_acc:.2f}% | "
          f"Val Loss: {val_loss:.4f}, Acc: {val_acc:.2f}%")

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        patience_counter = 0
        torch.save({
            'epoch': epoch + 1,
            'model_state_dict': model.state_dict(),
            'val_acc': best_val_acc,
        }, local_model_path)
        print(f"  🌟 Best CoAtNet Model Saved! (Accuracy: {best_val_acc:.2f}%)")
    else:
        patience_counter += 1
        if patience_counter >= PATIENCE:
            print(f"\n🛑 [Early Stopping] {PATIENCE} 에폭 동안 개선 없음. 학습 종료.")
            break

# ==========================================
# 7. 드라이브로 모델 최종 저장
# ==========================================
if os.path.exists(local_model_path):
    print(f"\n☁️ Google Drive로 최종 모델 업로드 중...")
    shutil.copy(local_model_path, drive_model_path)
    print(f"✅ 업로드 완료: {drive_model_path}")

print(f"\n🎉 학습 완료! 최고 정확도: {best_val_acc:.2f}%")