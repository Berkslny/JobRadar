# JobRadar engine

The Python part of JobRadar: it collects postings, filters and scores them, evaluates them with the AI model
you connect, writes tailored CVs and letters, and serves a local API (`/api/v1`) that the Mac app talks to.

The Mac app installs and starts this engine by itself. You only need this folder to work on the engine.

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Run it without the app:

```
.venv/bin/jobradar serve --workspace ~/jobradar-data      # local API and web panel
.venv/bin/jobradar run                                    # one scan from the command line
```

The command line and the web panel are in Turkish for now; the API and everything the Mac app shows are
available in English and Turkish (`X-JobRadar-Lang: en|tr`).

Layout: `src/jobradar/sources` (job boards and career systems), `processing` (normalising, filters, flags),
`scoring` (quick score, AI evaluation, model providers), `tailor` (documents, validation, PDF), `web`
(API and panel), `templates` (starting files for a workspace).

To hand a new engine to the app, run `scripts/build-engine.command` in the project root.

## Measuring and smart matching

```
.venv/bin/jobradar label JOB_ID good|maybe|bad      # your own verdict on a posting
.venv/bin/jobradar bench                            # what the rankings and the rules do with your verdicts
.venv/bin/pip install -e ".[match]"                 # the built-in embedding model (fastembed, ONNX, no PyTorch)
.venv/bin/jobradar match                            # embed and score what is there (matching.enabled: true)
```

`bench` needs no model. It reads your verdicts (labels, and what you did with a posting: shortlisted or
applied counts as "fits", skipped as "does not fit") and reports, on those postings:

- **Rankings**: precision in the first 10 and in the first `llm_max_per_run`, NDCG@10 and AUC for the
  quick score, the semantic score, both fused, and the AI score.
- **The gate**: per group (evaluated, waiting for the AI model, quick score too low, filtered by the track
  rule) how many postings you judged and how many of those you want, and from that an estimate of how many
  wanted postings never reach the AI model. `GET /api/v1/labels/queue` hands out postings to judge in a
  fixed random order, in turn from each group, so the shares hold for the whole group.
- **The judge**: agreement between the AI verdict and yours (Cohen's kappa; 0.6 and above is good).
- **Model use**: calls, tokens, time and API-equivalent cost by purpose (table `llm_calls`; sizes only,
  never a prompt or an answer).

Smart matching (`matching:` in jobradar.yaml, off by default) embeds each posting (its title, then tasks
and requirements, at most four pieces) and compares it with your tracks and your profile. The vectors are
kept in SQLite; the arithmetic is plain Python. Two things change when it is on:

- The order of the AI evaluations fuses the keyword rank and the semantic rank
  (reciprocal rank fusion, `1/(60+rank)` each).
- A posting that only the track rule filtered out, or whose quick score is below `prescore_min`, is promoted
  when its semantic score is above the median of the postings that do match keywords (at least 20 of those
  are needed, at most `promote_max_per_run` per scan). Rules you set yourself are never overridden, and a
  promoted posting carries the "Semantic match" badge.

The built-in model is downloaded once from Hugging Face into `data/models`. An embedding model of a local
Ollama (`provider: ollama`) or any OpenAI-compatible `/embeddings` endpoint works as well; a paid endpoint
needs `llm.allow_paid_api: true`, like a paid AI model.

## On a server of your own

The app can also talk to an engine that runs elsewhere (Settings > Engine and data > On my own server).
Install the package on the server, create a key with `jobradar api-token`, start `jobradar serve --host
0.0.0.0` behind HTTPS, and enter the address and the key in the app. Keep the key secret: it gives access
to your profile and applications.
