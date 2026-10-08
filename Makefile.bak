.PHONY: build dev stop clean up down logs shell migrate admin help

build:  ## Bootstrap: start PostgreSQL, migrate, seed admin user
	bash scripts/setup-dev.sh

dev:    ## Run the Django dev server
	cd backend && .venv/bin/python3 manage.py runserver

stop:   ## Stop the dev PostgreSQL container
	docker stop eixn-pos-db 2>/dev/null || true
	docker rm eixn-pos-db 2>/dev/null || true

clean:  ## Stop container and remove .pyc / __pycache__
	$(MAKE) stop
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

up:     ## Deploy via docker-compose
	docker compose up --build -d

down:   ## Tear down docker-compose
	docker compose down

logs:   ## Tail all logs
	docker compose logs -f

shell:  ## Django shell
	cd backend && python3 manage.py shell

migrate: ## Run migrations
	cd backend && python3 manage.py migrate

admin:  ## Seed or reset admin user (admin/admin)
	cd backend && python3 manage.py shell -c "from users.models import User; User.objects.get_or_create(username='admin', defaults={'role': User.Role.ADMIN, 'is_superuser': True, 'is_staff': True}); u = User.objects.get(username='admin'); u.set_password('admin'); u.role = User.Role.ADMIN; u.is_superuser = True; u.is_staff = True; u.save(); print('Admin user ready (admin / admin).')"

help:   ## Show this help
	@echo "Usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
