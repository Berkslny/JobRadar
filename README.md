# JobRadar

JobRadar is a Mac app that looks for jobs for you, judges every posting against your real CV, and writes
honest application documents for the ones you choose. It runs on your Mac, with the AI model you connect.

**Download:** [JobRadar-1.1.dmg](https://github.com/Berkslny/JobRadar/raw/main/downloads/JobRadar-1.1.dmg) (macOS 26 or later)

Türkçe: [README.tr.md](README.tr.md)

## What it does

- **Finds postings** on job boards (LinkedIn, Indeed, Google Jobs and others through JobSpy), on company career
  pages (Greenhouse, Lever, Ashby, Personio, Workday, SmartRecruiters, Recruitee, Softgarden), on Germany's
  Bundesagentur für Arbeit, and from links you add yourself.
- **Scores each posting** from 0 to 5 with your AI model. Every requirement is matched to a line of your
  profile, so you can see why a job fits or not.
- **Writes a CV and cover letter for a posting**, using only facts from your profile. A second reading and a
  check of the PDF catch mistakes. Nothing is sent anywhere; you apply yourself.
- **Keeps track** of your applications, reminds you to follow up, and can spot replies from companies in
  your mailbox (read-only).
- **Matches by meaning, if you turn it on.** *Smart matching* (Settings > Matching) compares every posting
  with your search tracks and your profile, using a small embedding model that runs on your Mac. The AI
  model then sees first the postings that keywords and meaning agree on, and a posting your keywords would
  miss can still reach you. The rules you set yourself always hold.
- **Measures itself on your verdicts.** The status page shows how many of the postings ranked first are
  ones you want, how many wanted postings never reach the AI model, how often the AI model judges like
  you, and what the model calls add up to. *Judge jobs…* asks you about a random sample to make these
  numbers honest.
- **Speaks English and Turkish**, follows the light or dark look of your Mac, and uses Liquid Glass.
- **Lets you look first.** *Look around with sample data* opens the app with made-up jobs and a made-up
  profile, without an AI model or a scan.

## Requirements

- macOS 26 or later (Apple silicon or Intel)
- An internet connection. On first start the app downloads Python and its libraries once (about 150 MB)
  into `~/Library/Application Support/JobRadar/runtime`.
- An AI model of your own. Any one of these:
  - **Claude Code** installed and signed in on the Mac (uses your Claude subscription)
  - an **Anthropic API key**
  - an **OpenAI-compatible** service (OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio…)
  - **Ollama** (free, runs on the Mac)

  Without a model JobRadar still collects and sorts postings, but it cannot evaluate them or write documents.

## Installing

1. Download [JobRadar-1.1.dmg](https://github.com/Berkslny/JobRadar/raw/main/downloads/JobRadar-1.1.dmg), open it and drag JobRadar into Applications.
2. Open JobRadar. The download is not notarised by Apple, so the first time macOS refuses to open it.
   Close that message, open **System Settings > Privacy & Security**, scroll down to the line about
   JobRadar, choose **Open Anyway** and confirm. This is needed once.
3. The assistant leads you through four steps: language and look, AI model, your profile (drop your CV and
   check what was read), and what to search for. Then start the first scan.

The app stays in the menu bar while it is open and scans at 08:00, 13:00 and 19:00.

**Updating from an earlier version.** Quit JobRadar (the button in its menu bar window), download the new
disk image and drag JobRadar into Applications again, replacing the old copy. Your data stays where it is.
On its first start the new version brings its engine up to date, and macOS asks once more for
**Open Anyway**, because every download is a new app to it. For the same reason, when JobRadar keeps a
secret for you (an API key, the e-mail app password, the key of your server), macOS asks for your login
password before the new copy may read it. Choose **Always Allow**; it asks once per secret, and JobRadar
goes on after you answered.

## Where your data lives

Everything is in one folder on your Mac, by default `~/Library/Application Support/JobRadar/workspace`:
your profile (`data/profile.yaml`), settings, the job database and the generated documents. You can choose
another folder in **Settings > Engine and data**. API keys and the e-mail app password are kept in the
macOS Keychain, never in a file. Requests leave the Mac only for the job boards, for the AI model you
connected, and for your own mailbox. With smart matching turned on, its model (about 220 MB) is downloaded
once from Hugging Face; the comparison itself happens on your Mac.

If an earlier JobRadar (the command line version) left its data in `~/projects/jobradar`, the app offers to
bring it over: profile, jobs, documents and settings are copied into the folder above, and the earlier
folder is left as it is.

## About the AI model options

- **Claude Code.** JobRadar starts the Claude Code program that is installed on your Mac (`claude -p`),
  unmodified, and you sign in to it yourself. JobRadar never asks for, reads or stores your Claude login.
  How Anthropic counts this use against your plan is set by Anthropic; see
  <https://code.claude.com/docs/en/legal-and-compliance> and your plan's terms.
- **API keys** are billed per use by the provider.
- **Ollama and LM Studio** run on your Mac and cost nothing. Small local models judge postings less well.

If you publish a build of this app: Anthropic's terms do not allow third-party apps to offer a Claude.ai
login or to route requests through a user's Free, Pro or Max credentials. This app does neither. Each
person uses their own Claude Code installation or their own API key. Read the page linked above before you
distribute the app; this is a description of how the app works, not legal advice.

## Building it yourself

1. Open `JobRadar.xcodeproj` in Xcode 27 or later.
2. Press ⌘R.

The project is set to *Sign to Run Locally*, so it builds without an Apple developer account. If you want
your own signature on your builds, choose your team in the target's **Signing & Capabilities**.

To make the disk image, either double-click `scripts/make-dmg.command`, or in the running app choose
**Settings > Advanced > Create a disk image…**. Both make a release build and put `JobRadar-<version>.dmg`
into `dist/` when the app runs from Xcode. In an installed copy, the menu command packs that copy as it is.

**Signing.** Without a *Developer ID Application* certificate, the app in the disk image gets a local
(ad hoc) signature that names nobody, and other Macs show the warning described under Installing. When a
Developer ID certificate (Apple Developer Program) is installed, `make-dmg.command` signs with it. To also
notarise, so that the warning does not appear, give it a keychain profile:

```
xcrun notarytool store-credentials jobradar-notary --apple-id you@example.com --team-id YOURTEAMID
JOBRADAR_NOTARY_PROFILE=jobradar-notary scripts/make-dmg.command
```

## Project layout

| Path | What |
|---|---|
| `JobRadar/` | The Mac app (SwiftUI). `L10nTurkish.swift` is generated from `tools/tr_table.py`. |
| `JobRadar/jobradar-1.1.0-py3-none-any.whl` | The engine as the app carries it. |
| `engine/` | The engine's source (Python): sources, scoring, tailoring, the local API. |
| `scripts/` | `make-dmg.command`, `build-engine.command`. |
| `downloads/` | The disk image of the current version. |
| `tools/` | Translation table and checks. |
| `.github/workflows/ci.yml` | Checks on every pull request and every push to main: engine tests, a build of the app, smart matching with the real model. |

After changing the engine: `scripts/build-engine.command`, then build the app again
(`python3 tools/check_wheel.py` tells you when that was forgotten).
Engine tests: `cd engine && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest`.
After changing interface texts: add the Turkish text to `tools/tr_table.py` and run `python3 tools/l10n.py write`.

The engine can also run without the app (`jobradar serve`, `jobradar run`); its command line and its
optional web panel are in Turkish for now.

## Versions

- **1.1**: smart matching (Settings > Matching, off until you turn it on) and measurements on your own
  verdicts (status page).
- **1.0**: the first release.

## Fair use of job boards

Job boards restrict automated reading in their terms. JobRadar reads them slowly, for one person's own
search. Use it that way, and switch a source off if its operator asks you to.

## Licence and credits

MIT, see [LICENSE](LICENSE). Credits are in [NOTICE.md](NOTICE.md).
