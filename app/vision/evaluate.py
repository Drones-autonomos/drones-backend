"""Evaluación de precisión, tasa de falsos positivos y ajuste de umbrales."""

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np

from app.vision.detector import VisionDetection


@dataclass(slots=True)
class LabeledSample:
    """Muestra etiquetada para evaluación offline de un detector."""

    frame: np.ndarray
    expected_present: bool
    label: str = "HUMO"
    name: str = "sample"


@dataclass(slots=True)
class EvaluationMetrics:
    """Métricas de clasificación binaria sobre muestras independientes."""

    threshold: float
    total_samples: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_detector(
    samples: list[LabeledSample],
    detect_fn: Callable[[np.ndarray], list[VisionDetection]],
    *,
    threshold: float = 0.65,
    target_label: str | None = None,
) -> EvaluationMetrics:
    """Evalúa precisión, recall y falsos positivos para un umbral dado."""
    tp = fp = tn = fn = 0
    for sample in samples:
        label = (target_label or sample.label).upper()
        detections = [
            det for det in detect_fn(sample.frame) if det.tipo.upper() == label and det.confianza >= threshold
        ]
        predicted = len(detections) > 0
        if sample.expected_present and predicted:
            tp += 1
        elif not sample.expected_present and predicted:
            fp += 1
        elif not sample.expected_present and not predicted:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return EvaluationMetrics(
        threshold=round(threshold, 4),
        total_samples=len(samples),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        false_positive_rate=round(fpr, 4),
    )


def tune_threshold(
    samples: list[LabeledSample],
    detect_fn: Callable[[np.ndarray], list[VisionDetection]],
    *,
    thresholds: list[float] | None = None,
    target_label: str | None = None,
) -> tuple[float, list[EvaluationMetrics]]:
    """Barre umbrales candidatos y selecciona el que maximiza F1 (desempate por menor FPR)."""
    candidates = thresholds or [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    reports = [evaluate_detector(samples, detect_fn, threshold=t, target_label=target_label) for t in candidates]
    best = max(reports, key=lambda m: (m.f1_score, -m.false_positive_rate, m.precision))
    return best.threshold, reports
