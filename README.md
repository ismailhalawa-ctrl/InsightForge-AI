# InsightForge AI

AI-powered platform for analyzing web content — starting with YouTube — using NLP, sentiment analysis, and large language models.

## Status

The backend implements YouTube video/comment retrieval and multi-language (Arabic/English/mixed)
sentiment analysis, exposed via FastAPI. There is no custom frontend yet — the current interface
is FastAPI's Swagger UI. No authentication, background jobs, or LLM features have been
implemented yet.

To run the backend locally, see [backend/README.md](backend/README.md).

## Structure

See [docs/Architecture.md](docs/Architecture.md) for the architecture overview and `backend/`, `frontend/`, `docker/`, and `docs/` for the top-level layout.

## License

MIT — see [LICENSE](LICENSE).
