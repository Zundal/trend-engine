.PHONY: install test offline serve demo doctor record
install: ; uv sync --all-extras
test: ; uv run pytest -q
offline: ; uv run trend-engine --offline collect
demo: ; uv run trend-engine --offline serve
serve: ; uv run trend-engine serve
doctor: ; uv run trend-engine doctor
record: ; uv run trend-engine record --regions KR,KR-11,US,JP
