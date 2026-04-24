"""Editable training knobs for the CIFAR-10 CNN harness."""

SEED = 17
DEVICE = "auto"
DETERMINISTIC = True

# CIFAR-10 has 5,000 training images and 1,000 test images per class.
# Keep these values between 1 and the per-class maximum for each split.
TRAIN_EXAMPLES_PER_CLASS = 5000
TEST_EXAMPLES_PER_CLASS = 1000

EPOCHS = 40
BATCH_SIZE = 128
LEARNING_RATE = 0.05
WEIGHT_DECAY = 0.0005
MOMENTUM = 0.9

DROPOUT = 0.15
USE_AUGMENTATION = True
NUM_WORKERS = 2
