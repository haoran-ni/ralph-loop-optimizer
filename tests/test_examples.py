from __future__ import annotations

import ast
from pathlib import Path


EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "cifar10-cnn"


def test_cifar10_cnn_example_has_expected_files() -> None:
    expected_files = {
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "evaluate.py",
        "model.py",
        "requirements.txt",
        "train_config.py",
    }

    assert {path.name for path in EXAMPLE_DIR.iterdir() if path.is_file()} == (
        expected_files
    )


def test_cifar10_cnn_example_documents_edit_boundaries() -> None:
    instructions = (EXAMPLE_DIR / "AGENTS.md").read_text(encoding="utf-8")

    assert "`model.py`" in instructions
    assert "`train_config.py`" in instructions
    assert "Do not edit:" in instructions
    assert "`evaluate.py`" in instructions
    assert "Use CIFAR-10 only" in instructions
    assert "pretrained weights" in instructions


def test_cifar10_cnn_evaluation_uses_only_cifar10_dataset() -> None:
    evaluate_source = (EXAMPLE_DIR / "evaluate.py").read_text(encoding="utf-8")

    assert "datasets.CIFAR10" in evaluate_source
    assert "dataset\": \"CIFAR-10\"" in evaluate_source
    assert "datasets.MNIST" not in evaluate_source
    assert "datasets.FashionMNIST" not in evaluate_source
    assert "datasets.CIFAR100" not in evaluate_source
    assert "ImageFolder" not in evaluate_source


def test_cifar10_cnn_python_files_are_parseable() -> None:
    for path in [
        EXAMPLE_DIR / "evaluate.py",
        EXAMPLE_DIR / "model.py",
        EXAMPLE_DIR / "train_config.py",
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
