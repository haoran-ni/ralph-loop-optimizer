from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ralph_loop_optimizer.cli import main
from ralph_loop_optimizer.config import load_config

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
CIFAR10_EXAMPLE_DIR = EXAMPLES_DIR / "cifar10-cnn"
TOY_EXAMPLE_DIR = EXAMPLES_DIR / "toy-benchmark"
US_STOCK_EXAMPLE_DIR = EXAMPLES_DIR / "us-stock-strategy"


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

    assert {path.name for path in CIFAR10_EXAMPLE_DIR.iterdir() if path.is_file()} == (
        expected_files
    )


def test_cifar10_cnn_example_documents_edit_boundaries() -> None:
    instructions = (CIFAR10_EXAMPLE_DIR / "AGENTS.md").read_text(encoding="utf-8")

    assert "`model.py`" in instructions
    assert "`train_config.py`" in instructions
    assert "Do not edit:" in instructions
    assert "`evaluate.py`" in instructions
    assert "Use CIFAR-10 only" in instructions
    assert "pretrained weights" in instructions


def test_cifar10_cnn_evaluation_uses_only_cifar10_dataset() -> None:
    evaluate_source = (CIFAR10_EXAMPLE_DIR / "evaluate.py").read_text(
        encoding="utf-8"
    )

    assert "datasets.CIFAR10" in evaluate_source
    assert "dataset\": \"CIFAR-10\"" in evaluate_source
    assert "datasets.MNIST" not in evaluate_source
    assert "datasets.FashionMNIST" not in evaluate_source
    assert "datasets.CIFAR100" not in evaluate_source
    assert "ImageFolder" not in evaluate_source


def test_cifar10_cnn_python_files_are_parseable() -> None:
    for path in [
        CIFAR10_EXAMPLE_DIR / "evaluate.py",
        CIFAR10_EXAMPLE_DIR / "model.py",
        CIFAR10_EXAMPLE_DIR / "train_config.py",
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_toy_benchmark_example_has_expected_files() -> None:
    expected_files = {
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "evaluate.py",
        "strategy.py",
    }

    assert {path.name for path in TOY_EXAMPLE_DIR.iterdir() if path.is_file()} == (
        expected_files
    )
    assert (TOY_EXAMPLE_DIR / "tests" / "test_strategy_contract.py").is_file()


def test_toy_benchmark_example_documents_edit_boundaries() -> None:
    instructions = (TOY_EXAMPLE_DIR / "AGENTS.md").read_text(encoding="utf-8")

    assert "`strategy.py`" in instructions
    assert "Do not edit:" in instructions
    assert "`evaluate.py`" in instructions
    assert "deterministic" in instructions
    assert "`python evaluate.py`" in instructions


def test_toy_benchmark_python_files_are_parseable() -> None:
    for path in [
        TOY_EXAMPLE_DIR / "evaluate.py",
        TOY_EXAMPLE_DIR / "strategy.py",
        TOY_EXAMPLE_DIR / "tests" / "test_strategy_contract.py",
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_toy_benchmark_evaluation_is_deterministic_and_fast() -> None:
    first = _run_toy_evaluation()
    second = _run_toy_evaluation()

    assert first.returncode == 0
    assert second.returncode == 0
    first_summary = json.loads(first.stdout.splitlines()[-1])
    second_summary = json.loads(second.stdout.splitlines()[-1])
    first_summary.pop("elapsed_seconds")
    second_summary.pop("elapsed_seconds")
    assert first_summary == second_summary
    assert first_summary["benchmark"] == "toy-benchmark"
    assert first_summary["cases"] == 8
    assert first_summary["max_score"] == 21
    assert first_summary["score"] < first_summary["target_score"]
    assert "summary score=" in first.stdout


def test_toy_benchmark_contract_tests_run_from_repo_root() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "examples/toy-benchmark/tests"],
        cwd=EXAMPLES_DIR.parent,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_toy_benchmark_can_be_initialized_as_harness(tmp_path: Path) -> None:
    harness_path = tmp_path / "toy-benchmark-harness"
    shutil.copytree(TOY_EXAMPLE_DIR, harness_path)
    _git_repo(harness_path)
    _commit_all(harness_path)

    exit_code = main(
        [
            "init",
            "--harness",
            str(harness_path),
            "--goal",
            "Improve the deterministic toy benchmark score.",
            "--evaluation-command",
            "python evaluate.py",
            "--backend",
            "fake",
        ]
    )

    assert exit_code == 0
    assert (harness_path / "RALPH_LOOP.md").is_file()
    assert (harness_path / "ralph-loop.json").is_file()
    config = load_config(harness_path / "ralph-loop.json")
    assert config.harness_path == harness_path.resolve()
    assert config.evaluation_command == "python evaluate.py"
    brief = (harness_path / "RALPH_LOOP.md").read_text(encoding="utf-8")
    assert "- `<path>`: `<why this file matters>`" in brief
    assert "`evaluate.py`" not in brief
    assert "`AGENTS.md`" not in brief
    assert not (harness_path / "ralph_loop_runs").exists()


def test_us_stock_strategy_example_has_expected_files() -> None:
    expected_files = {
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "evaluate.py",
        "requirements.txt",
        "strategy.py",
    }

    assert {
        path.name for path in US_STOCK_EXAMPLE_DIR.iterdir() if path.is_file()
    } == expected_files
    assert (US_STOCK_EXAMPLE_DIR / "tests" / "test_backtest.py").is_file()


def test_us_stock_strategy_example_documents_edit_boundaries() -> None:
    instructions = (US_STOCK_EXAMPLE_DIR / "AGENTS.md").read_text(
        encoding="utf-8"
    )

    assert "`strategy.py`" in instructions
    assert "Do not edit:" in instructions
    assert "`evaluate.py`" in instructions
    assert "Yahoo Finance OHLCV" in instructions
    assert "next trading day's open" in instructions


def test_us_stock_strategy_python_files_are_parseable() -> None:
    for path in [
        US_STOCK_EXAMPLE_DIR / "evaluate.py",
        US_STOCK_EXAMPLE_DIR / "strategy.py",
        US_STOCK_EXAMPLE_DIR / "tests" / "test_backtest.py",
    ]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_us_stock_strategy_backtest_tests_run_from_repo_root() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "examples/us-stock-strategy/tests"],
        cwd=EXAMPLES_DIR.parent,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _run_toy_evaluation() -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "evaluate.py"],
        cwd=TOY_EXAMPLE_DIR,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Ralph Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "ralph-test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _commit_all(repo_path: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
