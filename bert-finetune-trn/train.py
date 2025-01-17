"src: https://github.com/huggingface/optimum-neuron/blob/main/notebooks/text-classification/scripts/train.py"

import argparse
import logging
import os

import evaluate
import numpy as np
from datasets import load_from_disk
from huggingface_hub import HfFolder
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    set_seed,
)

from optimum.neuron import NeuronTrainer as Trainer
from optimum.neuron import NeuronTrainingArguments as TrainingArguments
from optimum.neuron.distributed import lazy_load_for_parallelism

logger = logging.getLogger(__name__)


print(f"is precompilation: {os.environ.get('NEURON_PARALLEL_COMPILE')}")

# torchrun --nproc_per_node 2 train.py --model_id bert-base-uncased --dataset_path /metaflow/metaflow/data/twitter-emotion --pretrained_model_cache ./pretrained_model_cache --bf16 True --lr 5e-05 --output_dir /metaflow/metaflow/model/checkpoints --per_device_train_batch_size 1 --epochs 3 --logging_steps 10


def parse_args():
    """Parse the arguments."""
    parser = argparse.ArgumentParser()
    # add model id and dataset path argument
    parser.add_argument("--model_id", type=str, default="bert-large-uncased", help="Model id to use for training.")
    parser.add_argument("--dataset_path", type=str, default="dataset", help="Path to the already processed dataset.")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory for the model.")
    # add training hyperparameters for epochs, batch size, learning rate, and seed
    parser.add_argument("--epochs", type=int, default=3, help="Number of epochs to train for.")
    parser.add_argument("--tensor_parallel_size", type=int, default=1, help="Number of tensor parallel groups.")
    parser.add_argument("--per_device_train_batch_size", type=int, default=8, help="Batch size to use for training.")
    parser.add_argument("--per_device_eval_batch_size", type=int, default=8, help="Batch size to use for testing.")
    parser.add_argument("--lr", type=float, default=5e-5, help="Learning rate to use for training.")
    parser.add_argument("--seed", type=int, default=42, help="Seed to use for training.")
    parser.add_argument(
        "--bf16",
        type=bool,
        default=False,
        help="Whether to use bf16.",
    )
    parser.add_argument(
        "--hf_token",
        type=str,
        default=HfFolder.get_token(),
        help="Token to use for uploading models to Hugging Face Hub.",
    )
    parser.add_argument(
        "--pretrained_model_cache",
        type=str,
        default=None,
        help="Path to the pretrained model cache.",
    )
    args = parser.parse_known_args()
    return args


# Metric Id
metric = evaluate.load("f1")


# Metric helper method
def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    return metric.compute(predictions=predictions, references=labels, average="weighted")


def training_function(args):
    # set seed
    set_seed(args.seed)

    # load dataset from disk and tokenizer
    train_dataset = load_from_disk(os.path.join(args.dataset_path, "train"))
    eval_dataset = load_from_disk(os.path.join(args.dataset_path, "eval"))
    tokenizer = AutoTokenizer.from_pretrained(args.model_id)

    # Prepare model labels - useful for inference
    labels = train_dataset.features["labels"].names
    num_labels = len(labels)
    label2id, id2label = {}, {}
    for i, label in enumerate(labels):
        label2id[label] = str(i)
        id2label[str(i)] = label

    # Download the model from huggingface.co/models
    # with lazy_load_for_parallelism(
    #     tensor_parallel_size=args.tensor_parallel_size
    # ):
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_id, num_labels=num_labels, label2id=label2id, id2label=id2label
    )

    # Define training args
    # output_dir = args.model_id.split("/")[-1] if "/" in args.model_id else args.model_id
    # output_dir = f"{output_dir}-finetuned"
    training_args = TrainingArguments(
        overwrite_output_dir=True,
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_train_batch_size,
        # per_device_eval_batch_size=args.per_device_eval_batch_size,
        bf16=args.bf16,  # Use BF16 if available
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        # logging & evaluation strategies
        logging_dir=f"{args.output_dir}/logs",
        logging_strategy="steps",
        logging_steps=10,
        # evaluation_strategy="epoch",
        # save_strategy="epoch", 
        # save_total_limit=2,
        # push to hub parameters
        # report_to="tensorboard"
    )

    # Create Trainer instance
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        compute_metrics=compute_metrics,
    )

    # Start training
    trainer.train()

    # eval_res = trainer.evaluate(eval_dataset=eval_dataset)
    # print(eval_res)

    # Save our tokenizer and create model card
    tokenizer.save_pretrained(args.output_dir)


def main():
    args, _ = parse_args()
    training_function(args)


if __name__ == "__main__":
    main()