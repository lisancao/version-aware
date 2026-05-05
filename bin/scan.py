#!/usr/bin/env python3
"""
scan.py: version-aware Layer 3 scanner

Reads text from stdin (pipe agent output into this) and identifies claims
that are high-risk for LLM knowledge staleness. Uses regex heuristics only;
stdlib, no dependencies, fast.

Usage:
    echo "Spark uses micro-batches and cannot achieve sub-second latency" | python3 scan.py
    cat agent_output.txt | python3 scan.py
    python3 scan.py < output.txt

Exit codes:
    0: no staleness risks found
    1: staleness risks detected
"""

import re
import sys
from dataclasses import dataclass
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Library-name allowlist
# Patterns require the matched subject to be a known library name. This is
# the single biggest false-positive reducer: "the schema cannot be modified"
# stops matching the capability-absence pattern because "the schema" is not
# a library. Add to this set as new libraries get covered.
# ---------------------------------------------------------------------------

LIBRARY_NAMES = {
    # Big-name frameworks (case-insensitive matches via .lower())
    "spark", "pyspark", "flink", "kafka", "pulsar", "beam",
    "iceberg", "delta", "hudi", "hive", "presto", "trino",
    "pandas", "numpy", "polars", "dask", "ray", "modin",
    "tensorflow", "pytorch", "torch", "jax", "keras", "transformers",
    "scikit-learn", "sklearn", "xgboost", "lightgbm", "catboost",
    "mlflow", "wandb", "kubeflow", "airflow", "dagster", "prefect",
    "dbt", "fivetran", "stitch", "airbyte",
    "pyarrow", "arrow", "avro", "parquet", "orc",
    "react", "next", "nextjs", "vue", "svelte", "angular",
    "express", "fastapi", "flask", "django", "rails",
    "kubernetes", "k8s", "docker", "terraform", "ansible",
    "postgres", "postgresql", "mysql", "redis", "mongodb", "cassandra",
    "snowflake", "databricks", "bigquery", "redshift", "athena",
    "kinesis", "firehose",
    "sqlalchemy", "alembic", "pydantic", "celery",
    "scala", "pyspark", "scikit-learn",
    # Note: bare "node", "go", "rust", "java" deliberately omitted.
    # They generate too many false positives (cluster node, go ahead,
    # java the language vs. java the runtime, etc.). Node.js claims are
    # caught via framework names (next, react, express, etc.).
}

LIBRARY_PATTERN_FRAGMENT = (
    r"(?:" + r"|".join(re.escape(n) for n in sorted(LIBRARY_NAMES, key=len, reverse=True)) + r")"
)


def _line_mentions_library(line: str) -> bool:
    """Whole-line library-name gate. The single biggest false-positive reducer.

    Returns True if the line mentions any known library. Lines about
    schemas, approaches, processes, etc. without naming a library are
    filtered out. This is more permissive than gating on the captured
    subject group, which is correct: the relevant signal is whether
    the line is *about* a library at all.

    Examples:
        'Spark cannot achieve sub-second latency'  -> True (mentions spark)
        'cannot achieve sub-second latency'        -> False (no library)
        'the schema cannot be modified'            -> False
        'Apache Spark Structured Streaming uses
         micro-batches'                            -> True (mentions spark)
    """
    if not line:
        return False
    tokens = re.split(r"[\s,.;:()/\-]+", line.lower())
    return any(t in LIBRARY_NAMES for t in tokens if t)


# ---------------------------------------------------------------------------
# Claim patterns: (regex, risk_level, claim_type, rationale, requires_lib)
# Precision over recall. requires_lib=True means group 1 must be a known
# library name (filters most false positives).
# ---------------------------------------------------------------------------

PATTERNS: List[Tuple[str, str, str, str]] = [
    # --- HIGH RISK: Capability absence claims ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:can(?:not|'t)|does(?:n't| not)|doesn't support|is(?:n't| not) (?:able to|capable of)|lacks|has no|doesn't have)\s+(.{10,80})",
        "HIGH",
        "Capability absence claim",
        "Claiming a library cannot do something; capabilities are added in new releases",
    ),
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:is not|isn't)\s+(?:designed for|suitable for|built for|meant for)\s+(.{5,60})",
        "HIGH",
        "Design/suitability limitation claim",
        "Suitability claims often become outdated as libraries expand their scope",
    ),
    (
        r"(?i)(?:fundamental|inherent|architectural|by design|by nature)\s+limitation\s+(?:of|in|with)\s+(\w[\w\s-]{1,40})",
        "HIGH",
        "Architectural limitation claim",
        "Claims about fundamental limitations are highest-risk; major releases often address these",
    ),

    # --- HIGH RISK: Processing model claims ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:uses?|processes?|operates? (?:using|via|with|on)|(?:is|are) based on)\s+(?:micro[-\s]?batch(?:es?|ing)?|mini[-\s]?batch(?:es?|ing)?)",
        "HIGH",
        "Processing model claim (micro-batch)",
        "Processing models change across major releases; Spark 4.x introduced continuous processing",
    ),
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:processes?|handles?|executes?)\s+(?:events?|records?|rows?|messages?)\s+(?:one at a time|sequentially|serially)",
        "HIGH",
        "Processing model claim (sequential)",
        "Processing model claims are frequently invalidated by new execution modes",
    ),
    (
        r"(?i)(?:true|real|genuine|native)\s+streaming\s+(?:in|with|via|using)\s+(\w[\w\s-]{1,40})",
        "HIGH",
        "Streaming capability claim",
        "Streaming capability is rapidly evolving across data frameworks",
    ),

    # --- HIGH RISK: Latency claims ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:cannot|can't|is unable to|doesn't)\s+(?:achieve|reach|provide|deliver|guarantee)\s+(?:sub[-\s]?second|low[-\s]?latency|millisecond|real[-\s]?time)\s+(?:latency|performance|processing|response)",
        "HIGH",
        "Latency ceiling claim",
        "Latency capabilities are a common target for improvement in major releases",
    ),
    (
        r"(?i)(?:minimum|minimum possible|lowest possible|best[-\s]case)\s+latency\s+(?:of|is|for)\s+(\w[\w\s-]{1,40})\s+is\s+(\d+\s*(?:second|ms|millisecond))",
        "HIGH",
        "Specific latency bound claim",
        "Hardcoded latency bounds are invalidated by new processing modes",
    ),

    # --- HIGH RISK: Competitive comparisons ---
    (
        r"(?i)use\s+(\w[\w\s-]{1,40})\s+(?:instead of|rather than|over|not)\s+(\w[\w\s-]{1,40})\s+(?:because|since|as|when|for|if)",
        "HIGH",
        "Competitive recommendation",
        "Comparative recommendations depend on capability claims for BOTH sides; both may have changed",
    ),
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+is\s+(?:better|superior|preferred|the right choice|more suitable|more appropriate)\s+(?:than|to)\s+(\w[\w\s-]{1,40})\s+(?:for|when|if|in cases?)",
        "HIGH",
        "Comparative quality claim",
        "Relative quality claims depend on both libraries' current capabilities",
    ),
    (
        r"(?i)(?:unlike|whereas|while|compared to)\s+(\w[\w\s-]{1,40}),\s+(\w[\w\s-]{1,40})\s+(?:can|does|supports?|provides?|offers?|has|is)",
        "HIGH",
        "Contrastive capability claim",
        "Contrastive claims ('unlike X, Y can...') become stale when X adds the capability",
    ),

    # --- MEDIUM RISK: API pattern claims ---
    (
        r"(?i)(?:the\s+)?(?:correct|proper|recommended|standard|idiomatic|canonical)\s+way\s+to\s+(?:\w+\s+){1,5}(?:in|with|using)\s+(\w[\w\s-]{1,40})\s+is",
        "MEDIUM",
        "Best practice / API pattern claim",
        "Recommended patterns evolve with API design and community conventions",
    ),
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:v\d|version\s+\d)[\w.-]*\s+(?:introduced|added|deprecated|removed|changed)",
        "MEDIUM",
        "Version-specific feature claim",
        "Version-specific claims require knowing whether the installed version matches",
    ),
    (
        r"(?i)(?:as of|since|starting (?:from|in|with))\s+(?:version\s+)?([\d.]+),?\s+(\w[\w\s-]{1,40})\s+(?:now\s+)?(?:supports?|provides?|offers?|has|can)",
        "MEDIUM",
        "Version-gated capability claim",
        "Verify the installed version actually includes this version's changes",
    ),

    # --- MEDIUM RISK: Default behavior claims ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:by default|defaults? to|out of the box)\s+(?:\w+\s+){0,5}(?:uses?|does|runs?|processes?|handles?)",
        "MEDIUM",
        "Default behavior claim",
        "Default settings change across major versions",
    ),

    # --- MEDIUM RISK: Performance characteristic claims ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+is\s+(?:significantly\s+)?(?:faster|slower|more efficient|less efficient|better performing)\s+than\s+(\w[\w\s-]{1,40})\s+(?:for|at|when|in)",
        "MEDIUM",
        "Relative performance claim",
        "Performance characteristics shift with implementation changes, JIT improvements, etc.",
    ),

    # --- LOW RISK: General architectural statements ---
    (
        r"(?i)\b(\w[\w\s-]{1,40})\s+(?:is built on|is built around|is designed around|is based on|uses internally)\s+(.{5,50})",
        "LOW",
        "Internal architecture claim",
        "Internal implementation details change, though less frequently than external behavior",
    ),
    (
        r"(?i)(?:spark|flink|kafka|delta|iceberg|hudi|dbt|ray|dask)\s+(?:architecture|execution model|processing model)",
        "LOW",
        "Architecture reference",
        "References to specific architecture concepts; verify they apply to installed version",
    ),
]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    line_num: int
    line: str
    risk: str
    claim_type: str
    rationale: str
    matched_text: str


def scan_text(text: str) -> List[Finding]:
    findings = []
    seen_matches = set()  # deduplicate near-identical matches

    # Patterns that gate on group 1 being a known library name.
    # These claim types had the highest false-positive rate without the gate.
    LIBRARY_GATED_TYPES = {
        "Capability absence claim",
        "Design/suitability limitation claim",
        "Architectural limitation claim",
        "Processing model claim (micro-batch)",
        "Processing model claim (sequential)",
        "Streaming capability claim",
        "Latency ceiling claim",
        "Specific latency bound claim",
        "Competitive recommendation",
        "Comparative quality claim",
        "Contrastive capability claim",
        "Best practice / API pattern claim",
        "Default behavior claim",
        "Relative performance claim",
        "Internal architecture claim",
    }

    lines = text.split("\n")
    for line_num, line in enumerate(lines, 1):
        # Skip empty lines, code blocks, and table rows
        stripped = line.strip()
        if not stripped or stripped.startswith("```") or stripped.startswith("|") or stripped.startswith("#"):
            continue

        # Whole-line library-name gate (drops "the schema cannot...",
        # "this approach is not designed for...", etc.)
        line_has_library = _line_mentions_library(stripped)

        for pattern, risk, claim_type, rationale in PATTERNS:
            for match in re.finditer(pattern, line):
                # Library-gated claim types fire only when the line names a library
                if claim_type in LIBRARY_GATED_TYPES and not line_has_library:
                    continue

                matched_text = match.group(0)[:120]  # cap length

                # Deduplicate: skip if we've seen the same claim_type on this line
                dedup_key = (line_num, claim_type, matched_text[:40])
                if dedup_key in seen_matches:
                    continue
                seen_matches.add(dedup_key)

                findings.append(Finding(
                    line_num=line_num,
                    line=line.strip()[:200],
                    risk=risk,
                    claim_type=claim_type,
                    rationale=rationale,
                    matched_text=matched_text,
                ))

    # Sort by risk level (HIGH first), then line number
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda f: (risk_order.get(f.risk, 9), f.line_num))

    return findings


def format_finding(f: Finding) -> str:
    risk_icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵"}
    icon = risk_icons.get(f.risk, "⚪")

    return (
        f"\nSTALENESS RISK [{f.risk}] {icon} (line {f.line_num})\n"
        f"  Claim: \"{f.matched_text}\"\n"
        f"  Type:  {f.claim_type}\n"
        f"  Risk:  {f.rationale}\n"
        f"  Action: Verify against installed version's release notes\n"
    )


def print_summary(findings: List[Finding]) -> None:
    high = sum(1 for f in findings if f.risk == "HIGH")
    medium = sum(1 for f in findings if f.risk == "MEDIUM")
    low = sum(1 for f in findings if f.risk == "LOW")

    print("\n" + "=" * 60)
    print("STALENESS SCAN SUMMARY")
    print("=" * 60)
    print(f"Total findings: {len(findings)}  |  🔴 HIGH: {high}  |  🟡 MEDIUM: {medium}  |  🔵 LOW: {low}")

    if high > 0:
        print("\n⚠️  HIGH-risk findings detected. These claims may be based on")
        print("   outdated training data. Verify against installed library versions")
        print("   before making architectural decisions.")
    elif medium > 0:
        print("\n   Medium-risk findings detected. Consider verifying key claims")
        print("   if making production architectural decisions.")
    else:
        print("\n   Low-risk findings only. Standard caution applies.")
    print("=" * 60 + "\n")


def main() -> int:
    if sys.stdin.isatty():
        print("Usage: echo '<text>' | python3 scan.py", file=sys.stderr)
        print("       cat output.txt | python3 scan.py", file=sys.stderr)
        return 1

    text = sys.stdin.read()
    if not text.strip():
        return 0

    findings = scan_text(text)

    if not findings:
        print("\n✅ No staleness risks detected in scanned text.\n")
        return 0

    for finding in findings:
        print(format_finding(finding))

    print_summary(findings)

    # Exit 1 if any HIGH findings, 0 otherwise (allows CI integration)
    has_high = any(f.risk == "HIGH" for f in findings)
    return 1 if has_high else 0


if __name__ == "__main__":
    sys.exit(main())
