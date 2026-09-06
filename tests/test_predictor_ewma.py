from src.predictor.predictor.ewma import EWMAModel


def test_predict_unknown_bucket_returns_zero():
    m = EWMAModel(alpha=0.3)
    assert m.predict(19) == 0.0


def test_update_converges_toward_repeated_count():
    m = EWMAModel(alpha=0.5)
    m.update(19, 0)
    v1 = m.update(19, 10)
    v2 = m.update(19, 10)
    assert v1 == 5.0
    assert v2 == 7.5
    assert m.predict(19) == 7.5


def test_buckets_are_independent():
    m = EWMAModel(alpha=0.5)
    m.update(19, 10)
    assert m.predict(3) == 0.0
    assert m.to_histogram() == {19: 5.0}
