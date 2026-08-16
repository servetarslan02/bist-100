# ALPHA v4 Clean Core

This directory is the governed rebuild path for ALPHA.

Current implemented and test-gated primitives:
- point-in-time canonical events with evidence references;
- raw OHLCV validation before feature calculation;
- mask-first return calculation;
- structured contract-event interpretation without a single news/sentiment score;
- company-relative materiality and explicit unknowns/cautions.

This package is not production-ready yet. Promotion requires passing the CI gate and the migration criteria in `memory/ROADMAP-v4.md`.
