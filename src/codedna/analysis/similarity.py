"""Step 9: fingerprints and repository similarity.

Each sub-vector is scaled across the corpus (z-score for the metric-like groups), L2
normalised, multiplied by sqrt(weight) and concatenated. The dot product of two
fingerprints is then exactly the weighted sum of the per-group cosine similarities,
so a single inner-product index (FAISS later) returns the final score.
"""
import numpy as np

from codedna import config

GROUPS = ("metrics", "language", "dependency", "structure", "evolution", "semantic")
ZSCORE_GROUPS = ("metrics", "evolution")


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class Corpus:
    """All repositories' fingerprints, ready for comparison.

    `dnas` is a list of dicts with repo_id, packages and raw_vectors (the shape
    stored in MongoDB), so a Corpus can be rebuilt from the database alone.
    """

    def __init__(self, dnas: list, weights: dict = None):
        self.weights = dict(weights or config.WEIGHTS)
        self.ids = [d["repo_id"] for d in dnas]
        self.packages = {d["repo_id"]: set(d["packages"]) for d in dnas}
        raw = {g: np.array([d["raw_vectors"][g] for d in dnas], dtype=float) for g in GROUPS}
        self.unit = {}
        for g in GROUPS:
            m = raw[g]
            if g in ZSCORE_GROUPS:
                sd = m.std(axis=0)
                sd[sd == 0] = 1.0
                m = (m - m.mean(axis=0)) / sd
            self.unit[g] = np.array([_unit(r) for r in m])
        self.matrix = self._concat(self.weights)

    def _concat(self, weights: dict) -> np.ndarray:
        return np.hstack([np.sqrt(weights[g]) * self.unit[g] for g in GROUPS])

    def index(self, repo_id: str) -> int:
        return self.ids.index(repo_id)

    def similarity(self, a: str, b: str) -> dict:
        """Overall score plus the cosine similarity of each group, so a result is explainable."""
        i, j = self.index(a), self.index(b)
        per_group = {g: float(self.unit[g][i] @ self.unit[g][j]) for g in GROUPS}
        total = sum(self.weights[g] * per_group[g] for g in GROUPS)
        pa, pb = self.packages[a], self.packages[b]
        jaccard = len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0
        return {"a": a, "b": b, "score": round(total, 4),
                "per_group": {g: round(v, 4) for g, v in per_group.items()},
                "package_jaccard": round(jaccard, 4)}

    def top_k(self, repo_id: str, k: int = 5) -> list:
        i = self.index(repo_id)
        scores = self.matrix @ self.matrix[i]
        order = np.argsort(-scores, kind="stable")
        return [{"repo": self.ids[j], "score": round(float(scores[j]), 4)}
                for j in order if j != i][:k]

    def score_matrix(self, weights: dict = None) -> np.ndarray:
        """n x n matrix of overall scores, optionally under different weights."""
        m = self._concat(weights) if weights else self.matrix
        return m @ m.T
