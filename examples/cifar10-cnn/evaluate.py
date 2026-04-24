"""Train and evaluate the editable CIFAR-10 model."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Iterable

import torch
from torch import nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms

from model import build_model
from train_config import (
    BATCH_SIZE,
    DETERMINISTIC,
    DEVICE,
    EPOCHS,
    LEARNING_RATE,
    MOMENTUM,
    NUM_WORKERS,
    SEED,
    TEST_EXAMPLES_PER_CLASS,
    TRAIN_EXAMPLES_PER_CLASS,
    USE_AUGMENTATION,
    WEIGHT_DECAY,
)


CIFAR10_CLASSES = 10
DATA_DIR = Path("data")


def main() -> int:
    validate_settings()
    seed_everything(SEED)
    device = choose_device()
    train_loader, test_loader = build_loaders()
    model = build_model().to(device)
    loss_fn = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(
        model.parameters(),
        lr=LEARNING_RATE,
        momentum=MOMENTUM,
        weight_decay=WEIGHT_DECAY,
    )

    started_at = time.perf_counter()
    epochs_to_log = progress_epochs(EPOCHS)
    for epoch in range(1, EPOCHS + 1):
        torch.manual_seed(SEED + epoch)
        train_loss, train_accuracy = train_one_epoch(
            model,
            train_loader,
            loss_fn,
            optimizer,
            device,
        )
        test_loss, test_accuracy = evaluate(model, test_loader, loss_fn, device)
        if epoch in epochs_to_log:
            print(
                "epoch={epoch} train_loss={train_loss:.4f} "
                "train_accuracy={train_accuracy:.4f} test_loss={test_loss:.4f} "
                "test_accuracy={test_accuracy:.4f}".format(
                    epoch=epoch,
                    train_loss=train_loss,
                    train_accuracy=train_accuracy,
                    test_loss=test_loss,
                    test_accuracy=test_accuracy,
                )
            )

    final_accuracy = round(test_accuracy, 6)
    summary = {
        "dataset": "CIFAR-10",
        "device": str(device),
        "epochs": EPOCHS,
        "train_examples": TRAIN_EXAMPLES_PER_CLASS * CIFAR10_CLASSES,
        "test_examples": TEST_EXAMPLES_PER_CLASS * CIFAR10_CLASSES,
        "test_accuracy": final_accuracy,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
    }
    print_summary(summary)
    return 0


def validate_settings() -> None:
    positive_ints = {
        "TRAIN_EXAMPLES_PER_CLASS": TRAIN_EXAMPLES_PER_CLASS,
        "TEST_EXAMPLES_PER_CLASS": TEST_EXAMPLES_PER_CLASS,
        "EPOCHS": EPOCHS,
        "BATCH_SIZE": BATCH_SIZE,
    }
    for name, value in positive_ints.items():
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    non_negative_numbers = {
        "LEARNING_RATE": LEARNING_RATE,
        "WEIGHT_DECAY": WEIGHT_DECAY,
        "MOMENTUM": MOMENTUM,
    }
    for name, value in non_negative_numbers.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{name} must be a non-negative number")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if DETERMINISTIC:
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def choose_device() -> torch.device:
    if DEVICE != "auto":
        return torch.device(DEVICE)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def build_loaders() -> tuple[DataLoader, DataLoader]:
    train_dataset = datasets.CIFAR10(
        root=DATA_DIR,
        train=True,
        download=True,
        transform=build_transform(training=True),
    )
    test_dataset = datasets.CIFAR10(
        root=DATA_DIR,
        train=False,
        download=True,
        transform=build_transform(training=False),
    )
    train_subset = Subset(
        train_dataset,
        class_balanced_indices(
            train_dataset.targets,
            TRAIN_EXAMPLES_PER_CLASS,
            SEED,
        ),
    )
    test_subset = Subset(
        test_dataset,
        class_balanced_indices(
            test_dataset.targets,
            TEST_EXAMPLES_PER_CLASS,
            SEED + 1,
        ),
    )
    return (
        DataLoader(
            train_subset,
            batch_size=BATCH_SIZE,
            shuffle=True,
            generator=torch.Generator().manual_seed(SEED),
            num_workers=NUM_WORKERS,
            pin_memory=torch.cuda.is_available(),
        ),
        DataLoader(
            test_subset,
            batch_size=BATCH_SIZE,
            shuffle=False,
            num_workers=NUM_WORKERS,
            pin_memory=torch.cuda.is_available(),
        ),
    )


def build_transform(training: bool) -> transforms.Compose:
    steps = []
    if training and USE_AUGMENTATION:
        steps.extend(
            [
                transforms.RandomCrop(32, padding=4),
                transforms.RandomHorizontalFlip(),
            ]
        )
    steps.extend(
        [
            transforms.ToTensor(),
            transforms.Normalize(
                mean=(0.4914, 0.4822, 0.4465),
                std=(0.2470, 0.2435, 0.2616),
            ),
        ]
    )
    return transforms.Compose(steps)


def progress_epochs(total_epochs: int) -> set[int]:
    if total_epochs <= 10:
        return set(range(1, total_epochs + 1))
    return {
        round(1 + index * (total_epochs - 1) / 9)
        for index in range(10)
    }


def class_balanced_indices(
    targets: Iterable[int],
    examples_per_class: int,
    seed: int,
) -> list[int]:
    buckets = [[] for _ in range(CIFAR10_CLASSES)]
    for index, target in enumerate(targets):
        buckets[int(target)].append(index)

    generator = torch.Generator().manual_seed(seed)
    selected = []
    for class_index, bucket in enumerate(buckets):
        if len(bucket) < examples_per_class:
            raise ValueError(
                f"CIFAR-10 class {class_index} has only {len(bucket)} examples; "
                f"requested {examples_per_class}"
            )
        order = torch.randperm(len(bucket), generator=generator)
        selected.extend(bucket[index] for index in order[:examples_per_class].tolist())
    return selected


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    loss_fn: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0
    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = loss_fn(logits, labels)
        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        correct += (logits.argmax(dim=1) == labels).sum().item()
        total += batch_size
    return total_loss / total, correct / total


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    loss_fn: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)
            logits = model(images)
            loss = loss_fn(logits, labels)

            batch_size = labels.size(0)
            total_loss += loss.item() * batch_size
            correct += (logits.argmax(dim=1) == labels).sum().item()
            total += batch_size
    return total_loss / total, correct / total


def print_summary(summary: dict[str, object]) -> None:
    print(
        "summary dataset={dataset} epochs={epochs} train_examples={train_examples} "
        "test_examples={test_examples} test_accuracy={test_accuracy:.4f} "
        "elapsed_seconds={elapsed_seconds:.3f}".format(**summary)
    )


if __name__ == "__main__":
    raise SystemExit(main())
