import numpy as np
import pytest

from codedna import config
from codedna.analysis import evaluation as ev
from codedna.analysis.similarity import GROUPS, Corpus

RNG = np.random.default_rng(1)
SIZES = {"metrics": 8, "language": 12, "dependency": 64, "structure": 16, "evolution": 8,
         "semantic": 64}


def make_dna(repo_id, centre, noise=0.05, packages=()):
    """Fingerprint near a cluster centre. `centre` is a dict group -> vector."""
    raw = {g: list(np.array(centre[g]) + RNG.normal(0, noise, SIZES[g])) for g in GROUPS}
    return {"repo_id": repo_id, "packages": list(packages), "raw_vectors": raw}


@pytest.fixture(scope="module")
def clusters():
    centres = {c: {g: RNG.normal(0, 1, SIZES[g]) for g in GROUPS} for c in ("web", "cli", "data")}
    dnas, labels = [], {}
    for c, pk in (("web", ["flask", "jinja2"]), ("cli", ["click", "rich"]), ("data", ["numpy", "scipy"])):
        for i in range(3):
            rid = f"{c}/r{i}"
            dnas.append(make_dna(rid, centres[c], packages=pk))
            labels[rid] = c
    return dnas, labels


def test_score_equals_weighted_sum_of_group_cosines(clusters):
    dnas, _ = clusters
    corpus = Corpus(dnas)
    a, b = dnas[0]["repo_id"], dnas[4]["repo_id"]
    r = corpus.similarity(a, b)
    expected = sum(config.WEIGHTS[g] * r["per_group"][g] for g in GROUPS)
    assert r["score"] == pytest.approx(expected, abs=1e-3)
    i, j = corpus.index(a), corpus.index(b)
    assert float(corpus.matrix[i] @ corpus.matrix[j]) == pytest.approx(r["score"], abs=1e-3)


def test_self_similarity_is_sum_of_weights(clusters):
    dnas, _ = clusters
    corpus = Corpus(dnas)
    assert np.allclose(np.diag(corpus.score_matrix()), sum(config.WEIGHTS.values()))


def test_top_k_finds_same_cluster_and_excludes_self(clusters):
    dnas, _ = clusters
    corpus = Corpus(dnas)
    top = corpus.top_k("web/r0", 2)
    assert {t["repo"] for t in top} == {"web/r1", "web/r2"}
    assert all(t["repo"] != "web/r0" for t in corpus.top_k("web/r0", 8))


def test_score_matrix_is_symmetric(clusters):
    m = Corpus(clusters[0]).score_matrix()
    assert np.allclose(m, m.T)


def test_identical_repositories_score_the_maximum():
    centre = {g: RNG.normal(0, 1, SIZES[g]) for g in GROUPS}
    dnas = [make_dna("a/x", centre, noise=0), make_dna("b/y", centre, noise=0),
            make_dna("c/z", {g: RNG.normal(0, 1, SIZES[g]) for g in GROUPS})]
    r = Corpus(dnas).similarity("a/x", "b/y")
    assert r["score"] == pytest.approx(sum(config.WEIGHTS.values()), abs=1e-3)


def test_zero_variance_groups_do_not_produce_nan():
    base = {g: np.ones(SIZES[g]) for g in GROUPS}
    dnas = [make_dna(f"o/r{i}", base, noise=0) for i in range(3)]
    assert not np.isnan(Corpus(dnas).score_matrix()).any()


# ---- evaluation metrics, checked against hand-computed values

def test_rank_metrics_perfect_ranking():
    ids = ["a1", "a2", "b1", "b2"]
    labels = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    s = np.array([[0, .9, .1, .1], [.9, 0, .1, .1], [.1, .1, 0, .9], [.1, .1, .9, 0]])
    m, n = ev.rank_metrics(s, ids, labels)
    assert n == 4
    assert m["P@1"] == m["MRR"] == m["MAP"] == 1.0


def test_rank_metrics_hand_computed_case():
    # a1 ranks [b1, a2, a3] -> hits F,T,T: P@1=0, MRR=1/2, AP=(1/2 + 2/3)/2
    # a2 ranks [a1, a3, b1] -> hits T,T,F: P@1=1, MRR=1,   AP=1
    # a3 ranks [a1, a2, b1] -> hits T,T,F: P@1=1, MRR=1,   AP=1
    # b1 has no same-category peer and is skipped
    ids = ["a1", "a2", "a3", "b1"]
    labels = {"a1": "A", "a2": "A", "a3": "A", "b1": "B"}
    s = np.array([[0, .5, .4, .9],
                  [.9, 0, .5, .1],
                  [.9, .5, 0, .1],
                  [.1, .1, .1, 0]])
    m, n = ev.rank_metrics(s, ids, labels)
    assert n == 3
    assert m["P@1"] == pytest.approx((0 + 1 + 1) / 3, abs=1e-4)
    assert m["MRR"] == pytest.approx((0.5 + 1 + 1) / 3, abs=1e-4)
    assert m["MAP"] == pytest.approx((((1 / 2 + 2 / 3) / 2) + 1 + 1) / 3, abs=1e-4)


def test_rank_metrics_skips_singleton_categories():
    ids = ["a1", "a2", "solo"]
    labels = {"a1": "A", "a2": "A", "solo": "S"}
    _, n = ev.rank_metrics(np.eye(3), ids, labels)
    assert n == 2


def test_random_baseline_is_far_below_perfect(clusters):
    dnas, labels = clusters
    ids = [d["repo_id"] for d in dnas]
    b = ev.random_baseline(ids, labels, trials=50)
    assert b["P@1"] < 0.5 and b["MAP"] < 0.6


def test_run_evaluation_end_to_end_and_outputs(clusters, tmp_path):
    dnas, labels = clusters
    readmes = {d["repo_id"]: f"{d['repo_id'].split('/')[0]} project docs about "
                              f"{d['repo_id'].split('/')[0]}" for d in dnas}
    result = ev.run_evaluation(dnas, readmes, labels)
    rows = {r["method"]: r for r in result["rows"]}
    assert rows["Code DNA (all 6 groups, default weights)"]["MAP"] == 1.0
    assert rows["Random ranking (mean of 200 trials)"]["MAP"] < 0.8
    assert len(result["rows"]) == 2 + 6 + 6 + 3
    assert result["sensitivity"]["MAP_min"] <= result["sensitivity"]["MAP_mean"] <= result["sensitivity"]["MAP_max"]
    ev.write_outputs(result, str(tmp_path))
    for name in ("similarity_eval.csv", "similarity_eval.json", "weight_sensitivity.json",
                 "confusion_by_category.csv"):
        assert (tmp_path / name).stat().st_size > 0
    assert "Code DNA" in ev.format_table(result)
