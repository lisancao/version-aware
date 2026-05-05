# Contributing to version-aware

The cutoff map in `bin/version-check.sh` is the product. The code is scaffolding. The single most useful contribution is keeping that map accurate and expanding its coverage.

## Adding a library to the cutoff map

1. Pick the last version you're confident a recent (~2024 to early 2026) frontier model was trained on. Conservative is correct.
2. Add the entry to the `CUTOFF_MAP` heredoc in `bin/version-check.sh`:

   ```
   <library-name-as-pip-shows-it> <major>.<minor>
   ```

3. If the library is in the Node.js ecosystem, add it to the `NODE_CUTOFFS` heredoc with the same format, but read from `package.json` semantics (typically just `<major>` for things like react/express).
4. Add the library token to the `LIBRARY_NAMES` set in `bin/scan.py` so the scanner's library-name gate recognizes it.
5. Run the tests: `tests/run.sh`. They should still pass.
6. Open a PR.

## Adding a new claim pattern to the scanner

Patterns live in `bin/scan.py` under the `PATTERNS` list. Each entry is a 4-tuple: `(regex, risk_level, claim_type, rationale)`.

Rules of thumb for new patterns:

- Precision over recall. A new pattern that fires twice on real-world prose where one is a true positive and one is a false positive is net negative for the user. Tune until the false positive rate is well below 10% on representative input.
- The library-name gate is automatic. Patterns with claim types in `LIBRARY_GATED_TYPES` only fire when the line mentions a known library. New claim types are gated unless explicitly listed otherwise.
- Risk levels are conservative. `HIGH` is reserved for claims where being wrong leads to a wrong architectural decision. `MEDIUM` is for claims that mislead but rarely steer big decisions. `LOW` is for context worth flagging without blocking.
- Add a regression test in `tests/test_scanner.sh` for any new pattern. Both a positive case (the pattern should fire) and a negative case (a similar shape that should not).

## Verifying the plugin still loads

A plugin format change can silently break things. Before merging:

1. `tests/run.sh` should pass.
2. `cat .claude-plugin/plugin.json | python3 -c 'import json,sys; json.load(sys.stdin)'` should not error.
3. `cat hooks/hooks.json | python3 -c 'import json,sys; json.load(sys.stdin)'` should not error.
4. Install the plugin locally (`/plugin install file:///path/to/version-aware`) and verify the hook fires by running any Bash tool and watching for the `STALENESS WARNING` block when a flagged version is installed.

## Things this project will not accept

- Cutoffs based on assumptions about specific models. The map is a conservative *floor*, not a per-model knowledge base.
- Patterns that need an LLM to evaluate. Everything is regex by design. Speed matters: the hook runs before every Bash tool invocation.
- Claim types like "spelling errors" or "TODO comments" that aren't about staleness. Wrong tool.

## Related projects

- [lisancao/spark-skills](https://github.com/lisancao/spark-skills): version-pinned Apache Spark reference docs, validated against Spark 4.1. A complementary install for any project doing Spark work; gives Claude concrete current-version knowledge to match against the staleness signal.
- [lisancao/lakehouse-skills](https://github.com/lisancao/lakehouse-skills): broader lakehouse skills (Iceberg, Delta, MLflow, etc.).

## License

Apache 2.0. Same as the project.
