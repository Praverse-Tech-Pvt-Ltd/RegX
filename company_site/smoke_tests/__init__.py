"""Smoke tests for the carried-in company site (run: ./run_tests.sh).

Hard rule: OPENAI_API_KEY must never be set while these tests run. The
company's FDA-483 summariser (AIDatabase/observation_summary.py) calls OpenAI
for every observation block whenever a key is present, and GET / alone once
triggered 71 paid calls. The check below fails the whole run at import time,
before any test or page load, if the key is set in the environment.
"""

import os

if os.environ.get("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY is set. company_site tests must run without it: unset it "
        "and run again. Nothing was executed."
    )
