"""부분관측 마르코프 결정과정: the diffusion *phase* of a keyword is hidden; the daily verdict observes it.

`diffusion.classify()` reads a 17-week window and names one stage. It has no memory: a keyword sitting
on a threshold (boom 1.6×, active 50%, lag 2 weeks) flips stage from one day to the next, and every
flip re-fires an alert. Here the stage is treated as what it is — a noisy observation of a phase that
changes slowly — and each keyword carries a belief over phases that is updated by Bayes' rule.

    b'(s) ∝ O(o | s) · Σ_s' T(s | s') · b(s')            (predict with T, correct with O)

  states   PHASES   휴면 → 청년 상승 → 확산 → 퇴조 → 휴면 ; 휴면 → 전 연령 → 퇴조 (a news shock)
  observations      the six verdicts of diffusion.classify()
  T, O              weekly transition / emission matrices; started from PRIOR_T / PRIOR_O and
                    re-estimated every run by Baum-Welch on the walk-forward verdict sequences (fit)
  actions           gate(): let a stage alert through only when the belief agrees (≥ GATE);
                    plan(): which keywords get a search-data request next run — hold the ones whose
                    phase is undecided, rest the ones that have settled into 휴면

Pure Python (5 × 6 matrices). Nothing here creates information: filtering smooths the same
observations over time. Its promise is fewer flips, measured as `flips()` on the backtest, and its
accuracy is scored next to the raw verdict (diffusion.track → belief_accuracy). docs/POMDP.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

PHASES = ("휴면", "청년 상승", "확산", "전 연령", "퇴조")
VERDICTS = ("확산 대기", "확산 중", "윗세대 상승", "전 연령 동시", "지나감", "상시 관심")
WEEK = 7  # one transition step

# Weekly transitions. Heavy diagonal (a phase lasts weeks); forward moves carry most of the rest.
PRIOR_T: list[list[float]] = [
    # 휴면    청년    확산    전연령  퇴조
    [0.930, 0.030, 0.005, 0.030, 0.005],  # 휴면
    [0.020, 0.800, 0.100, 0.010, 0.070],  # 청년 상승
    [0.010, 0.010, 0.850, 0.010, 0.120],  # 확산
    [0.030, 0.010, 0.010, 0.750, 0.200],  # 전 연령
    [0.170, 0.010, 0.010, 0.010, 0.800],  # 퇴조
]
# P(verdict | phase): the confusion matrix of the rule. The argmax of each row *defines* the phase.
PRIOR_O: list[list[float]] = [
    # 대기    중      윗세대  동시    지나감  상시
    [0.060, 0.010, 0.030, 0.030, 0.120, 0.750],  # 휴면
    [0.650, 0.050, 0.020, 0.050, 0.080, 0.150],  # 청년 상승
    [0.100, 0.450, 0.300, 0.100, 0.030, 0.020],  # 확산
    [0.050, 0.100, 0.100, 0.600, 0.100, 0.050],  # 전 연령
    [0.030, 0.030, 0.050, 0.050, 0.700, 0.140],  # 퇴조
]
PRIOR_PI: list[float] = [0.60, 0.15, 0.08, 0.07, 0.10]
PRIOR_WEIGHT = 20.0  # Dirichlet pseudo-counts per row: the prior is worth 20 observed transitions
GATE = 0.5  # alert phases need at least this much belief
ALERT_PHASES = ("청년 상승", "확산")
HOLD = 0.35  # P(청년 상승) + P(확산) at or above this keeps a keyword on the watch list
HOLD_SHARE = 0.5  # ... but held keywords never take more than this share of the budget
SETTLED = 0.90  # P(휴면) at or above this ...
SETTLED_STREAK = 3  # ... for this many consecutive updates = settled
REST_DAYS = 7  # a settled keyword is re-measured this often
STALE_DAYS = 14  # a belief older than this no longer holds a slot

Matrix = list[list[float]]


# --- linear algebra (tiny) ------------------------------------------------------------------
def _matmul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]


def _identity(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _normalise(row: Sequence[float]) -> list[float]:
    s = sum(row)
    return [v / s for v in row] if s > 0 else [1.0 / len(row)] * len(row)


def transition_over(days: int, T: Matrix | None = None) -> Matrix:
    """T applied for `days`: one full power per week, and the remainder as a linear mix with the
    identity (a day is a seventh of a week's worth of change)."""
    T = T or PRIOR_T
    n = len(T)
    out = _identity(n)
    for _ in range(max(days, 0) // WEEK):
        out = _matmul(out, T)
    rest = max(days, 0) % WEEK
    if rest:
        a = rest / WEEK
        part = [[(1 - a) * (1.0 if i == j else 0.0) + a * T[i][j] for j in range(n)] for i in range(n)]
        out = _matmul(out, part)
    return out


# --- model ---------------------------------------------------------------------------------
@dataclass
class Model:
    T: Matrix
    O: Matrix
    sequences: int = 0  # how many verdict sequences the fit saw
    label_locked: bool = False  # True = EM tried to rename a phase; the prior was kept instead
    log_likelihood: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"phases": list(PHASES), "verdicts": list(VERDICTS), "sequences": self.sequences,
                "label_locked": self.label_locked,
                "transition": [[round(v, 3) for v in row] for row in self.T],
                "emission": [[round(v, 3) for v in row] for row in self.O]}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Model":
        if not d or "transition" not in d:
            return cls(PRIOR_T, PRIOR_O)
        T = [_normalise(r) for r in d["transition"]]
        O = [_normalise(r) for r in d["emission"]]
        if len(T) != len(PHASES) or len(O[0]) != len(VERDICTS) or not _labels_ok(O):
            return cls(PRIOR_T, PRIOR_O)
        return cls(T, O, d.get("sequences", 0), d.get("label_locked", False))


DEFAULT = Model(PRIOR_T, PRIOR_O)


def _labels_ok(O: Matrix) -> bool:
    """Each phase keeps the verdict it was named after as its most likely emission."""
    return all(max(range(len(VERDICTS)), key=lambda j: O[i][j]) == max(range(len(VERDICTS)), key=lambda j: PRIOR_O[i][j])
               for i in range(len(PHASES)))


def fit(sequences: list[list[int]], iterations: int = 20, prior_weight: float = PRIOR_WEIGHT) -> Model:
    """Baum-Welch with Dirichlet priors (PRIOR_T / PRIOR_O × prior_weight as pseudo-counts). The
    initial distribution stays PRIOR_PI. If the data would rename a phase, the prior is returned."""
    seqs = [s for s in sequences if s]
    if not seqs:
        return Model(PRIOR_T, PRIOR_O)
    n, m = len(PHASES), len(VERDICTS)
    T = [row[:] for row in PRIOR_T]
    O = [row[:] for row in PRIOR_O]
    ll = None
    for _ in range(iterations):
        cT = [[prior_weight * PRIOR_T[i][j] for j in range(n)] for i in range(n)]
        cO = [[prior_weight * PRIOR_O[i][j] for j in range(m)] for i in range(n)]
        ll = 0.0
        for obs in seqs:
            L = len(obs)
            alpha, scale = [], []
            a = [PRIOR_PI[i] * O[i][obs[0]] for i in range(n)]
            c = sum(a) or 1e-300
            alpha.append([v / c for v in a]); scale.append(c)
            for t in range(1, L):
                a = [O[j][obs[t]] * sum(alpha[-1][i] * T[i][j] for i in range(n)) for j in range(n)]
                c = sum(a) or 1e-300
                alpha.append([v / c for v in a]); scale.append(c)
            beta = [[1.0] * n for _ in range(L)]
            for t in range(L - 2, -1, -1):
                beta[t] = [sum(T[i][j] * O[j][obs[t + 1]] * beta[t + 1][j] for j in range(n)) / scale[t + 1] for i in range(n)]
            for t in range(L):
                g = _normalise([alpha[t][i] * beta[t][i] for i in range(n)])
                for i in range(n):
                    cO[i][obs[t]] += g[i]
                if t + 1 < L:
                    xi = [[alpha[t][i] * T[i][j] * O[j][obs[t + 1]] * beta[t + 1][j] for j in range(n)] for i in range(n)]
                    z = sum(map(sum, xi)) or 1e-300
                    for i in range(n):
                        for j in range(n):
                            cT[i][j] += xi[i][j] / z
            ll += sum(math.log(c) for c in scale)
        T = [_normalise(r) for r in cT]
        O = [_normalise(r) for r in cO]
    if not _labels_ok(O):
        return Model(PRIOR_T, PRIOR_O, len(seqs), label_locked=True, log_likelihood=ll)
    return Model(T, O, len(seqs), log_likelihood=ll)


# --- belief ----------------------------------------------------------------------------------
def _verdict_index(v: int | str) -> int:
    return v if isinstance(v, int) else VERDICTS.index(v)


@dataclass(frozen=True)
class Belief:
    b: tuple[float, ...]
    updated: str | None = None  # ISO day of the last observation
    streak: int = 0  # consecutive updates that kept the same phase

    @classmethod
    def initial(cls) -> "Belief":
        return cls(tuple(PRIOR_PI))

    @property
    def phase(self) -> str:
        return PHASES[max(range(len(PHASES)), key=lambda i: self.b[i])]

    @property
    def confidence(self) -> float:
        return max(self.b)

    @property
    def pending(self) -> float:
        """Mass on the phases where a decision is still open."""
        return sum(self.b[PHASES.index(p)] for p in ALERT_PHASES)

    @property
    def settled(self) -> bool:
        return self.b[0] >= SETTLED and self.streak >= SETTLED_STREAK

    def predict(self, days: int, model: Model | None = None) -> "Belief":
        Td = transition_over(days, (model or DEFAULT).T)
        n = len(PHASES)
        b = _normalise([sum(self.b[i] * Td[i][j] for i in range(n)) for j in range(n)])
        return Belief(tuple(b), self.updated, self.streak)

    def update(self, verdict: int | str, days: int, model: Model | None = None) -> "Belief":
        """One observation after `days`. A verdict read a day after the last one is mostly the same
        17-week window read again, so its likelihood is tempered to (days / 7) of a weekly one — the
        same fraction the transition gets. A gap longer than a week is still just one observation."""
        model = model or DEFAULT
        o = _verdict_index(verdict)
        prior = self.predict(days, model)
        w = min(max(days, 0), WEEK) / WEEK
        b = _normalise([prior.b[i] * model.O[i][o] ** w for i in range(len(PHASES))])
        nxt = Belief(tuple(b), self.updated, 0)
        streak = self.streak + 1 if nxt.phase == self.phase else 1
        return Belief(tuple(b), self.updated, streak)

    def stamp(self, day: date) -> "Belief":
        return Belief(self.b, day.isoformat(), self.streak)

    def days_since(self, today: date) -> int | None:
        return (today - date.fromisoformat(self.updated)).days if self.updated else None

    def to_dict(self) -> dict[str, Any]:
        return {"b": [round(v, 4) for v in self.b], "phase": self.phase, "confidence": round(self.confidence, 3),
                "pending": round(self.pending, 3), "updated": self.updated, "streak": self.streak}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Belief":
        b = list(d.get("b", []))
        if len(b) != len(PHASES) or min(b) < 0 or sum(b) <= 0:
            b = list(PRIOR_PI)
        elif abs(sum(b) - 1) > 1e-3:  # stored rounded to 4 decimals: leave a near-1 sum alone
            b = _normalise(b)
        return cls(tuple(b), d.get("updated"), int(d.get("streak", 0)))


# --- evaluation on a verdict sequence (weekly, causal) ------------------------------------------
def filter_beliefs(verdicts: Sequence[int | str], model: Model | None = None) -> list[Belief]:
    """Belief after each weekly verdict, using only verdicts up to that week."""
    b = Belief.initial()
    out = []
    for v in verdicts:
        b = b.update(v, WEEK, model)
        out.append(b)
    return out


def filter_sequence(verdicts: Sequence[int | str], model: Model | None = None) -> list[str]:
    return [b.phase for b in filter_beliefs(verdicts, model)]


ALERT_VERDICTS = ("확산 대기", "확산 중", "윗세대 상승")  # = alerts.STAGE_ALERTS


def simulate_alerts(verdicts: Sequence[int | str], model: Model | None = None) -> tuple[list[int], list[int]]:
    """Week indices at which each policy would alert on this sequence: the raw rule (alert stage
    entered, i.e. differs from last week's verdict) and the gated one (alerts.evaluate: same, but
    only while the belief agrees, remembering the last stage it let through)."""
    names = [VERDICTS[_verdict_index(v)] for v in verdicts]
    raw, gated = [], []
    last_gated: str | None = None
    for t, (v, b) in enumerate(zip(names, filter_beliefs(verdicts, model))):
        if v in ALERT_VERDICTS and (t == 0 or names[t - 1] != v):
            raw.append(t)
        if gate(b):
            if v in ALERT_VERDICTS and last_gated != v:
                gated.append(t)
            last_gated = v
        else:
            last_gated = None
    return raw, gated


def weekly_sequences(daily: dict[str, list[tuple[date, int | str]]], min_weeks: int = 2) -> list[list[int]]:
    """Daily (day, verdict) records per keyword -> one verdict per ISO week (the week's last day),
    split into separate sequences wherever a week is missing. Feeds `fit` with what the archive
    accumulates day after day, so the model keeps learning beyond one backtest window."""
    out: list[list[int]] = []
    for rows in daily.values():
        by_week: dict[date, int] = {}
        for day, v in sorted(rows, key=lambda r: r[0]):
            by_week[day - timedelta(days=day.weekday())] = _verdict_index(v)
        run: list[int] = []
        prev: date | None = None
        for wk in sorted(by_week):
            if prev is not None and (wk - prev).days != WEEK:
                if len(run) >= min_weeks:
                    out.append(run)
                run = []
            run.append(by_week[wk])
            prev = wk
        if len(run) >= min_weeks:
            out.append(run)
    return out


def flips(seq: Sequence[Any]) -> int:
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


# --- actions ------------------------------------------------------------------------------------
def gate(belief: Belief | None) -> bool:
    """Should a stage alert for this keyword go out? Without a belief, yes (the old behaviour)."""
    if belief is None:
        return True
    return belief.phase in ALERT_PHASES and belief.confidence >= GATE


def plan(beliefs: dict[str, Belief], candidates: list[str], pinned: list[str], limit: int, today: date) -> list[str]:
    """Which keywords to spend search-data requests on: pinned, then keywords whose phase is still
    undecided (held even when they left the youth lists), then the candidates in their own order —
    skipping settled keywords measured within REST_DAYS."""
    out = list(dict.fromkeys(pinned))

    def fresh(b: Belief) -> bool:
        d = b.days_since(today)
        return d is not None and d <= STALE_DAYS

    held = sorted((k for k, b in beliefs.items() if k not in out and fresh(b) and b.pending >= HOLD),
                  key=lambda k: -beliefs[k].pending)
    out += held[: int(limit * HOLD_SHARE)]
    for k in candidates:
        if len(out) >= limit:
            break
        if k in out:
            continue
        b = beliefs.get(k)
        if b and b.settled and (b.days_since(today) or 0) < REST_DAYS:
            continue
        out.append(k)
    for k in candidates:  # fill any slots left by resting keywords
        if len(out) >= limit:
            break
        if k not in out:
            out.append(k)
    return out[:limit]
