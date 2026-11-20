# Third-party notice: HappySearch

This package vendors the web-retrieval engine layer of **HappySearch**.

- Source: https://github.com/xkx121029/happy-search
- Upstream commit: `c1f64f1` ("feat: HappySearch 面向 AI 的搜索 API 服务（M1）")
- License: MIT (see `LICENSE` in this directory)
- Copyright: Copyright (c) 2026 HappySearch contributors

## What was vendored

- `app/providers/free_engines.py` -> `engines.py`
- `app/providers/ddg.py` (DuckDuckGo parsers) -> `engines.py`
- `app/providers/free.py` (engine orchestration + RRF fusion) -> `search.py`
- `app/core/models.py` -> `models.py`
- `app/core/ranker.py` -> `ranker.py`

## What was changed

- Removed FastAPI, Uvicorn, request schemas, authentication, rate limiting,
  local index, `/v1/fetch` and all other HTTP-service concerns.
- Replaced the global `settings` object with injectable configuration in
  `config.py` (environment-variable driven).
- Added a process-wide in-flight engine semaphore and a hard total budget.
- Added last-run status counters (`status.py`) and a LangChain tool wrapper
  (`octop/infra/search/happy_tool.py`).
- Removed the local-index branch of the ranker (unused by the tool).

The MIT license text is preserved verbatim in `LICENSE`. Redistributions
(wheel, onedir bundle, Docker image) must keep both files.
