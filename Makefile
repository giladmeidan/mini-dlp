up:
	docker compose up --build -d --wait

down:
	docker compose down -v

test:
	docker compose up -d --wait db && uv run pytest -q

# Phony: a directory named postman/ exists, so without it make reports "up to date" and runs nothing.
.PHONY: postman
postman:
	npx --yes newman@6.2.3 run postman/mini-dlp.postman_collection.json
