from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


FEATURE_NAMES: tuple[str, ...] = (
    "ast",
    "calls",
    "attrs",
    "signature",
    "control",
    "decorators",
    "strings",
    "name",
)


@dataclass(frozen=True, slots=True)
class RankedExample:
    features: Mapping[str, float]
    label: int
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class Evaluation:
    samples: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    log_loss: float
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    @property
    def false_positive_rate(self) -> float:
        denominator = self.false_positives + self.true_negatives
        return self.false_positives / denominator if denominator else 0.0

    def as_dict(self) -> dict:
        return {
            "samples": self.samples,
            "accuracy": round(self.accuracy, 6),
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
            "f1": round(self.f1, 6),
            "log_loss": round(self.log_loss, 6),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "false_positive_rate": round(self.false_positive_rate, 6),
        }


class LogisticRanker:
    """Tiny deterministic logistic classifier for semantic API-pair ranking.

    All current features are normalized to [0, 1], so the model intentionally
    avoids external numerical dependencies. The trained coefficients are small
    enough to ship inside a Migration Brain pack.
    """

    def __init__(self, weights: Mapping[str, float] | None = None, bias: float = 0.0):
        self.weights = {name: float((weights or {}).get(name, 0.0)) for name in FEATURE_NAMES}
        self.bias = float(bias)

    @staticmethod
    def _sigmoid(value: float) -> float:
        value = max(-35.0, min(35.0, value))
        return 1.0 / (1.0 + math.exp(-value))

    def predict_proba(self, features: Mapping[str, float]) -> float:
        score = self.bias
        for name in FEATURE_NAMES:
            score += self.weights[name] * float(features.get(name, 0.0))
        return self._sigmoid(score)

    def fit(
        self,
        examples: Iterable[RankedExample],
        *,
        epochs: int = 700,
        learning_rate: float = 0.16,
        l2: float = 0.015,
    ) -> "LogisticRanker":
        rows = tuple(examples)
        if not rows:
            raise ValueError("No training examples were supplied.")
        if not any(row.label == 1 for row in rows) or not any(row.label == 0 for row in rows):
            raise ValueError("Training data must contain both positive and negative examples.")

        for _ in range(epochs):
            grad_bias = 0.0
            grad = {name: 0.0 for name in FEATURE_NAMES}
            total_weight = 0.0
            for row in rows:
                sample_weight = max(0.0, float(row.weight))
                if not sample_weight:
                    continue
                probability = self.predict_proba(row.features)
                error = (probability - float(row.label)) * sample_weight
                grad_bias += error
                total_weight += sample_weight
                for name in FEATURE_NAMES:
                    grad[name] += error * float(row.features.get(name, 0.0))

            if not total_weight:
                raise ValueError("Training data has zero effective sample weight.")

            self.bias -= learning_rate * grad_bias / total_weight
            for name in FEATURE_NAMES:
                regularized = grad[name] / total_weight + l2 * self.weights[name]
                self.weights[name] -= learning_rate * regularized
        return self

    def evaluate(self, examples: Iterable[RankedExample], threshold: float = 0.5) -> Evaluation:
        rows = tuple(examples)
        if not rows:
            return Evaluation(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        tp = tn = fp = fn = 0
        loss = 0.0
        total_weight = 0.0
        correct_weight = 0.0
        for row in rows:
            weight = max(0.0, float(row.weight))
            probability = min(1.0 - 1e-9, max(1e-9, self.predict_proba(row.features)))
            predicted = int(probability >= threshold)
            if predicted == row.label:
                correct_weight += weight
            total_weight += weight
            loss += -weight * (
                row.label * math.log(probability)
                + (1 - row.label) * math.log(1.0 - probability)
            )
            if predicted and row.label:
                tp += 1
            elif predicted and not row.label:
                fp += 1
            elif not predicted and row.label:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        return Evaluation(
            len(rows),
            correct_weight / total_weight if total_weight else 0.0,
            precision,
            recall,
            f1,
            loss / total_weight if total_weight else 0.0,
            tp,
            fp,
            tn,
            fn,
        )

    def as_dict(self) -> dict:
        return {
            "type": "logistic_semantic_ranker",
            "feature_names": list(FEATURE_NAMES),
            "weights": {name: round(self.weights[name], 10) for name in FEATURE_NAMES},
            "bias": round(self.bias, 10),
        }

    @classmethod
    def from_dict(cls, value: Mapping) -> "LogisticRanker":
        if value.get("type") != "logistic_semantic_ranker":
            raise ValueError(f"Unsupported brain ranker: {value.get('type')!r}")
        return cls(value.get("weights", {}), float(value.get("bias", 0.0)))
