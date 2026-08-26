# Offline synthetic demo

This tiny repository contains one intentionally flaky test. It randomly passes
or fails because it incorrectly expects a random binary value to always be
zero. The mock diagnoser recognizes this exact fixture and replaces the invalid
assertion in a copied repository; the original demo file is never changed.
