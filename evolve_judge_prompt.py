#!/usr/bin/env python3
"""
evolve_judge_prompt.py - Evolve an LLM-as-a-judge prompt (genetic algorithm) that decides whether a
task description is correct, using reports produced by diff_tasks.py.

Env vars (OpenAI-compatible chat completions API):
  LLM_BASE_URL   e.g. https://host/v1          LLM_API_KEY
  JUDGE_MODEL    model used as judge            META_MODEL  model used to mutate/crossover prompts

Usage:
  python evolve_judge_prompt.py mbpp_report.json humaneval_report.json \
      --per-group 20 --pop 6 --generations 5 --batch 24 --outdir judge_run
"""
import argparse, hashlib, json, os, random, re, time, urllib.request
import sys, traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI

KNOWN_TYPES = {"ambiguity", "incompleteness", "contradiction", "correctness"}
TYPES = ["ambiguity", "incompleteness", "contradiction", "correctness", "none"]
LABEL_ALIASES = {"lv": "ambiguity", "lexical_vagueness": "ambiguity", "ambiguous": "ambiguity"}

OUTPUT_SPEC = """
Answer ONLY with a JSON object, no other text:
{"reasoning": "<max 80 words>", "verdict": "correct" | "incorrect",
 "issue_type": "none" | "ambiguity" | "incompleteness" | "contradiction" | "correctness"}
Use issue_type "none" if and only if verdict is "correct"."""

SEED_PROMPT = """You are an expert reviewer of programming task descriptions.
Decide whether the task description below is CORRECT, i.e. a developer could implement exactly one
well-defined behaviour from it. It is INCORRECT if it has one of these issues:
- ambiguity: the text allows several behaviours. This includes explicit alternatives ("odd or even",
  "minimum or maximum"), hedges ("a certain condition", "such as ..."), and lexical vagueness, where
  precise technical terms are replaced by generic words ("items", "group", "data", "related",
  "routine", "something", "a particular way") so that the exact data, operation or condition
  cannot be determined, even if the sentence structure looks fine.
- incompleteness: missing information needed to implement it (inputs, outputs, rules, conditions, cases).
- contradiction: statements that conflict with each other, with the signature/type hints or with the examples
  (e.g. incompatible return types, impossible constraints such as O(1) for a full scan, sort vs keep order).
- correctness: the description states something factually wrong or inconsistent with its own examples.
A description is CORRECT only if it is precise, complete, self-consistent and consistent with its
signature and examples, so that exactly one behaviour can be implemented. Judge the text on its own
merits: do not accept a description just because it sounds natural, and do not reject it only because
its wording is unusual. Check step by step: inputs, outputs, rules, edge cases, and consistency with
examples and signature.
"""

# ----------------------------------------------------------------- LLM client


def _post(url, headers, payload, retries=4):
    body = json.dumps(payload).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(url, body, headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code == 400 or i == retries - 1:   # do not retry client errors
                raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from None
            time.sleep(2 ** i)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def _is_reasoning_model(model):
    m = model.lower()
    return m.startswith(("o1", "o3", "o4", "gpt-5"))


def judge_chat(model, messages, temperature=0.0, max_tokens=1500):
    """GPT judge via the OpenAI Chat Completions API (or any compatible endpoint)."""
    client = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY")
            )
    response = client.chat.completions.parse(
        model=model,
        messages=messages
    )
    return response.choices[0].message.content


def claude_chat(model, system, user, temperature=0.9, max_tokens=2048):
    """Claude (prompt mutation / crossover) via the Anthropic Messages API."""
    client = Anthropic(
        base_url="https://gateway.pia.private.list.lu",
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    if not text.strip():
        print(f"No text block in response (stop_reason={response.stop_reason}, "
                           f"block types={[b.type for b in response.content]})")
        return ""
    return text


# ----------------------------------------------------------------- data
def dataset_of(tid):
    return "humaneval" if tid.lower().startswith("humaneval") else "mbpp"


def clean(prompt, ep):
    return re.sub(r"\bcandidate\b", ep or "candidate", prompt or "").strip()


def diff_summary(rep):
    """Compact view of the diff_tasks.py report, used ONLY as evolution feedback."""
    s, m = rep["structural_diff"], rep["semantic_diff"]
    return {"inline_diff": s["description_diff"]["inline_diff"][:600],
            "similarity": s["description_diff"]["similarity_ratio"],
            "embedding_cosine": m.get("embedding_cosine"),
            "signature_changes": {k: v for k, v in s["signature"].items() if v and k != "any"},
            "examples_removed": s["examples_removed"][:3], "examples_added": s["examples_added"][:3],
            "evidence": {k: v for k, v in m["evidence"].items() if v}}

def load_samples(paths, use_originals=True):
    samples, seen_orig = [], set()
    for p in paths:
        for rep in json.loads(Path(p).read_text(encoding="utf-8")):
            tid, ep = rep["task_id"], rep.get("entry_point")
            lab = LABEL_ALIASES.get(rep["issue_label"], rep["issue_label"])
            samples.append({"id": f"{tid}|{lab}", "task_id": tid, "dataset": dataset_of(tid),
                            "entry_point": ep, "text": clean(rep["variant_prompt"], ep),
                            "gold": "incorrect",
                            "gold_type": lab if lab in KNOWN_TYPES else "unknown",
                            "label": lab, "diff": diff_summary(rep)})
            if use_originals and tid not in seen_orig and rep.get("original_prompt"):
                seen_orig.add(tid)
                samples.append({"id": f"{tid}|original", "task_id": tid, "dataset": dataset_of(tid),
                                "entry_point": ep, "text": clean(rep["original_prompt"], ep),
                                "gold": "correct", "gold_type": "none", "label": "original",
                                "diff": None})
    return samples


def stratified_sample(samples, per_group, rng):
    groups = defaultdict(list)
    for s in samples:
        groups[(s["dataset"], s["label"])].append(s)
    out = []
    for g in groups.values():
        rng.shuffle(g)
        out += g[:per_group]
    return out


def split(samples, rng, fr=(0.5, 0.25)):
    """Split by task_id so a task and its variants never straddle train/val/test."""
    ids = sorted({s["task_id"] for s in samples}); rng.shuffle(ids)
    a, b = int(len(ids) * fr[0]), int(len(ids) * (fr[0] + fr[1]))
    part = {t: 0 if i < a else 1 if i < b else 2 for i, t in enumerate(ids)}
    sp = ([], [], [])
    for s in samples:
        sp[part[s["task_id"]]].append(s)
    return sp


# ----------------------------------------------------------------- judging
_cache = {}


def parse_json(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    try:
        d = json.loads(m.group(0))
        v = str(d.get("verdict", "")).lower()
        t = str(d.get("issue_type", "none")).lower()
        t = LABEL_ALIASES.get(t, t)
        return {"verdict": v if v in ("correct", "incorrect") else "invalid",
                "issue_type": t if t in TYPES else "none", "reasoning": str(d.get("reasoning", ""))[:400]}
    except Exception:
        return {"verdict": "invalid", "issue_type": "none", "reasoning": (txt or "")[:200]}


def judge_one(prompt, s, model):
    user = f"Dataset: {s['dataset']}\nFunction entry point: {s['entry_point']}\n\nTask description:\n<<<\n{s['text']}\n>>>"
    key = hashlib.md5((model + prompt + user).encode()).hexdigest()
    if key not in _cache:
        try:
            _cache[key] = parse_json(judge_chat(model, [{"role": "system", "content": prompt + "\n" + OUTPUT_SPEC},
                                                        {"role": "user", "content": user}]))
        except Exception as e:
            _cache[key] = {"verdict": "invalid", "issue_type": "none", "reasoning": f"API error: {e}"}
    return _cache[key]


def evaluate(prompt, samples, model, workers):
    with ThreadPoolExecutor(workers) as ex:
        preds = list(ex.map(lambda s: judge_one(prompt, s, model), samples))
    return metrics(samples, preds), list(zip(samples, preds))


def metrics(samples, preds):
    tp = tn = fp = fn = type_ok = n_inc = invalid = 0
    for s, p in zip(samples, preds):
        v = p["verdict"]
        if v == "invalid":
            invalid += 1; v = "correct" if s["gold"] == "incorrect" else "incorrect"  # invalid counts as wrong
        if s["gold"] == "incorrect":
            fn += v == "correct"; tp += v == "incorrect"
            if s["gold_type"] in KNOWN_TYPES:
                n_inc += 1
                type_ok += v == "incorrect" and p["issue_type"] == s["gold_type"]
        else:
            tn += v == "correct"; fp += v == "incorrect"
    rec_inc = tp / (tp + fn) if tp + fn else 0.0
    rec_cor = tn / (tn + fp) if tn + fp else 0.0
    bal = (rec_inc + rec_cor) / 2
    type_acc = type_ok / n_inc if n_inc else 0.0
    return {"fitness": round(0.8 * bal + 0.2 * type_acc, 4), "balanced_acc": round(bal, 4),
            "recall_incorrect": round(rec_inc, 4), "recall_correct": round(rec_cor, 4),
            "type_acc": round(type_acc, 4), "invalid": invalid, "n": len(samples)}


def breakdown(pairs):
    g = defaultdict(lambda: [0, 0])
    for s, p in pairs:
        ok = p["verdict"] == s["gold"]
        for k in (f"{s['dataset']}/{s['label']}", f"dataset:{s['dataset']}"):
            g[k][0] += ok; g[k][1] += 1
    return {k: f"{a}/{b}" for k, (a, b) in sorted(g.items())}


# ----------------------------------------------------------------- GA operators
META_SYS = ("You are an expert prompt engineer optimising an LLM-as-a-judge prompt that decides whether a programming "
            "task description is correct. Return ONLY the full new prompt text (instructions only; do not include "
            "any output-format/JSON specification, it is appended automatically). Do not mention specific task ids "
            "or copy example texts; generalise.")


def failure_block(pairs, k):
    bad = [(s, p) for s, p in pairs
           if p["verdict"] != s["gold"]
           or (s["gold"] == "incorrect" and s["gold_type"] in KNOWN_TYPES and p["issue_type"] != s["gold_type"])]
    random.shuffle(bad)
    out = []
    for s, p in bad[:k]:
        out.append(json.dumps({
            "task_description": s["text"][:900], "gold_verdict": s["gold"], "gold_issue_type": s["gold_type"],
            "judge_verdict": p["verdict"], "judge_issue_type": p["issue_type"], "judge_reasoning": p["reasoning"],
            "what_changed_vs_reference (diff analysis, NOT visible to judge)": s["diff"]}, ensure_ascii=False))
    return "\n".join(out) if out else "(no failures on this batch)"


def mutate(parent, pairs, k_fail, model):
    msg = (f"CURRENT JUDGE PROMPT:\n<<<\n{parent['text']}\n>>>\n\nMetrics on a batch: {parent['metrics']}\n\n"
           f"MISCLASSIFIED EXAMPLES with the diff analysis between the reference task and the variant "
           f"(the judge never sees the reference or the diff; use them to understand which concrete signals "
           f"distinguish each issue type, and which harmless paraphrases must NOT be flagged):\n{failure_block(pairs, k_fail)}\n\n"
           "Improve the prompt: fix the observed failure patterns by adding/refining concrete, general detection "
           "criteria, tie-break rules and a short checklist. Keep it under 500 words.")
    return claude_chat(model, META_SYS, msg, temperature=0.9, max_tokens=1800).strip()

def crossover(a, b, model):
    msg = (f"PROMPT A (fitness {a['metrics']['fitness']}):\n<<<\n{a['text']}\n>>>\n\nPROMPT B (fitness {b['metrics']['fitness']}):\n<<<\n{b['text']}\n>>>\n\n"
           "Combine the strongest elements of both into one coherent prompt, removing redundancy. Under 500 words.")
    return claude_chat(model, META_SYS, msg, temperature=0.7, max_tokens=1800).strip()

def tournament(pop, rng, k=3):
    return max(rng.sample(pop, min(k, len(pop))), key=lambda x: x["metrics"]["fitness"])


# ----------------------------------------------------------------- main loop
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--per-group", type=int, default=20, help="max samples per (dataset,label) group")
    ap.add_argument("--pop", type=int, default=6)
    ap.add_argument("--generations", type=int, default=5)
    ap.add_argument("--batch", type=int, default=24, help="train minibatch per generation")
    ap.add_argument("--elite", type=int, default=2)
    ap.add_argument("--crossover-rate", type=float, default=0.3)
    ap.add_argument("--fail-k", type=int, default=6)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-originals", action="store_true")
    ap.add_argument("--seed-prompt-file")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--outdir", default="judge_run")
    a = ap.parse_args()

    rng = random.Random(a.seed); random.seed(a.seed)
    # judge_m, meta_m = os.environ.get("JUDGE_MODEL"), os.environ.get("META_MODEL")
    judge_m, meta_m = "gpt-6-luna", "claude-sonnet-5"
    missing = [k for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")#, "JUDGE_MODEL", "META_MODEL")
               if not os.environ.get(k)]
    if missing:
        ap.error("missing environment variables: " + ", ".join(missing))


    out = Path(a.outdir); out.mkdir(exist_ok=True)

    samples = load_samples(a.reports, not a.no_originals)
    samples = stratified_sample(samples, a.per_group, rng)
    train, val, test = split(samples, rng)
    print(f"samples={len(samples)} train={len(train)} val={len(val)} test={len(test)}")
    if not train:
        raise SystemExit("no training samples")

    seed = Path(a.seed_prompt_file).read_text() if a.seed_prompt_file else SEED_PROMPT
    pop = [{"id": "g0-seed", "text": seed, "parent": None}]
    while len(pop) < a.pop:  # diversify the initial population
        try:
            pop.append({"id": f"g0-{len(pop)}", "text": mutate({"text": seed, "metrics": {}}, [], 0, meta_m), "parent": "seed"})
        except Exception as e:
            traceback.print_exc()
            print("init mutation failed:", e)
            pop.append({"id": f"g0-{len(pop)}", "text": seed, "parent": "seed"})

    log = []
    for g in range(a.generations + 1):
        batch = rng.sample(train, min(a.batch, len(train)))  # same batch for all individuals (fair comparison)
        for ind in pop:
            ind["metrics"], ind["pairs"] = evaluate(ind["text"], batch, judge_m, a.workers)
        pop.sort(key=lambda x: -x["metrics"]["fitness"])
        log.append({"generation": g, "individuals": [{"id": i["id"], "parent": i["parent"], "metrics": i["metrics"],
                                                      "prompt": i["text"]} for i in pop]})
        print(f"gen {g}: best={pop[0]['metrics']}")
        (out / "evolution_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        if g == a.generations:
            break
        nxt = pop[:a.elite]
        while len(nxt) < a.pop:
            try:
                if rng.random() < a.crossover_rate and len(pop) > 1:
                    p1, p2 = tournament(pop, rng), tournament(pop, rng)
                    child = {"text": crossover(p1, p2, meta_m), "parent": f"{p1['id']}+{p2['id']}"}
                else:
                    p = tournament(pop, rng)
                    child = {"text": mutate(p, p["pairs"], a.fail_k, meta_m), "parent": p["id"]}
                child["id"] = f"g{g+1}-{len(nxt)}"
                nxt.append(child)
            except Exception as e:
                traceback.print_exc()
                print("operator failed:", e)
        pop = nxt

    # model selection on validation (full), then one-shot report on test
    cands = pop[:3]
    for c in cands:
        c["val"], _ = evaluate(c["text"], val or train, judge_m, a.workers)
    best = max(cands, key=lambda c: c["val"]["fitness"])
    test_m, test_pairs = evaluate(best["text"], test, judge_m, a.workers) if test else (None, [])
    seed_test, _ = evaluate(seed, test, judge_m, a.workers) if test else (None, None)
    final = best["text"] + "\n" + OUTPUT_SPEC
    (out / "best_judge_prompt.txt").write_text(final, encoding="utf-8")
    (out / "final_report.json").write_text(json.dumps({
        "best_id": best["id"], "validation": best["val"], "test": test_m, "seed_prompt_test": seed_test,
        "test_breakdown": breakdown(test_pairs)}, indent=2), encoding="utf-8")
    print("best:", best["id"], "val:", best["val"], "test:", test_m, "seed on test:", seed_test)
    print(f"Wrote {out/'best_judge_prompt.txt'}")


if __name__ == "__main__":
    main()