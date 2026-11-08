import threading

import pytest

from app.capacity import Capacity


def test_claims_stop_at_the_limit_and_free_on_release():
    cap = Capacity(2)
    a, b = cap.try_claim(), cap.try_claim()
    assert a and b and cap.try_claim() is None and cap.usage().busy
    assert a.release()
    assert cap.try_claim() is not None


def test_a_stopping_worker_still_holds_its_slot():
    cap = Capacity(1)
    claim = cap.try_claim()
    claim.stopping()
    usage = cap.usage()
    assert claim.state == "stopping" and usage.stopping == 1 and usage.running == 0
    assert cap.try_claim() is None
    claim.release()
    assert claim.state == "stopped" and cap.try_claim() is not None


def test_release_happens_exactly_once():
    cap = Capacity(1)
    claim = cap.try_claim()
    assert claim.release() and not claim.release()
    other = cap.try_claim()
    claim.release()
    assert cap.try_claim() is None and other.state == "running"


def test_stopping_after_release_does_not_reopen_the_claim():
    cap = Capacity(1)
    claim = cap.try_claim()
    claim.release()
    claim.stopping()
    assert claim.state == "stopped"


def test_concurrent_claims_never_exceed_the_limit():
    cap = Capacity(5)
    start = threading.Barrier(20)
    won = []

    def grab():
        start.wait()
        claim = cap.try_claim()
        if claim:
            won.append(claim)

    threads = [threading.Thread(target=grab) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 5 and cap.usage().running == 5


def test_a_zero_limit_is_refused():
    with pytest.raises(ValueError):
        Capacity(0)
