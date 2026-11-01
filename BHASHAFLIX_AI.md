# BhashaFlix AI (new project in this repository)

This repository also contains **BhashaFlix AI** — an AI movie-dubbing application that replaces only
the spoken dialogue of a movie with AI voices in the viewer's language while keeping the original
video stream byte-identical.

- Source, setup and documentation: [`bhashaflix-ai/README.md`](bhashaflix-ai/README.md)
- Run it: `cd bhashaflix-ai && pip install -r requirements.txt && make run` → <http://localhost:8000>
- Tests: `cd bhashaflix-ai && make test` (47 real tests, ~20 s, no mocks)
- Demo: `cd bhashaflix-ai && make demo`

It lives in its own folder so the existing YOUPI PG payment-gateway project in this repository is
completely untouched.
