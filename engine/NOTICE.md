# Sources and thanks

JobRadar was written from scratch. It uses ideas and documentation from the projects below.

| Project | Licence | What was taken |
|---|---|---|
| [career-ops](https://github.com/career-ops-hq/career-ops) | MIT | Endpoints and page structures of Arbeitsagentur v6, Rheinmetall, Softgarden, Personio, Workday and SmartRecruiters; the evaluation dimensions (CV match, fit with the goal, pay, culture, risks), the 4.0 apply threshold, importing LinkedIn alert e-mails, matching Connections.csv, and the idea of a cautious "is the posting closed" check. The code was rewritten in Python. |
| [JobSpy](https://github.com/speedyapply/JobSpy) | MIT | Used as a library (LinkedIn, Indeed, Glassdoor and others). Installed separately on first start. |
| [JobNavigator](https://github.com/vesaias/JobNavigator) | MIT | Ideas for de-duplication across sources and URL identity, two-stage scoring, Telegram notifications and source health warnings. |
| [JobCtrl](https://github.com/ebarti/JobCtrl) | AGPL-3.0 | Ideas only: tying every CV bullet to a fact in the profile, rejecting drafts with invented content, and never sending an application without approval. No code was taken. |
| [bundesAPI/jobsuche-api](https://github.com/bundesAPI/jobsuche-api) | Documentation | Parameters of the Jobsuche API and the jobdetails endpoint. |
| [freehire.me API](https://freehire.me/jobs-api) | Terms of use | Reading without a key for personal, non-commercial use. Off by default. |
| [uv](https://github.com/astral-sh/uv) | MIT / Apache-2.0 | Downloaded on first start to install Python and the libraries. |
| [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | MPL-2.0 and others | The Python that uv installs for the engine. |
| [fastembed](https://github.com/qdrant/fastembed) | Apache-2.0 | Used as a library for smart matching (embedding models on ONNX Runtime). Installed only when smart matching is turned on. |
| [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | Apache-2.0 | The standard embedding model of smart matching. Downloaded from Hugging Face on first use. Other models can be chosen; each comes under its own licence. |

Python libraries the engine installs on first start: httpx, pydantic, PyYAML, typer, rich, Jinja2, FastAPI,
uvicorn, Beautiful Soup, python-multipart, pypdf (each under its own open-source licence).
