# version-aware

> **Status: prototype (v0.1).** API surface and pattern catalog will iterate based on real-world usage. Apache 2.0 licensed. PRs welcome.

**LLMs have training cutoffs. Your libraries don't.**

Every time a coding agent tells you "X can't do Y" or "use X instead of Y because Y lacks Z": that claim was generated from training data with a fixed cutoff date. The libraries in your project keep getting updated. When there's a version gap between what the model learned and what you've installed, the model doesn't know. It answers with full confidence anyway. This plugin makes that gap visible.

---

## The Spark 4.1 Incident

In January 2026, a Claude agent advised a team to use Apache Flink instead of Spark Structured Streaming for their sub-second latency use case. The reasoning was technically sound, for Spark 3.x. The agent cited micro-batch processing as a fundamental limitation of Spark Streaming, correctly noting it couldn't achieve sub-second latency.

The installed version was PySpark 4.1.0.dev4.

Spark 4.0 introduced continuous processing mode. The "fundamental limitation" had been addressed in a major release. The model didn't know. The team spent a week evaluating a Flink migration before someone checked the Spark 4.0 release notes.

This is not a hallucination problem. The model's claim was accurate, for the version it was trained on. This is a **staleness problem**, and it's endemic to any AI assistant used in an active software ecosystem.

---

## What version-aware Does

The plugin operates at three layers:

```
Layer 1: Planning phase (SKILL)
  ↓ Before answering architectural questions, identify libraries,
    check installed versions, compare against training cutoff,
    fetch changelogs for gaps, generate version-pinned answers.

Layer 2: Pre-execution hook (HOOK)
  ↓ Before every Bash tool call, scan the project's dependency
    files, check installed versions of key libraries, and emit
    warnings when installed versions exceed training coverage.

Layer 3: Post-generation scanner (CLI TOOL)
  ↓ Pipe agent output through scan.py to identify
    high-risk claim patterns: capability absence claims,
    processing model claims, competitive comparisons,
    latency ceilings, default behavior claims.
```

### Component 1: `architecture-check` Skill

Fires when you ask architectural or comparative questions. Triggers a structured planning protocol that:
- Identifies all libraries mentioned
- Checks installed versions via pip/npm/cargo
- Flags version gaps explicitly (⚠️ format, not hidden in prose)
- Fetches changelogs for gap ranges before making claims
- Generates answers with version-pinned claims and uncertainty markers
- Ends every response with a **Staleness Check** table

### Component 2: Version-Check Hook

Runs automatically before every Bash tool execution. Reads `requirements.txt`, `pyproject.toml`, `package.json`, or `Cargo.toml`, checks installed versions of ~20 key data/ML libraries against a conservative cutoff map, and emits a warning block when gaps are found. **Silent when no gaps exist**: zero noise when you're working with well-covered library versions.

### Component 3: `scan.py`

A standalone stdin scanner you can pipe any text through. Identifies 15+ claim pattern types sorted by staleness risk:
- 🔴 HIGH: capability absence, processing model, latency ceiling, competitive comparison
- 🟡 MEDIUM: API patterns, version-gated features, default behavior
- 🔵 LOW: internal architecture, general references

CI-friendly: exits with code 1 if HIGH-risk findings are present.

---

## Installation

```bash
git clone https://github.com/lisancao/version-aware ~/.claude/plugins/version-aware
```

Or use Claude Code's plugin install command pointed at a local clone:
```bash
git clone https://github.com/lisancao/version-aware
/plugin install file://$(pwd)/version-aware
```

Verify installation by running any Bash tool. If you have flagged libraries installed, you'll see a `STALENESS WARNING` block. If not, the hook is silent (by design).

To run the test suite:
```bash
cd version-aware && tests/run.sh
```

---

## How It Works

```
User asks: "Should I use Spark or Flink for sub-second latency?"
                    │
                    ▼
         [architecture-check skill fires]
                    │
         ┌──────────┴──────────┐
         │  Check pip show     │
         │  pyspark → 4.1.0    │
         │  Training covers    │
         │  ~3.5.x             │
         └──────────┬──────────┘
                    │
         ⚠️ Version gap detected
                    │
         ┌──────────┴──────────┐
         │  Fetch changelog    │
         │  for 3.5 → 4.1 gap  │
         │  Found: continuous  │
         │  processing mode    │
         └──────────┬──────────┘
                    │
         ┌──────────┴──────────────────────────────────┐
         │  Answer (version-pinned):                    │
         │  "[As of Spark 3.5] Spark Structured        │
         │   Streaming uses micro-batches..."           │
         │                                             │
         │  "[Changelog note] Spark 4.0 introduced    │
         │   continuous processing. sub-second        │
         │   latency now achievable. Recommend         │
         │   verifying before choosing Flink."         │
         └──────────┬──────────────────────────────────┘
                    │
         ## Staleness Check
         | pyspark | 4.1.0 | ~3.5.x | ⚠️ Major gap |
         Claims NOT verified: latency characteristics
```

---

## Usage

### Automatic (via skill)
Just ask architectural questions normally. The skill fires on keywords like "should I use", "does X support", "compare X and Y", "can X handle".

### Manual scan
```bash
# Scan agent output for staleness risks
cat agent_response.txt | python3 bin/scan.py

# In-line
echo "Spark cannot achieve sub-second latency" | python3 bin/scan.py

# As a CI check (exits 1 on HIGH findings)
generate_recommendations.sh | python3 bin/scan.py || echo "Staleness review required"
```

### Manual version check
```bash
./bin/version-check.sh
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

The version cutoff map in `bin/version-check.sh` is the most important thing to keep updated. It's a heredoc, one library per line:

```
pyspark 3.5
delta-spark 2.4
# add more here
```

**Contributions needed:**
- Libraries not yet in the map (especially JVM ecosystem: Scala libs, Java frameworks)
- Cutoff updates when current entries fall behind
- Node.js, Rust, Go ecosystem maps with proper version comparison
- scan.py pattern tuning (more claim types, fewer false positives)
- Flink detection (hard via pip; PyFlink ships as `apache-flink`, not `flink`)

Open a PR. The map is the product. The code is scaffolding.

## Related

- [lisancao/spark-skills](https://github.com/lisancao/spark-skills): Apache Spark reference docs, validated against Spark 4.1. Complementary install for projects doing Spark work; gives Claude concrete current-version knowledge to match against the staleness signal.
- [lisancao/lakehouse-skills](https://github.com/lisancao/lakehouse-skills): broader lakehouse skills (Iceberg, Delta, MLflow).

---

## Why This Matters (Databricks Ecosystem)

The Databricks ecosystem moves fast. Delta Lake 3.x changed the transaction log format. Unity Catalog changed how you reference tables. Spark 4.0 changed the execution model. MLflow 2.x broke several API patterns from 1.x. DBT 1.5 introduced model contracts.

If you use AI coding assistants in a Databricks environment (and you do), you're routinely asking questions about libraries where major releases have happened since the model's training cutoff. The model doesn't flag this. It answers confidently. version-aware makes the gap visible so you can make informed decisions instead of discovering the problem in production.

---

## License

Apache 2.0. See [LICENSE](LICENSE).

---

*Built by [Lisa Cao](https://github.com/lisancao). Initial scaffold drafted with glyph; v0.1 prototype hardening (plugin format fixes, scanner tuning, tests, hook perf) drafted with Claude.*
