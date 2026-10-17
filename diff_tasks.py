#!/usr/bin/env python3
"""
diff_tasks.py - Compare reference task descriptions (HumanEval / MBPP style JSONL/JSON)
with degraded variants and explain the structural and semantic differences.
Only the 'prompt' and 'entry_point' fields are used (test_cases / reference_prompt are ignored).

Issue label is taken from the variant file name:
  *_ambiguous*, *_incomplete*, *_contradict*(ion|ory), *_correctness*/*_incorrect*

Usage:
  python diff_tasks.py humaneval_original.jsonl humaneval_wu_ambiguous.jsonl \
        humaneval_larbi_contradictory.jsonl humaneval_larbi_incomplete.jsonl \
        -o report.json --md report.md
  python diff_tasks.py --reference humaneval_original.jsonl variant1.jsonl variant2.jsonl
Options:
  --embeddings   add sentence-transformers cosine (optional dependency)
"""
import argparse, ast, difflib, json, math, re
from collections import Counter
from pathlib import Path

LABELS = {"ambiguous": "ambiguity", "ambiguity": "ambiguity",
          "incomplete": "incompleteness", "incompleteness": "incompleteness",
          "contradiction": "contradiction", "contradictory": "contradiction",
          "correctness": "correctness", "incorrect": "correctness"}

VAGUE = {"something", "certain", "particular", "special", "specific", "some", "group", "groups",
         "items", "item", "entries", "collection", "data", "values", "thing", "kind", "kinds",
         "way", "rule", "property", "pieces", "parts", "shape", "figure", "text", "sequence",
         "mapping", "information", "pattern", "symbols", "similar", "around", "another", "other",
         "type", "types", "technique", "tool", "simple", "related", "roughly", "condition"}
TECH = {"tuple", "tuples", "list", "lists", "array", "set", "dictionary", "string", "strings",
        "regex", "lambda", "heap", "sorted", "sort", "triangle", "trapezium", "prime", "factorial",
        "binary", "decimal", "uppercase", "lowercase", "substring", "sum", "product", "frequency",
        "minimum", "maximum", "largest", "smallest", "greatest", "shortest", "longest", "length",
        "area", "volume", "palindrome", "palindromic", "prefixes", "prefix", "suffixes", "divisor",
        "digits", "digit", "even", "odd", "ascending", "descending", "positive", "negative",
        "integers", "integer", "inclusive", "vowels", "nth", "mean", "median", "average", "absolute"}
CONSTRAINT_WORDS = {"all", "every", "only", "each", "exactly", "same", "never", "always", "below",
                    "above", "least", "most", "first", "last", "distinct", "positive", "negative",
                    "non", "empty", "unique", "consecutive", "inclusive", "otherwise", "if", "not",
                    "between", "equal", "greater", "less", "than", "none", "nearest", "sorted"}
NEGATIONS = {"not", "no", "never", "without", "neither", "nor", "except", "non"}
ANTONYMS = [("minimum", "maximum"), ("smallest", "largest"), ("lowest", "highest"),
            ("shortest", "longest"), ("first", "last"), ("odd", "even"), ("upper", "lower"),
            ("uppercase", "lowercase"), ("positive", "negative"), ("sum", "product"),
            ("add", "subtract"), ("increasing", "decreasing"), ("ascending", "descending"),
            ("below", "above"), ("more", "less"), ("encoded", "decoded"), ("prefix", "suffix"),
            ("prefixes", "suffixes"), ("with", "without"), ("smaller", "larger"),
            ("binary", "hexadecimal"), ("true", "false")]

# constraints that are typically *injected* in contradictory variants
CONSTRAINTS = {
    "complexity requirement": r"\bO\(\w*\)|\bo\(\w*\)|time complexity|complexity",
    "no loops/recursion": r"(not|no|without)\s+(use\s+|using\s+)?(any\s+)?(type of\s+)?(loops?|recursion|iterative)",
    "no built-ins": r"in-?built|built-in",
    "extra input types": r"(work|support|handle)s?\s+(for\s+|with\s+)?(both\s+|also\s+)?(strings?|lists?|numeric|integers?|negative)",
    "ordering rule": r"\b(sort\w*|ascending|descending|original order|maintain\w*)\b",
    "meta-contradiction wording": r"\b(however|contradicts?|according to the (first|second)|but also|simultaneously|at the same time|instead of)\b",
}
ORDER_KEEP = re.compile(r"(maintain|keep|preserve)\w*\s+(the\s+)?(original\s+)?order", re.I)
SORTING = re.compile(r"\bsort\w*|\bascending|\bdescending", re.I)
HEDGE = re.compile(r"\be\.g\.|such as|or another|or other|certain|specific condition|roughly|around|similar", re.I)
TYPE_WORDS = {"string": "str", "str": "str", "text": "str", "integer": "int", "int": "int",
              "list": "list", "array": "list", "tuple": "tuple", "float": "float",
              "bool": "bool", "boolean": "bool"}
RET_RE = re.compile(r"\b(?:return|returns|returned|output|result)\b[^.\n]{0,60}?\b"
                    r"(string|str|text|integer|int|list|array|tuple|float|boolean|bool)\b", re.I)

TOKEN_RE = re.compile(r"[A-Za-z_]+|\d+(?:\.\d+)?|[^\sA-Za-z_\d]")
WORD_RE = re.compile(r"[a-z_]+|\d+(?:\.\d+)?")
DEF_RE = re.compile(r"\bdef\s+(\w+)\s*(?:\((.*?)\))?\s*(?:->\s*([^:\n]+?))?\s*:", re.S)
DOC_RE = re.compile(r'("""|\'\'\')(.*?)(\1|\Z)', re.S)
EX_LINE = re.compile(r">>>|==|=>|\u279e|^(Input|Output|Explanation|Example)|^For\s+\w+\s*="
                     r"|\w+\(.*\)\s*(returns|should return|#|->|=)", re.I)
OR_RE = re.compile(r"\b\w+(?:\s*,\s*\w+)*\s+or\s+\w+(?:\s+or\s+\w+)*", re.I)
HEADING_RE = re.compile(r"^(note|notes|example|examples|constraints?|restrictions?|variables|output)\b", re.I)


# ------------------------------------------------------------------ IO
def load_records(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
        data = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        data = []
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[warn] {path}:{i}: invalid JSON line skipped ({e})")
    return [r for r in data if isinstance(r, dict) and "task_id" in r]


def label_from_filename(path):
    stem = Path(path).stem.lower()
    for k, v in LABELS.items():
        if k in stem:
            return v
    return stem.split("_")[-1]


def dataset_of(path):
    return Path(path).stem.lower().split("_")[0]


def find_reference(var, by_id, by_ep):
    """Match on task_id, check entry_point; fall back to a unique entry_point."""
    tid, ep = var.get("task_id"), var.get("entry_point")
    o = by_id.get(tid)
    cands = by_ep.get(ep, [])
    if o and (not ep or o.get("entry_point") == ep):
        return o, "task_id"
    if o and ep:
        if len(cands) == 1:
            return cands[0], "entry_point (task_id points to another function)"
        return o, "task_id (WARNING: entry_point differs)"
    if len(cands) == 1:
        return cands[0], "entry_point"
    return None, None


# ------------------------------------------------------------ parsing
def normalize(prompt, ep, is_variant):
    p = prompt or ""
    if is_variant and ep:
        p = re.sub(r"\bcandidate\b", ep, p)
    lines = [re.sub(r"\s+", " ", l.strip()) for l in p.replace("\t", " ").splitlines()]
    return "\n".join(l for l in lines if l)


def split_params(s):
    out, depth, cur = [], 0, ""
    for ch in s or "":
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def split_doc(text):
    desc, ex, in_out = [], [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            in_out = False
            continue
        if re.match(r"^(for\s+)?examples?\s*:?$", line, re.I):
            continue
        if line.startswith(">>>"):
            ex.append(line); in_out = True
        elif in_out:
            ex.append(line)
        elif EX_LINE.search(line):
            ex.append(line)
        else:
            desc.append(line)
    return desc, ex


def parse_prompt(prompt, ep):
    flags = {"unterminated_docstring": False, "missing_parens": False,
             "dangling_return": False, "text_after_docstring": False}
    defs = list(DEF_RE.finditer(prompt))
    if not defs:
        desc, ex = split_doc(prompt)
        d = " ".join(desc)
        flags["dangling_return"] = bool(re.search(r"\breturn\s*[.,]", d))
        return dict(kind="text", name=None, params=None, returns=None, helpers=[], imports=[],
                    description=d, examples=ex, flags=flags)
    t = next((d for d in defs if d.group(1) == ep), defs[-1])
    flags["missing_parens"] = t.group(2) is None
    rest = prompt[t.end():].strip()
    body, trailing = rest, ""
    q = DOC_RE.search(rest)
    if q and q.start() <= 60:
        body = q.group(2)
        flags["unterminated_docstring"] = q.group(3) == ""
        trailing = rest[q.end():].strip()
        if re.match(r"[A-Z][a-z]+ [a-z]+", trailing):
            flags["text_after_docstring"] = True
            body += "\n" + trailing
    if not body.strip():
        pre = [l for l in prompt[:t.start()].splitlines()
               if l.strip() and not re.match(r"\s*(from|import)\s", l)]
        body = "\n".join(pre)
    desc, ex = split_doc(body)
    d = " ".join(desc)
    flags["dangling_return"] = bool(re.search(r"\breturn\s*[.,]", d))
    return dict(kind="code", name=t.group(1),
                params=split_params(t.group(2)) if t.group(2) is not None else None,
                returns=(t.group(3) or "").strip() or None,
                helpers=sorted(x.group(1) for x in defs if x is not t),
                imports=[l for l in prompt.splitlines() if re.match(r"\s*(import|from)\s", l)],
                description=d, examples=ex, flags=flags)


# ------------------------------------------------------------ helpers
def tokenize(s): return TOKEN_RE.findall(s)
def words(s): return WORD_RE.findall(s.lower())
def sents(s): return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", s) if len(x.strip()) > 2]


def token_diff(a, b):
    ta, tb = tokenize(a), tokenize(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    ops, inline = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        old, new = " ".join(ta[i1:i2]), " ".join(tb[j1:j2])
        if tag == "equal":
            inline.append(old); continue
        ops.append({"op": tag, "original": old, "variant": new})
        if old: inline.append(f"[-{old}-]")
        if new: inline.append(f"{{+{new}+}}")
    return {"similarity_ratio": round(sm.ratio(), 3), "operations": ops,
            "inline_diff": " ".join(inline), "n_tokens_original": len(ta),
            "n_tokens_variant": len(tb), "token_length_delta": len(tb) - len(ta)}


def unmatched(xs, ys, thr=0.85):
    return [x for x in xs if not any(
        difflib.SequenceMatcher(None, x.lower(), y.lower()).ratio() >= thr for y in ys)]


def type_set(text):
    return {TYPE_WORDS[m.group(1).lower()] for m in RET_RE.finditer(text or "")}


def annotation_types(ann):
    if not ann:
        return set()
    out = set()
    for w in re.findall(r"[A-Za-z]+", ann):
        t = TYPE_WORDS.get(w.lower())
        if t:
            out.add(t)
    return out


def doctest_output_types(examples):
    types, prev = set(), False
    for l in examples:
        if l.startswith(">>>"):
            prev = True
        elif prev:
            prev = False
            try:
                types.add(type(ast.literal_eval(l)).__name__)
            except Exception:
                pass
    return types & {"str", "int", "list", "tuple", "float", "bool"}


def doctest_without_output(examples):
    n = 0
    for i, l in enumerate(examples):
        if l.startswith(">>>") and (i + 1 == len(examples) or examples[i + 1].startswith(">>>")):
            n += 1
    return n


def bow_cosine(a, b):
    ca, cb = Counter(words(a)), Counter(words(b))
    dot = sum(ca[w] * cb[w] for w in ca)
    na, nb = math.sqrt(sum(v * v for v in ca.values())), math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


_ST = None
def embedding_cosine(a, b):
    global _ST
    try:
        if _ST is None:
            from sentence_transformers import SentenceTransformer
            _ST = SentenceTransformer("all-MiniLM-L6-v2")
        ea, eb = _ST.encode([a, b], normalize_embeddings=True)
        return float((ea * eb).sum())
    except Exception:
        return None


# ------------------------------------------------------------ structural diff
def signature_diff(A, B):
    names = lambda ps: [re.split(r"[:=]", p)[0].strip() for p in (ps or [])]
    na, nb = names(A["params"]), names(B["params"])
    d = {"signature_lost": A["params"] is not None and B["params"] is None,
         "params_removed": [p for p in na if p not in nb],
         "params_added": [p for p in nb if p not in na],
         "params_renamed": [(x, y) for x, y in zip(na, nb) if x != y] if len(na) == len(nb) else [],
         "annotations_dropped": (sum(":" in p for p in A["params"] or []) > sum(":" in p for p in B["params"] or [])
                                 or bool(A["returns"] and not B["returns"])),
         "return_annotation": [A["returns"], B["returns"]] if A["returns"] != B["returns"] else None,
         "helpers_dropped": [h for h in A["helpers"] if h not in B["helpers"]],
         "imports_dropped": [i for i in A["imports"] if i not in B["imports"]]}
    d["any"] = any(bool(v) for v in list(d.values()))
    return d


def structural_diff(orig, var, A, B):
    s = {"form": f"{A['kind']} -> {B['kind']}",
         "entry_point_changed": orig.get("entry_point") != var.get("entry_point"),
         "malformed_flags": [k for k, v in B["flags"].items() if v and not A["flags"].get(k)],
         "signature": signature_diff(A, B),
         "description_diff": token_diff(A["description"], B["description"]),
         "description_original": A["description"], "description_variant": B["description"]}
    eo, ev = A["examples"], B["examples"]
    s["examples_original"], s["examples_variant"] = len(eo), len(ev)
    s["examples_removed"] = [e for e in eo if e not in ev]
    s["examples_added"] = [e for e in ev if e not in eo]
    s["doctest_calls_without_output"] = [doctest_without_output(eo), doctest_without_output(ev)]
    heads = lambda d: {m.group(1).lower() for l in d.split(". ") for m in [HEADING_RE.match(l.strip())] if m}
    s["headings_lost"] = sorted(heads(A["description"]) - heads(B["description"]))
    return s


# ------------------------------------------------------------ semantic diff
def semantic_diff(A, B, S, embeddings=False):
    do, dv = A["description"], B["description"]
    wo_l, wv_l = words(do), words(dv)
    wo, wv = set(wo_l), set(wv_l)
    removed, added = sorted(wo - wv), sorted(wv - wo)
    added_s, removed_s = unmatched(sents(dv), sents(do)), unmatched(sents(do), sents(dv))
    added_text = " ".join(added_s)
    sig = S["signature"]

    # ---- ambiguity
    norm = lambda m: re.sub(r"\s+", " ", m.group(0).lower())
    alts = sorted({norm(m) for m in OR_RE.finditer(dv)} - {norm(m) for m in OR_RE.finditer(do)})
    hedges = sorted({m.group(0).lower() for m in HEDGE.finditer(dv)}
                    - {m.group(0).lower() for m in HEDGE.finditer(do)})
    nums_removed = [w for w in removed if re.fullmatch(r"\d+(\.\d+)?", w)]
    nums_added = [w for w in added if re.fullmatch(r"\d+(\.\d+)?", w)]
    ph = set(re.findall(r"\b[A-Z]\b", dv)) - set(re.findall(r"\b[A-Z]\b", do)) - {"I"}
    if not nums_removed:
        ph -= {"A"}
    lost_tech = [w for w in removed if w in TECH]
    gained_vague = [w for w in added if w in VAGUE]
    ambiguity = []
    if alts: ambiguity.append("alternatives introduced: " + "; ".join(f"'{a}'" for a in alts))
    if hedges: ambiguity.append("hedging wording: " + ", ".join(hedges))
    if ph: ambiguity.append("placeholder symbols replace concrete values: " + ", ".join(sorted(ph)))
    if gained_vague: ambiguity.append("vague terms: " + ", ".join(gained_vague))
    if lost_tech: ambiguity.append("precise terms replaced/removed: " + ", ".join(lost_tech))

    # ---- incompleteness
    inc = []
    if A["kind"] == "code" and B["kind"] == "text":
        inc.append("function signature removed (parameter names/types no longer given)")
    if sig["params_removed"]: inc.append("parameters removed from signature: " + ", ".join(sig["params_removed"]))
    if sig["annotations_dropped"]: inc.append("type annotations dropped")
    if sig["helpers_dropped"]: inc.append("helper functions dropped: " + ", ".join(sig["helpers_dropped"]))
    if sig["imports_dropped"]: inc.append("imports dropped")
    if S["malformed_flags"]: inc.append("malformed prompt: " + ", ".join(S["malformed_flags"]))
    if B["flags"]["dangling_return"]: inc.append("dangling 'return' with no value stated")
    if S["examples_original"] and S["examples_variant"] < S["examples_original"]:
        inc.append(f"examples reduced from {S['examples_original']} to {S['examples_variant']}")
    if S["doctest_calls_without_output"][1] > S["doctest_calls_without_output"][0]:
        inc.append("doctest calls without expected output")
    if S["headings_lost"]: inc.append("sections removed: " + ", ".join(S["headings_lost"]))
    lost_c = [w for w in removed if w in CONSTRAINT_WORDS]
    if lost_c: inc.append("constraint words removed: " + ", ".join(lost_c))
    if nums_removed and not nums_added: inc.append("numbers removed: " + ", ".join(nums_removed))
    if wo_l and len(wv_l) / len(wo_l) < 0.8:
        inc.append(f"description shrank to {len(wv_l)}/{len(wo_l)} words")
    if removed_s and not added_s:
        inc.append(f"{len(removed_s)} statement(s) dropped: " + " | ".join(x[:80] for x in removed_s[:3]))

    # ---- contradiction
    con = []
    for name, pat in CONSTRAINTS.items():
        if re.search(pat, added_text, re.I) and not re.search(pat, do, re.I):
            con.append(f"injected constraint: {name}")
    tv, to = type_set(dv), type_set(do)
    ann = annotation_types(B["returns"])
    if len(tv) > 1: con.append("description states several return types: " + ", ".join(sorted(tv)))
    if tv and ann and not (tv & ann): con.append(f"description return type {sorted(tv)} vs annotation {sorted(ann)}")
    if tv and to and tv != to and len(tv) == 1: con.append(f"return type changed {sorted(to)} -> {sorted(tv)}")
    ex_t = doctest_output_types(B["examples"])
    decl = tv | ann
    if decl and ex_t and not (ex_t <= decl):
        con.append(f"example outputs {sorted(ex_t)} do not match declared type(s) {sorted(decl)}")
    if ORDER_KEEP.search(dv) and SORTING.search(dv) and not (ORDER_KEEP.search(do) and SORTING.search(do)):
        con.append("both 'keep original order' and 'sort' requested")
    if sig["return_annotation"] and A["returns"] and B["returns"]:
        con.append(f"return annotation changed {A['returns']} -> {B['returns']}")

    # ---- correctness
    neg_o, neg_v = wo & NEGATIONS, wv & NEGATIONS
    flips = [(x, y) for x, y in ANTONYMS
             if (x in wo and y in wv and x not in wv and y not in wo) or
                (y in wo and x in wv and y not in wv and x not in wo)]
    cor = []
    if flips: cor.append("opposite-meaning swap: " + ", ".join(f"{a}<->{b}" for a, b in flips))
    if nums_removed and nums_added: cor.append(f"numbers changed {nums_removed} -> {nums_added}")
    if neg_o != neg_v: cor.append(f"negation changed {sorted(neg_o)} -> {sorted(neg_v)}")
    if S["examples_removed"] and len(S["examples_removed"]) == len(S["examples_added"]):
        cor.append(f"{len(S['examples_added'])} example(s) modified (may disagree with description)")
    stale = [p for p in sig["params_removed"] if len(p) > 1 and p in wv]
    if stale: cor.append("description still refers to removed parameters: " + ", ".join(stale))
    if sig["params_renamed"]:
        cor.append("parameters renamed: " + ", ".join(f"{a}->{b}" for a, b in sig["params_renamed"]))

    out = {"lexical_cosine": round(bow_cosine(do, dv), 3), "embedding_cosine": None,
           "removed_words": removed, "added_words": added,
           "sentences_added_or_modified": added_s, "sentences_removed_or_modified": removed_s,
           "evidence": {"ambiguity": ambiguity, "incompleteness": inc,
                        "contradiction": con, "correctness": cor}}
    if embeddings and do and dv:
        e = embedding_cosine(do, dv)
        out["embedding_cosine"] = round(e, 3) if e is not None else None
    return out


# ------------------------------------------------------------ explanation
def explain(label, S, M):
    n = []
    if (S["description_diff"]["similarity_ratio"] == 1.0 and not S["examples_removed"]
            and not S["examples_added"] and not S["signature"]["any"]):
        return ["No content difference after normalising whitespace and the 'candidate' placeholder name."]
    n.append(f"Structure: {S['form']} (code stub / plain text). Cosmetic differences were normalised away.")
    sg = S["signature"]
    if sg["any"]:
        parts = [k.replace("_", " ") for k in ("signature_lost", "annotations_dropped") if sg[k]]
        for k in ("params_removed", "params_added", "helpers_dropped"):
            if sg[k]: parts.append(f"{k.replace('_', ' ')}: {', '.join(sg[k])}")
        if sg["params_renamed"]:
            parts.append("params renamed: " + ", ".join(f"{a}->{b}" for a, b in sg["params_renamed"]))
        if sg["return_annotation"]:
            parts.append(f"return annotation {sg['return_annotation'][0]} -> {sg['return_annotation'][1]}")
        n.append("Signature: " + "; ".join(parts) + ".")
    else:
        n.append("Signature unchanged.")
    n.append(f"Examples: {S['examples_original']} -> {S['examples_variant']} "
             f"({len(S['examples_removed'])} removed, {len(S['examples_added'])} added/modified).")
    dd = S["description_diff"]
    n.append(f"Description: {dd['n_tokens_original']} -> {dd['n_tokens_variant']} tokens, "
             f"similarity {dd['similarity_ratio']}, {len(dd['operations'])} edit operation(s).")
    ev = M["evidence"]
    if ev.get(label):
        n.append(f"Evidence consistent with '{label}':")
        n += [f"   - {e}" for e in ev[label]]
    else:
        n.append(f"No automatic evidence for '{label}'; manual review advised.")
    for k, v in ev.items():
        if k != label and v:
            n.append(f"Additional signals ({k}): " + "; ".join(v))
    kind = "embedding" if M["embedding_cosine"] is not None else "bag-of-words"
    sim = M["embedding_cosine"] if M["embedding_cosine"] is not None else M["lexical_cosine"]
    n.append(f"Semantic similarity ({kind} cosine): {sim}.")
    return n


# ------------------------------------------------------------ driver
def compare(orig_recs, var_recs, label, embeddings):
    by_id = {r["task_id"]: r for r in orig_recs}
    by_ep = {}
    for r in orig_recs:
        by_ep.setdefault(r.get("entry_point"), []).append(r)
    res, missing = [], []
    for var in var_recs:
        orig, how = find_reference(var, by_id, by_ep)
        if orig is None:
            missing.append(var["task_id"]); continue
        ep = orig.get("entry_point") or var.get("entry_point")
        A = parse_prompt(normalize(orig.get("prompt"), ep, False), ep)
        B = parse_prompt(normalize(var.get("prompt"), ep, True), ep)
        S = structural_diff(orig, var, A, B)
        M = semantic_diff(A, B, S, embeddings)
        res.append({"task_id": var["task_id"], "entry_point": ep, "issue_label": label,
                    "matched_by": how, "original_prompt": orig.get("prompt"),
                    "variant_prompt": var.get("prompt"), "structural_diff": S,
                    "semantic_diff": M, "explanation": explain(label, S, M)})
    return res, missing


def to_markdown(results):
    L = ["# Task description diff report", ""]
    for r in results:
        S = r["structural_diff"]
        L += [f"## {r['task_id']} ({r['issue_label']}) - `{r['entry_point']}`  [matched by {r['matched_by']}]", "",
              f"- **Original:** {S['description_original'] or r['original_prompt']}",
              f"- **Variant:** {S['description_variant'] or r['variant_prompt']}",
              f"- **Inline diff:** `{S['description_diff']['inline_diff']}`", ""]
        L += [f"  - {x}" for x in r["explanation"]] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--reference", help="single reference file; all positional files are then variants")
    ap.add_argument("-o", "--output", default="diff_report.json")
    ap.add_argument("--md", help="optional Markdown report path")
    ap.add_argument("--embeddings", action="store_true")
    args = ap.parse_args()

    refs, variants = {}, []
    if args.reference:
        refs["*"] = load_records(args.reference); variants = args.files
    else:
        for f in args.files:
            if "original" in Path(f).stem.lower():
                refs[dataset_of(f)] = load_records(f)
            else:
                variants.append(f)
    if not refs or not variants:
        ap.error("need a reference file (name containing 'original', or --reference) and variant file(s)")

    allr = []
    for vf in variants:
        orig = refs.get("*") or refs.get(dataset_of(vf))
        if orig is None:
            print(f"[warn] no reference for dataset '{dataset_of(vf)}' ({vf}); skipped"); continue
        label = label_from_filename(vf)
        res, missing = compare(orig, load_records(vf), label, args.embeddings)
        print(f"{vf}: label={label}, compared={len(res)}, unmatched={len(missing)}"
              + (f" ({', '.join(missing[:8])}{'...' if len(missing) > 8 else ''})" if missing else ""))
        allr += res
    Path(args.output).write_text(json.dumps(allr, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(to_markdown(allr), encoding="utf-8")
    print(f"Wrote {len(allr)} comparisons to {args.output}")


if __name__ == "__main__":
    main()