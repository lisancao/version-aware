---
name: architecture-check
description: >
  Fire this skill when the user asks architectural questions about libraries or frameworks:
  "does X support Y", "should I use X or Y for Z", "what's the best approach for Z",
  "compare X and Y", "can X handle Y", "what are the limitations of X",
  "is X suitable for Y", "X vs Y", capability questions, performance comparisons,
  or any recommendation involving specific library/framework versions.
  Also fire when making claims about what a library "cannot" do, its "fundamental"
  behavior, or its processing model (micro-batch, streaming, etc.).
allowed-tools: Bash, Read, Glob
---

# Architecture Check: Staleness-Aware Planning

You are about to answer an architectural or comparative question about software libraries or frameworks. Before generating your answer, run through this protocol. It exists because your training data has a cutoff; installed library versions in this project may be newer than what you're confident about, and architectural claims about old versions can be confidently, silently wrong.

## Step 1: Identify Libraries and Frameworks

List every library, framework, or tool mentioned in the question or that is relevant to the answer. Include:
- Directly named tools ("Spark", "pandas", "Flink")
- Implied dependencies (if asking about Delta Lake, also check pyspark)
- Competing tools being compared

**Output format:**
```
Libraries identified: [lib1, lib2, lib3]
```

## Step 2: Check Installed Versions

For each identified library, run the appropriate version command:

**Python:**
```bash
pip show <library> 2>/dev/null | grep -E "^(Name|Version):"
# or
python -c "import <library>; print(<library>.__version__)" 2>/dev/null
```

**Node.js:**
```bash
npm list <package> --depth=0 2>/dev/null
```

**Rust:**
```bash
cargo tree -i <crate> 2>/dev/null | head -5
```

**Scala/Java (look in build files):**
```bash
grep -r "<library>" build.sbt pom.xml build.gradle 2>/dev/null | head -10
```

If no dependency files exist, note: "No dependency manifest found, so installed versions cannot be checked."

**Output format:**
```
Installed versions:
- pyspark: 4.1.0.dev4
- delta-spark: not installed / version unknown
- pandas: 2.2.3
```

## Step 3: Training Cutoff Comparison

State your training cutoff date explicitly. Then, for each library:

1. State what version range you're confident about
2. Compare against installed version
3. Flag any gaps

**Flag format (use this exactly when a gap exists):**

> ⚠️ My training data may not cover [library] [installed version]. I have confident knowledge up to approximately [last known version]. Proceeding with version-aware caution.

Do not skip this step. Do not compress it. Even if you're "pretty sure" nothing changed, flag version gaps explicitly. The point of this plugin is to make uncertainty visible.

**Special attention for major version jumps:** If the installed version represents a major release higher than your training data (e.g., you know Spark 3.x well, installed is Spark 4.x), this is high-risk. Major releases frequently change architectural fundamentals.

## Step 4: Changelog Fetch (Required When Version Gap Detected)

When you've flagged a version gap, **do not proceed to answer until you've checked the changelog**. This is the step most commonly skipped, so do not skip it.

Run one of these to find changelog/release notes:
```bash
# Check for local changelog
find . -name "CHANGELOG*" -o -name "CHANGES*" -o -name "HISTORY*" 2>/dev/null | head -5

# Check PyPI for release info (if pip available)
pip index versions <library> 2>/dev/null | head -5
```

If no local changelog, note that web lookup would be needed and state: "I cannot verify changelog locally. The following answer is based on training data up to [version] and should be verified against [library] release notes for versions [gap range]."

When fetching changelogs, specifically look for:
- **New execution modes or processing models** (e.g., does the library now support a new processing paradigm?)
- **Changes to fundamental limitations** previously used in comparisons (e.g., latency claims, throughput ceilings)
- **Deprecated patterns or replaced APIs** (e.g., old API style vs. new)
- **New capabilities that change competitive comparisons** (e.g., a library adding a feature that was previously a reason to prefer a competitor)
- **Breaking changes to architectural assumptions** (e.g., execution model changes)

## Step 5: Generate Answer with Uncertainty Markers

Now write your answer, applying these rules:

### For claims about libraries WITHOUT a version gap:
Write normally. You can be confident.

### For claims about libraries WITH a version gap:

1. **Version-pin every architectural claim:**
   - Instead of: "Spark Structured Streaming uses micro-batches"
   - Write: "[As of Spark 3.5] Spark Structured Streaming uses micro-batches"

2. **Distinguish stable API from architectural claims:**
   - Stable API (surface-level, unlikely to change): note with `[stable API]`
   - Architectural claim (processing model, limitations, performance characteristics): note with `[verify against vX.Y release notes]`

3. **When changelog evidence contradicts your training data, state both explicitly:**
   ```
   [Training data understanding]: Spark Structured Streaming cannot achieve sub-second latency
   because it uses micro-batch processing with minimum trigger intervals.
   
   [Changelog note]: Spark 4.0 introduced [feature]; this claim may no longer hold.
   Recommend verifying current latency characteristics before making architectural decisions.
   ```

4. **Competitive comparisons are highest risk.** If you're saying "use X instead of Y because X can do Z that Y cannot": that "Y cannot do Z" claim must be version-pinned. Capabilities get added. Limitations get removed.

## Step 6: Self-scan with the staleness scanner

Before emitting your answer, pipe your draft through `scan.py` and address any HIGH-risk findings. This catches stale claims you missed.

```bash
echo "<your draft answer>" | python3 ${CLAUDE_PLUGIN_ROOT:-./}/bin/scan.py
```

If the scanner reports HIGH findings:
- Re-read each flagged claim
- For each, either: (a) version-pin the claim explicitly, (b) cite a changelog confirming current behavior, or (c) remove the claim
- Re-scan until no HIGH findings remain

The scanner is a backstop, not a replacement for steps 1 to 5. A clean scan does not mean the answer is correct; it means the answer doesn't trip the known staleness patterns.

## Step 7: Staleness Summary

End every architectural response with this section. No exceptions.

```markdown
## Staleness Check

| Library | Installed | Training Covers | Gap |
|---------|-----------|-----------------|-----|
| pyspark | 4.1.0     | ~3.5.x          | ⚠️ Major version gap |
| pandas  | 2.2.3     | ~2.1.x          | Minor, low risk |

**Claims verified against changelog:** [list specific claims, or "none, no local changelog"]

**Claims NOT verified (treat with caution):**
- [Specific claim 1]: reason for caution
- [Specific claim 2]: reason for caution

**Recommendation:** For production architectural decisions involving libraries with version gaps,
verify against official release notes before committing to an approach.
```

---

## Common Staleness Traps

These are the claim types most likely to go stale across major releases. Be especially careful:

| Claim Type | Example | Risk |
|------------|---------|------|
| Processing model | "X uses micro-batches" | HIGH: often changes in major releases |
| Latency ceiling | "X cannot achieve sub-second latency" | HIGH. new modes may invalidate |
| Capability absence | "X doesn't support Y" | HIGH. features get added |
| Competitive framing | "Use X not Y because Y can't do Z" | HIGH. both sides may have changed |
| API pattern | "The correct way to do X is Y" | MEDIUM. APIs evolve |
| Default behavior | "By default, X does Y" | MEDIUM. defaults change |
| Performance characteristic | "X is faster than Y for Z" | MEDIUM. benchmarks shift |
| Import path | `from x.y import z` | LOW. usually stable, but check on major versions |

---

## Why This Protocol Exists

On 2026-01-14, a Claude agent confidently told a user that Apache Spark Structured Streaming
"uses micro-batches and cannot achieve sub-second latency". citing this as a reason to
prefer Flink for their use case. The installed PySpark version was 4.1.0.dev4. Spark 4.0
introduced continuous processing mode with sub-second latency. The training data covered
Spark 3.x. The claim was accurate for Spark 3.x. It was wrong for the version actually
installed. The user made architectural decisions based on it.

This protocol exists to prevent that. Version gaps are not rare. They are the default state
of any active project.
