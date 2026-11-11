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

## On a server of your own

The app can also talk to an engine that runs elsewhere (Settings > Engine and data > On my own server).
Install the package on the server, create a key with `jobradar api-token`, start `jobradar serve --host
0.0.0.0` behind HTTPS, and enter the address and the key in the app. Keep the key secret: it gives access
to your profile and applications.
