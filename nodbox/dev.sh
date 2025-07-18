#!/bin/bash

# NotVox Development Service Manager
# Simple alternative to systemd/launchd for local development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
PID_FILE="$SCRIPT_DIR/.notvox-server.pid"
LOG_FILE="$SCRIPT_DIR/notvox-server.log"
ENV_FILE="$SCRIPT_DIR/.env"

# Load environment variables from .env file if it exists
if [[ -f "$ENV_FILE" ]]; then
    echo "📋 Loading environment from .env"
    set -a  # automatically export all variables
    source "$ENV_FILE"
    set +a  # turn off automatic export
fi

start_server() {
    if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "🎵 NotVox server is already running (PID: $(cat "$PID_FILE"))"
        return 0
    fi
    
    echo "🚀 Starting NotVox server..."
    
    # Verify Spotify credentials are loaded
    if [[ -z "$SPOTIFY_CLIENT_ID" ]] || [[ -z "$SPOTIFY_CLIENT_SECRET" ]]; then
        echo "❌ Missing Spotify credentials!"
        echo "   Please ensure .env file contains:"
        echo "   SPOTIFY_CLIENT_ID=your_client_id"
        echo "   SPOTIFY_CLIENT_SECRET=your_client_secret"
        return 1
    fi
    
    # Create virtual environment if it doesn't exist
    if [[ ! -d "$VENV_DIR" ]]; then
        echo "📦 Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
        pip install -r requirements.txt
    else
        source "$VENV_DIR/bin/activate"
    fi
    
    # Start server in background
    cd "$SCRIPT_DIR"
    nohup python server.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    
    # Wait a moment and check if it started successfully
    sleep 2
    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "✅ NotVox server started successfully!"
        echo "📊 PID: $(cat "$PID_FILE")"
        echo "🌐 Server: http://localhost:8080"
        echo "📝 Logs: tail -f $LOG_FILE"
    else
        echo "❌ Failed to start server. Check logs:"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "🛑 NotVox server is not running"
        return 0
    fi
    
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "🛑 Stopping NotVox server (PID: $PID)..."
        kill "$PID"
        
        # Wait up to 10 seconds for graceful shutdown
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        
        # Force kill if still running
        if kill -0 "$PID" 2>/dev/null; then
            echo "🔨 Force killing server..."
            kill -9 "$PID"
        fi
        
        echo "✅ NotVox server stopped"
    fi
    
    rm -f "$PID_FILE"
}

status_server() {
    if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        echo "✅ NotVox server is running (PID: $PID)"
        echo "🌐 Server: http://localhost:8080"
        echo "📝 Logs: tail -f $LOG_FILE"
        
        # Test server responsiveness
        if command -v curl >/dev/null 2>&1; then
            if curl -s http://localhost:8080/status >/dev/null 2>&1; then
                echo "🔄 Server is responding"
            else
                echo "⚠️  Server process running but not responding"
            fi
        fi
        
        # Show environment status
        if [[ -n "$SPOTIFY_CLIENT_ID" ]]; then
            echo "🎵 Spotify credentials loaded"
        else
            echo "⚠️  No Spotify credentials in environment"
        fi
    else
        echo "🛑 NotVox server is not running"
        if [[ -f "$PID_FILE" ]]; then
            echo "🧹 Cleaning up stale PID file"
            rm -f "$PID_FILE"
        fi
    fi
}

restart_server() {
    echo "🔄 Restarting NotVox server..."
    stop_server
    sleep 1
    start_server
}

logs_server() {
    if [[ -f "$LOG_FILE" ]]; then
        echo "📝 NotVox server logs (tail -f to follow):"
        echo "----------------------------------------"
        tail -f "$LOG_FILE"
    else
        echo "📝 No log file found at $LOG_FILE"
    fi
}

case "${1:-start}" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    restart)
        restart_server
        ;;
    status)
        status_server
        ;;
    logs)
        logs_server
        ;;
    *)
        echo "🎵 NotVox Development Service Manager"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the NotVox server"
        echo "  stop    - Stop the NotVox server"
        echo "  restart - Restart the NotVox server"
        echo "  status  - Check server status"
        echo "  logs    - Show server logs (tail -f)"
        echo ""
        echo "Quick test commands after starting:"
        echo "  notvox status"
        echo "  notvox cue 'test song' 30s"
        echo "  notvox stop"
        exit 1
        ;;
esac