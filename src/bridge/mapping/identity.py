"""Enterprise identity resolution: Halcyon per-facility PAT rows -> one person.

Deterministic links (exact name + DOB + SSN4, or an ADT A40 merge) are automatic. Probable
matches above REVIEW_THRESHOLD become identity_match questions for a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from ..normalize.legacy import fix_mojibake

AUTO_THRESHOLD = 0.95
REVIEW_THRESHOLD = 0.6
NICKNAMES = {"JIM": "JAMES", "BOB": "ROBERT", "MIKE": "MICHAEL", "MARIE": "MARY", "BILL": "WILLIAM"}


def _norm_name(raw: str) -> tuple[str, str]:
    s, _ = fix_mojibake(raw)
    last, _, rest = s.upper().partition(",")
    first = rest.split()[0] if rest.split() else ""
    clean = lambda t: re.sub(r"[^A-Z]", "", t)  # noqa: E731
    return clean(last), clean(first)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass
class Match:
    a: str
    b: str
    score: float
    reasons: list[str]


def score_pair(p: dict[str, str], q: dict[str, str]) -> Match:
    (la, fa), (lb, fb) = _norm_name(p["PAT_NAME"]), _norm_name(q["PAT_NAME"])
    s, why = 0.0, []
    if p["SSN4"] and p["SSN4"] == q["SSN4"]:
        s += 0.35; why.append("ssn4")
    if p["DOB"] == q["DOB"] and p["DOB"].strip("0"):
        s += 0.3; why.append("dob")
    elif len(p["DOB"]) == 8 and len(q["DOB"]) == 8 and p["DOB"][:4] == q["DOB"][:4] and _edit_distance(p["DOB"], q["DOB"]) <= 2:
        s += 0.15; why.append("dob~")
    if la == lb:
        s += 0.2; why.append("last")
    elif _edit_distance(la, lb) <= 2:
        s += 0.12; why.append("last~")
    if fa == fb:
        s += 0.15; why.append("first")
    elif NICKNAMES.get(fa, fa) == NICKNAMES.get(fb, fb) or (fa[:3] == fb[:3] and len(fa) > 2):
        s += 0.08; why.append("first~")
    return Match(p["PAT_ID"], q["PAT_ID"], round(s, 3), why)


class UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = sorted((self.find(a), self.find(b)))
        self.parent[rb] = ra


def resolve(pats: list[dict[str, str]], merges: list[tuple[str, str]],
            auto_merge: bool = True) -> tuple[dict[str, list[str]], list[Match], dict[str, str]]:
    """Return (clusters root->members, review candidates, link reason per non-root member).

    `merges` are (surviving PAT_ID, retired PAT_ID) pairs from ADT A40.

    With ``auto_merge=False`` (the generated profile's merge policy,
    ``route_to_reconciliation``), nothing is unioned automatically: every
    chart stays its own cluster, and every would-be automatic link —
    deterministic matches and A40 merges alike — is returned as a review
    candidate so a human decides it in reconciliation.
    """
    ids = [p["PAT_ID"] for p in pats]
    uf = UnionFind(ids)
    reason: dict[str, str] = {}
    review: dict[tuple[str, str], Match] = {}

    def add_review(m: Match) -> None:
        """Record a review candidate, merging with any candidate already
        held for the pair: keep the higher score and the union of reasons.
        An A40 merge is the strongest evidence a pair carries — a plain
        score match for the same pair must never overwrite it before the
        human reconciler sees it."""
        key = tuple(sorted((m.a, m.b)))
        held = review.get(key)
        if held is None:
            review[key] = m
            return
        reasons = list(held.reasons)
        for r in m.reasons:
            if r not in reasons:
                reasons.append(r)
        review[key] = Match(a=held.a, b=held.b,
                            score=max(held.score, m.score), reasons=reasons)

    by_id = {p["PAT_ID"]: p for p in pats}
    for keep, retire in merges:
        if keep in uf.parent and retire in uf.parent:
            if auto_merge:
                uf.union(keep, retire)
                reason[retire] = "adt_a40"
            else:
                m = score_pair(by_id[keep], by_id[retire])
                add_review(Match(a=m.a, b=m.b, score=max(m.score, 1.0),
                                 reasons=[*m.reasons, "adt_a40"]))
    blocks: dict[str, list[dict[str, str]]] = {}
    for p in pats:
        blocks.setdefault(p["SSN4"] or p["PAT_ID"], []).append(p)
        last, _ = _norm_name(p["PAT_NAME"])
        blocks.setdefault(f"N:{last[:4]}:{p['DOB'][:4]}", []).append(p)
    for group in blocks.values():
        for p, q in combinations(group, 2):
            if uf.find(p["PAT_ID"]) == uf.find(q["PAT_ID"]):
                continue
            m = score_pair(p, q)
            if auto_merge and m.score >= AUTO_THRESHOLD:
                uf.union(p["PAT_ID"], q["PAT_ID"])
                reason.setdefault(max(m.a, m.b), "deterministic")
            elif m.score >= REVIEW_THRESHOLD:
                add_review(m)
    clusters: dict[str, list[str]] = {}
    for i in ids:
        clusters.setdefault(uf.find(i), []).append(i)
    best: dict[tuple[str, str], Match] = {}
    for (a, b), m in sorted(review.items()):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        pair = tuple(sorted((ra, rb)))
        if pair not in best or m.score > best[pair].score:
            best[pair] = m
    return clusters, [best[k] for k in sorted(best)], reason


def summarize(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p.get(k) for k in ("PAT_ID", "MRN", "FAC_ID", "PAT_NAME", "DOB", "SEX", "SSN4", "ADDR")}
