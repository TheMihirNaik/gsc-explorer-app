"""Gunicorn configuration for the GSC Explorer web process.

Gunicorn's defaults are one sync worker with one thread, which means the
whole app serves exactly one request at a time. Every route here blocks on
Google Search Console I/O for seconds to minutes, so a single 15-month fetch
made every other visitor wait -- including on pages that do no work at all.

Threads, not processes, are the fix: this workload is I/O bound, waiting on
HTTP responses from Google and OpenAI. A thread costs a stack; a worker costs
a second copy of pandas, scikit-learn, umap and the rest of the import graph
(~250-400 MB resident before serving anything). So the default here is one
worker with eight threads, which is memory-neutral against the old config.

Raise WEB_CONCURRENCY above 1 only after checking the box has headroom:

    ps -o rss=,cmd= -C gunicorn

Gunicorn reads this file automatically when it is in the working directory,
so it applies even to a bare `gunicorn run:app` start command.
"""

import os

# I/O-bound workload: threads let requests overlap while they wait on Google.
worker_class = "gthread"

# One interpreter by default -- same memory profile as the previous config.
# Each extra worker duplicates the full import graph, so raise deliberately.
workers = int(os.getenv("WEB_CONCURRENCY", "1"))

# Concurrent requests per worker. Mostly idle, waiting on the GSC API.
threads = int(os.getenv("GUNICORN_THREADS", "8"))

# Unchanged: the long reports genuinely need minutes on large properties.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "180"))

# Let in-flight requests finish on redeploy instead of being cut off.
graceful_timeout = 30

# Hold connections open briefly for HTMX partials fetched back to back.
keepalive = 5
