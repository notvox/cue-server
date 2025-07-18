# NotVox Development Makefile
# Control the NotVox server and development environment

# Configuration
# Load environment variables from .env file
ifneq (,$(wildcard .env))
	include .env
	export SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET SPOTIFY_REDIRECT_URI
endif

PID_FILE := .notvox-server.pid
LOG_FILE := notvox-server.log
PYTHON := python
PIP := pip

# Colors for output
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
BLUE := \033[0;34m
NC := \033[0m # No Color

# Default target
.DEFAULT_GOAL := help

# Phony targets
.PHONY: help start stop restart status logs install clean test dev setup run kill health cue port-check port-kill

help: ## Show this help message
	@echo "$(BLUE)🎵 NotVox Development Commands$(NC)"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "$(GREEN)Main targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-15s$(NC) %s\n", $1, $2}'
	@echo ""
	@echo "$(GREEN)Quick examples:$(NC)"
	@echo "  make start         # Start the server"
	@echo "  make test          # Run integration tests"
	@echo "  make cue           # Play a test track"
	@echo "  make logs          # Follow server logs"

# Dependency management
check-deps: ## Check if dependencies are installed
	@echo "$(BLUE)🔍 Checking dependencies...$(NC)"
	@$(PYTHON) -c "import flask, spotipy, requests, click" 2>/dev/null && echo "$(GREEN)✅ All dependencies installed$(NC)" || echo "$(RED)❌ Missing dependencies. Run 'make install'$(NC)"

install: ## Install Python dependencies globally
	@echo "$(BLUE)📦 Installing dependencies...$(NC)"
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✅ Dependencies installed globally$(NC)"

setup: install ## Initial setup (alias for install)

# Server management
port-check: ## Check what's using port 8080
	@echo "$(BLUE)🔍 Checking port 8080...$(NC)"
	@lsof -i :8080 || echo "$(GREEN)✅ Port 8080 is free$(NC)"

port-kill: ## Kill whatever is using port 8080
	@echo "$(BLUE)🔫 Killing process on port 8080...$(NC)"
	@lsof -ti:8080 | xargs kill -9 2>/dev/null && echo "$(GREEN)✅ Port 8080 freed$(NC)" || echo "$(YELLOW)⚠️  Nothing running on port 8080$(NC)"

start: ## Start the NotVox server
	@echo "🚀 Delegating start to dev.sh..."
	@./dev.sh start

stop: ## Stop the NotVox server
	@echo "🛑 Delegating stop to dev.sh..."
	@./dev.sh stop

restart: ## Restart the NotVox server
	@echo "🔄 Delegating restart to dev.sh..."
	@./dev.sh restart

status: ## Check server status
	@echo "🔍 Delegating status to dev.sh..."
	@./dev.sh status

logs: ## Follow server logs (Ctrl+C to exit)
	@echo "📝 Delegating logs to dev.sh..."
	@./dev.sh logs

# Development helpers
run: start ## Alias for 'start'

dev: check-deps start logs ## Start server and follow logs

kill: stop ## Force kill the server (alias for stop)

health: ## Check server health endpoint
	@curl -s http://localhost:8080/health | python -m json.tool || echo "$(RED)❌ Server not responding$(NC)"

test: ## Run integration tests
	@if [ ! -f $(PID_FILE) ] || ! kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "$(YELLOW)⚠️  Starting server for tests...$(NC)"; \
		$(MAKE) start; \
		sleep 2; \
	fi
	@echo "$(BLUE)🧪 Running integration tests...$(NC)"
	@$(PYTHON) test_notvox.py

# Quick test commands
cue: ## Play a test track for 30 seconds
	@echo "$(BLUE)🎵 Playing test track...$(NC)"
	notvox cue "Never Gonna Give You Up" 30s

queue-test: ## Test queue functionality
	@echo "$(BLUE)🎵 Testing queue...$(NC)"
	notvox queue add "test song 1" 20s
	notvox queue add "test song 2" 20s
	notvox queue

skip-test: ## Test skip functionality
	@echo "$(BLUE)⏭️  Testing skip...$(NC)"
	notvox skip

# Cleanup
clean: ## Clean up generated files
	@echo "$(BLUE)🧹 Cleaning up...$(NC)"
	@rm -f $(PID_FILE) $(LOG_FILE)
	@rm -rf __pycache__ .pytest_cache
	@rm -f .spotify_cache
	@rm -f notvox.db
	@echo "$(GREEN)✅ Cleaned up$(NC)"

clean-logs: ## Clean only log files
	@echo "$(BLUE)🧹 Cleaning logs...$(NC)"
	@rm -f $(LOG_FILE)
	@echo "$(GREEN)✅ Logs cleaned$(NC)"

# Database management
db-reset: ## Reset the database
	@echo "$(BLUE)🗄️  Resetting database...$(NC)"
	@rm -f notvox.db
	@echo "$(GREEN)✅ Database reset$(NC)"

db-backup: ## Backup the database
	@echo "$(BLUE)🗄️  Backing up database...$(NC)"
	@cp notvox.db notvox.db.backup.$$(date +%Y%m%d_%H%M%S) 2>/dev/null || echo "$(YELLOW)⚠️  No database to backup$(NC)"
	@echo "$(GREEN)✅ Database backed up$(NC)"

# Installation helpers
deps: install ## Install dependencies (alias)

update-deps: ## Update all dependencies
	@echo "$(BLUE)📦 Updating dependencies...$(NC)"
	$(PIP) install --upgrade -r requirements.txt
	@echo "$(GREEN)✅ Dependencies updated$(NC)"

freeze: ## Freeze current dependencies
	$(PIP) freeze | grep -E "^(Flask|spotipy|requests|click|schedule)" > requirements.txt
	@echo "$(GREEN)✅ Requirements frozen$(NC)"

# Development workflow
watch: ## Watch logs in real-time
	@$(MAKE) logs

quick-test: ## Run a quick functionality test
	@echo "$(BLUE)🧪 Running quick test...$(NC)"
	@notvox status
	@notvox cue "test" 10s
	@sleep 2
	@notvox status
	@notvox stop
	@echo "$(GREEN)✅ Quick test completed$(NC)"

# Info targets
info: ## Show current configuration
	@echo "$(BLUE)ℹ️  NotVox Configuration$(NC)"
	@echo "  SPOTIFY_CLIENT_ID: $(SPOTIFY_CLIENT_ID)"
	@echo "  SPOTIFY_REDIRECT_URI: $(SPOTIFY_REDIRECT_URI)"
	@echo "  PID_FILE: $(PID_FILE)"
	@echo "  LOG_FILE: $(LOG_FILE)"
	@echo "  Python: $(which python)"
	@echo "  Pip: $(which pip)"

version: ## Show NotVox version
	@$(PYTHON) -c "import __init__; print(f'NotVox version: {__init__.__version__}')" 2>/dev/null || echo "0.1.0"

which-python: ## Show which Python is being used
	@echo "$(BLUE)🐍 Python configuration:$(NC)"
	@echo "  Python: $(which python)"
	@echo "  Version: $(python --version)"
	@echo "  Pip: $(which pip)"