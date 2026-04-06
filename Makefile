COMPOSE_LOCAL = docker/docker-compose.yml
COMPOSE_RALPHEX = docker/docker-compose.postgres.redis.ralphex.yml

run_l:
	docker compose -f $(COMPOSE_LOCAL) up -d

stop_l:
	docker compose -f $(COMPOSE_LOCAL) down

test:
	docker compose -f $(COMPOSE_LOCAL) run --rm app pytest tests/ -v

test_unit:
	pytest tests/unit/ -v

run_for_ralphex:
	docker compose -f $(COMPOSE_RALPHEX) up -d

stop_for_ralphex:
	docker compose -f $(COMPOSE_RALPHEX) down

.PHONY: run_l stop_l test test_unit run_for_ralphex stop_for_ralphex
