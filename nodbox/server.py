#!/usr/bin/env python3
"""
NotVox Server - Networked Spotify Control System
Handles auth refresh and playback commands with duration support
"""

import os
import time
import threading
import sqlite3
import random
from collections import Counter
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import schedule
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class NotVoxServer:
    def __init__(self):
        self.spotify = None
        self.current_session = None
        self.session_timer = None
        self.queue_enabled = True  # Flag to enable/disable queue processing
        self.init_database()
        self.init_spotify()
        
        # Start background auth refresh
        self.start_auth_refresh()
    
    def init_database(self):
        """Initialize SQLite database for session state and queue"""
        self.conn = sqlite3.connect('notvox.db', check_same_thread=False)
        
        # Sessions table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                track_name TEXT,
                track_uri TEXT,
                start_time TEXT,
                end_time TEXT,
                duration_seconds INTEGER,
                status TEXT
            )
        ''')
        
        # Queue table
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY,
                track_name TEXT,
                track_uri TEXT,
                duration_seconds INTEGER,
                added_at TEXT,
                position INTEGER,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        self.conn.commit()
    
    def init_spotify(self):
        """Initialize Spotify client with auth"""
        try:
            # Updated scope to include recently played
            scope = "user-modify-playback-state user-read-playback-state user-read-recently-played"
            
            self.spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=os.getenv('SPOTIFY_CLIENT_ID'),
                client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
                redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8080/callback'),
                scope=scope,
                cache_path='.spotify_cache'
            ))
            
            # Test the connection
            self.spotify.current_user()
            logger.info("Spotify authentication successful")
            
        except Exception as e:
            logger.error(f"Spotify auth failed: {e}")
            self.spotify = None
    
    def refresh_auth(self):
        """Refresh Spotify auth tokens"""
        try:
            if self.spotify and self.spotify.auth_manager:
                token_info = self.spotify.auth_manager.get_cached_token()
                if token_info:
                    # Check if token needs refresh (50 minute buffer)
                    expires_at = token_info.get('expires_at', 0)
                    if time.time() > (expires_at - 600):  # 10 min buffer
                        logger.info("Refreshing Spotify token...")
                        self.spotify.auth_manager.refresh_access_token(token_info['refresh_token'])
                        logger.info("Token refreshed successfully")
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
    
    def start_auth_refresh(self):
        """Start background thread for token refresh"""
        def refresh_worker():
            schedule.every(50).minutes.do(self.refresh_auth)
            while True:
                schedule.run_pending()
                time.sleep(60)
        
        refresh_thread = threading.Thread(target=refresh_worker, daemon=True)
        refresh_thread.start()
        logger.info("Auth refresh thread started")
    
    def parse_duration(self, duration_str):
        """Parse duration string (e.g., '2d', '30m', '1h') to seconds"""
        duration_str = duration_str.lower().strip()
        
        if duration_str.endswith('d'):
            return int(duration_str[:-1]) * 24 * 3600
        elif duration_str.endswith('h'):
            return int(duration_str[:-1]) * 3600
        elif duration_str.endswith('m'):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith('s'):
            return int(duration_str[:-1])
        else:
            # Assume minutes if no unit
            return int(duration_str) * 60
    
    def search_and_play(self, query, duration_str):
        """Search for track and start playback with timer"""
        if not self.spotify:
            return {"error": "Spotify not authenticated"}, 500
        
        try:
            # Stop any existing session
            self.stop_current_session()
            
            # Search for track
            results = self.spotify.search(q=query, type='track', limit=1)
            if not results['tracks']['items']:
                return {"error": f"No tracks found for '{query}'"}, 404
            
            track = results['tracks']['items'][0]
            track_uri = track['uri']
            track_name = f"{track['name']} by {track['artists'][0]['name']}"
            
            # Start playback
            self.spotify.start_playback(uris=[track_uri])
            
            # Parse duration and set timer
            duration_seconds = self.parse_duration(duration_str)
            start_time = datetime.now()
            end_time = start_time + timedelta(seconds=duration_seconds)
            
            # Save session to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, 'playing'))
            
            session_id = cursor.lastrowid
            self.conn.commit()
            
            # Set timer to stop playback
            self.session_timer = threading.Timer(duration_seconds, self.stop_playback_timer)
            self.session_timer.start()
            
            self.current_session = {
                'id': session_id,
                'track_name': track_name,
                'track_uri': track_uri,
                'start_time': start_time,
                'end_time': end_time,
                'duration_seconds': duration_seconds
            }
            
            logger.info(f"Started playing: {track_name} for {duration_str}")
            
            return {
                "message": f"Now playing: {track_name}",
                "duration": duration_str,
                "ends_at": end_time.isoformat()
            }, 200
            
        except Exception as e:
            logger.error(f"Playback error: {e}")
            return {"error": str(e)}, 500
    
    def stop_playback_timer(self):
        """Called by timer to stop playback and process queue"""
        try:
            if self.spotify:
                self.spotify.pause_playback()
            
            if self.current_session:
                # Update database
                cursor = self.conn.cursor()
                cursor.execute('''
                    UPDATE sessions SET status = ? WHERE id = ?
                ''', ('completed', self.current_session['id']))
                self.conn.commit()
                
                logger.info(f"Session completed: {self.current_session['track_name']}")
                self.current_session = None
            
            # Check queue for next track
            if self.queue_enabled:
                self.process_queue()
                
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")
    
    def stop_current_session(self):
        """Manually stop current session"""
        if self.session_timer:
            self.session_timer.cancel()
            self.session_timer = None
        
        if self.current_session:
            try:
                if self.spotify:
                    self.spotify.pause_playback()
                
                # Update database
                cursor = self.conn.cursor()
                cursor.execute('''
                    UPDATE sessions SET status = ? WHERE id = ?
                ''', ('stopped', self.current_session['id']))
                self.conn.commit()
                
                logger.info(f"Session stopped: {self.current_session['track_name']}")
                
            except Exception as e:
                logger.error(f"Error stopping session: {e}")
            
            self.current_session = None
    
    def get_status(self):
        """Get current playback status"""
        if not self.current_session:
            return {"status": "idle", "message": "No active session"}
        
        now = datetime.now()
        time_remaining = self.current_session['end_time'] - now
        
        return {
            "status": "playing",
            "track": self.current_session['track_name'],
            "started_at": self.current_session['start_time'].isoformat(),
            "ends_at": self.current_session['end_time'].isoformat(),
            "time_remaining": str(time_remaining).split('.')[0]  # Remove microseconds
        }
    
    def process_queue(self):
        """Process the next item in the queue"""
        try:
            cursor = self.conn.cursor()
            
            # Get next pending track
            cursor.execute('''
                SELECT id, track_uri, track_name, duration_seconds
                FROM queue
                WHERE status = 'pending'
                ORDER BY position ASC
                LIMIT 1
            ''')
            
            next_track = cursor.fetchone()
            if not next_track:
                logger.info("Queue is empty")
                return
            
            queue_id, track_uri, track_name, duration_seconds = next_track
            
            # Mark as playing
            cursor.execute('''
                UPDATE queue SET status = 'playing' WHERE id = ?
            ''', (queue_id,))
            self.conn.commit()
            
            # Start playback
            self.spotify.start_playback(uris=[track_uri])
            
            # Create session
            start_time = datetime.now()
            end_time = start_time + timedelta(seconds=duration_seconds)
            
            cursor.execute('''
                INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, 'playing'))
            
            session_id = cursor.lastrowid
            self.conn.commit()
            
            # Set timer
            self.session_timer = threading.Timer(duration_seconds, self.stop_playback_timer)
            self.session_timer.start()
            
            self.current_session = {
                'id': session_id,
                'track_name': track_name,
                'track_uri': track_uri,
                'start_time': start_time,
                'end_time': end_time,
                'duration_seconds': duration_seconds
            }
            
            # Mark queue item as completed
            cursor.execute('''
                UPDATE queue SET status = 'completed' WHERE id = ?
            ''', (queue_id,))
            self.conn.commit()
            
            logger.info(f"Started from queue: {track_name} for {duration_seconds}s")
            
        except Exception as e:
            logger.error(f"Queue processing error: {e}")

# Initialize server
server = NotVoxServer()

# API Routes
@app.route('/play', methods=['POST'])
def play():
    """Play a track for specified duration"""
    data = request.get_json()
    if not data or 'query' not in data or 'duration' not in data:
        return jsonify({"error": "Missing 'query' or 'duration' in request"}), 400
    
    result, status_code = server.search_and_play(data['query'], data['duration'])
    return jsonify(result), status_code

@app.route('/stop', methods=['DELETE'])
def stop():
    """Stop current playback session"""
    server.stop_current_session()
    return jsonify({"message": "Playback stopped"}), 200

@app.route('/status', methods=['GET'])
def status():
    """Get current playback status"""
    return jsonify(server.get_status()), 200

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "spotify_connected": server.spotify is not None,
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/history', methods=['GET'])
def history():
    """Get playback history with optional filters"""
    try:
        limit = request.args.get('limit', 20, type=int)
        since = request.args.get('since', None)  # ISO timestamp
        
        query = '''
            SELECT id, track_name, track_uri, start_time, end_time, 
                   duration_seconds, status
            FROM sessions
        '''
        params = []
        
        if since:
            query += ' WHERE start_time >= ?'
            params.append(since)
        
        query += ' ORDER BY start_time DESC LIMIT ?'
        params.append(limit)
        
        cursor = server.conn.cursor()
        cursor.execute(query, params)
        
        sessions = []
        for row in cursor.fetchall():
            sessions.append({
                'id': row[0],
                'track_name': row[1],
                'track_uri': row[2],
                'start_time': row[3],
                'end_time': row[4],
                'duration_seconds': row[5],
                'status': row[6]
            })
        
        # Calculate play counts for each track
        cursor.execute('''
            SELECT track_name, COUNT(*) as play_count
            FROM sessions
            GROUP BY track_uri
        ''')
        
        play_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Add play count to each session
        for session in sessions:
            session['play_count'] = play_counts.get(session['track_name'], 1)
        
        return jsonify({
            'sessions': sessions,
            'total': len(sessions)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({"error": "Failed to fetch history"}), 500

@app.route('/extend', methods=['POST'])
def extend_session():
    """Extend or reduce current session time"""
    try:
        if not server.current_session:
            return {"error": "No active session to extend"}, 404
        
        data = request.get_json()
        duration_str = data.get('duration', '0m')
        
        # Parse duration (can be negative like "-10m")
        is_negative = duration_str.startswith('-')
        if is_negative:
            duration_str = duration_str[1:]
        
        additional_seconds = server.parse_duration(duration_str)
        if is_negative:
            additional_seconds = -additional_seconds
        
        # Calculate new end time
        current_end = server.current_session['end_time']
        new_end = current_end + timedelta(seconds=additional_seconds)
        
        # Don't allow extending into the past
        if new_end <= datetime.now():
            return {"error": "Cannot extend session to past time"}, 400
        
        # Update session
        server.current_session['end_time'] = new_end
        new_duration = int((new_end - server.current_session['start_time']).total_seconds())
        server.current_session['duration_seconds'] = new_duration
        
        # Update database
        cursor = server.conn.cursor()
        cursor.execute('''
            UPDATE sessions 
            SET end_time = ?, duration_seconds = ?
            WHERE id = ?
        ''', (new_end.isoformat(), new_duration, server.current_session['id']))
        server.conn.commit()
        
        # Cancel old timer and set new one
        if server.session_timer:
            server.session_timer.cancel()
        
        time_remaining = (new_end - datetime.now()).total_seconds()
        server.session_timer = threading.Timer(time_remaining, server.stop_playback_timer)
        server.session_timer.start()
        
        logger.info(f"Extended session by {additional_seconds}s, new end: {new_end}")
        
        return {
            "message": f"Session {'extended' if additional_seconds > 0 else 'reduced'} by {duration_str}",
            "new_end_time": new_end.isoformat(),
            "total_duration": server.current_session['duration_seconds']
        }, 200
        
    except Exception as e:
        logger.error(f"Extend error: {e}")
        return {"error": str(e)}, 500

@app.route('/search', methods=['GET'])
def search():
    """Search for tracks and return multiple results"""
    try:
        query = request.args.get('q', '')
        limit = request.args.get('limit', 5, type=int)
        
        if not query:
            return {"error": "Missing search query"}, 400
        
        if not server.spotify:
            return {"error": "Spotify not authenticated"}, 500
        
        # Search Spotify
        results = server.spotify.search(q=query, type='track', limit=limit)
        
        tracks = []
        for item in results['tracks']['items']:
            tracks.append({
                'id': item['id'],
                'uri': item['uri'],
                'name': item['name'],
                'artist': item['artists'][0]['name'] if item['artists'] else 'Unknown',
                'album': item['album']['name'],
                'duration_ms': item['duration_ms'],
                'popularity': item['popularity']
            })
        
        return {
            'query': query,
            'tracks': tracks,
            'total': len(tracks)
        }, 200
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"error": str(e)}, 500


@app.route('/play-uri', methods=['POST'])
def play_uri():
    """Play a specific track by URI (for select mode)"""
    try:
        data = request.get_json()
        track_uri = data.get('uri')
        track_name = data.get('name', 'Unknown Track')
        duration_str = data.get('duration', '30m')
        
        if not track_uri:
            return {"error": "Missing track URI"}, 400
        
        # Stop any existing session
        server.stop_current_session()
        
        # Start playback
        server.spotify.start_playback(uris=[track_uri])
        
        # Handle duration and session (same as regular play)
        duration_seconds = server.parse_duration(duration_str)
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        # Save session
        cursor = server.conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, 'playing'))
        
        session_id = cursor.lastrowid
        server.conn.commit()
        
        # Set timer
        server.session_timer = threading.Timer(duration_seconds, server.stop_playback_timer)
        server.session_timer.start()
        
        server.current_session = {
            'id': session_id,
            'track_name': track_name,
            'track_uri': track_uri,
            'start_time': start_time,
            'end_time': end_time,
            'duration_seconds': duration_seconds
        }
        
        return {
            "message": f"Now playing: {track_name}",
            "duration": duration_str,
            "ends_at": end_time.isoformat()
        }, 200
        
    except Exception as e:
        logger.error(f"Play URI error: {e}")
        return {"error": str(e)}, 500

@app.route('/resume', methods=['POST'])
def resume_session():
    """Resume a previous session"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if session_id:
            # Resume specific session
            cursor = server.conn.cursor()
            cursor.execute('''
                SELECT track_uri, track_name, duration_seconds
                FROM sessions
                WHERE id = ?
            ''', (session_id,))
            
            session = cursor.fetchone()
            if not session:
                return {"error": "Session not found"}, 404
            
            track_uri, track_name, original_duration = session
        else:
            # Resume last stopped session
            cursor = server.conn.cursor()
            cursor.execute('''
                SELECT track_uri, track_name, duration_seconds
                FROM sessions
                WHERE status = 'stopped'
                ORDER BY start_time DESC
                LIMIT 1
            ''')
            
            session = cursor.fetchone()
            if not session:
                return {"error": "No stopped sessions to resume"}, 404
            
            track_uri, track_name, original_duration = session
        
        # Use original duration or provided duration
        duration_str = data.get('duration')
        if duration_str:
            duration_seconds = server.parse_duration(duration_str)
        else:
            # Resume with remaining time would be complex, so use original duration
            duration_seconds = original_duration
            # Convert back to string for display
            if duration_seconds < 60:
                duration_str = f"{duration_seconds}s"
            elif duration_seconds < 3600:
                duration_str = f"{duration_seconds // 60}m"
            else:
                duration_str = f"{duration_seconds // 3600}h"
        
        # Stop any existing session
        server.stop_current_session()
        
        # Start playback
        server.spotify.start_playback(uris=[track_uri])
        
        # Create new session
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        cursor.execute('''
            INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, 'playing'))
        
        new_session_id = cursor.lastrowid
        server.conn.commit()
        
        # Set timer
        server.session_timer = threading.Timer(duration_seconds, server.stop_playback_timer)
        server.session_timer.start()
        
        server.current_session = {
            'id': new_session_id,
            'track_name': track_name,
            'track_uri': track_uri,
            'start_time': start_time,
            'end_time': end_time,
            'duration_seconds': duration_seconds
        }
        
        logger.info(f"Resumed: {track_name} for {duration_str}")
        
        return {
            "message": f"Resumed: {track_name}",
            "duration": duration_str,
            "ends_at": end_time.isoformat()
        }, 200
        
    except Exception as e:
        logger.error(f"Resume error: {e}")
        return {"error": str(e)}, 500

# NEW ENDPOINTS FOR SPOTIFY HISTORY INTEGRATION

@app.route('/spotify-history', methods=['GET'])
def spotify_history():
    """Get recently played tracks from Spotify"""
    try:
        if not server.spotify:
            return {"error": "Spotify not authenticated"}, 500
        
        limit = request.args.get('limit', 50, type=int)
        
        # Get recently played from Spotify (max 50)
        recently_played = server.spotify.current_user_recently_played(limit=min(limit, 50))
        
        tracks = []
        track_counts = {}
        
        for item in recently_played['items']:
            track = item['track']
            track_uri = track['uri']
            
            # Count plays
            track_counts[track_uri] = track_counts.get(track_uri, 0) + 1
            
            # Only add unique tracks
            if not any(t['uri'] == track_uri for t in tracks):
                tracks.append({
                    'uri': track_uri,
                    'name': track['name'],
                    'artist': track['artists'][0]['name'] if track['artists'] else 'Unknown',
                    'album': track['album']['name'],
                    'played_at': item['played_at'],
                    'duration_ms': track['duration_ms']
                })
        
        # Add play counts and sort by most played
        for track in tracks:
            track['spotify_play_count'] = track_counts[track['uri']]
        
        tracks.sort(key=lambda x: x['spotify_play_count'], reverse=True)
        
        return {
            'tracks': tracks,
            'total': len(tracks),
            'source': 'spotify'
        }, 200
        
    except Exception as e:
        logger.error(f"Spotify history error: {e}")
        return {"error": str(e)}, 500

@app.route('/lucky', methods=['POST'])
def lucky():
    """Pick a random track based on combined history"""
    try:
        data = request.get_json()
        duration = data.get('duration', '30m')
        
        # Get NotVox history (excluding last 24 hours)
        cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()
        
        cursor = server.conn.cursor()
        cursor.execute('''
            SELECT track_uri, track_name, COUNT(*) as play_count
            FROM sessions
            WHERE start_time < ?
            GROUP BY track_uri
            ORDER BY play_count DESC
            LIMIT 50
        ''', (cutoff_time,))
        
        history_tracks = []
        notvox_uris = set()
        
        for row in cursor.fetchall():
            notvox_uris.add(row[0])
            # Weight by play count
            for _ in range(row[2]):
                history_tracks.append({
                    'uri': row[0],
                    'name': row[1],
                    'play_count': row[2],
                    'source': 'notvox'
                })
        
        # Get Spotify history if available
        if server.spotify:
            try:
                recently_played = server.spotify.current_user_recently_played(limit=50)
                
                spotify_track_counts = {}
                for item in recently_played['items']:
                    track = item['track']
                    uri = track['uri']
                    
                    # Skip if played in NotVox recently
                    if uri in notvox_uris:
                        continue
                    
                    # Skip if played in last 24 hours on Spotify
                    played_at = datetime.fromisoformat(item['played_at'].replace('Z', '+00:00'))
                    if (datetime.now(played_at.tzinfo) - played_at).total_seconds() < 86400:
                        continue
                    
                    if uri not in spotify_track_counts:
                        spotify_track_counts[uri] = {
                            'name': f"{track['name']} by {track['artists'][0]['name']}",
                            'count': 0
                        }
                    spotify_track_counts[uri]['count'] += 1
                
                # Add Spotify tracks to history (weighted by play count)
                for uri, info in spotify_track_counts.items():
                    for _ in range(info['count']):
                        history_tracks.append({
                            'uri': uri,
                            'name': info['name'],
                            'play_count': info['count'],
                            'source': 'spotify'
                        })
                
                logger.info(f"Combined history: {len(history_tracks)} weighted tracks "
                          f"({len(notvox_uris)} NotVox, {len(spotify_track_counts)} Spotify)")
                
            except Exception as e:
                logger.warning(f"Could not fetch Spotify history: {e}")
        
        # Decide whether to use history or discover new
        use_history = len(history_tracks) > 0 and random.random() < 0.7
        
        if use_history:
            # Pick from weighted combined history
            track = random.choice(history_tracks)
            logger.info(f"Lucky pick from {track['source']} history: {track['name']} "
                       f"(played {track['play_count']}x)")
            
            # Start playback
            server.spotify.start_playback(uris=[track['uri']])
            track_name = track['name']
            track_uri = track['uri']
            source = f"history-{track['source']}"
            
        else:
            # Get recommendations based on combined history
            seed_tracks = []
            seed_artists = []
            
            # Use top tracks from both sources as seeds
            if server.spotify:
                # Get unique tracks from combined history
                unique_tracks = {}
                for t in history_tracks:
                    if t['uri'] not in unique_tracks:
                        unique_tracks[t['uri']] = t
                
                # Use top 3 tracks as seeds
                top_tracks = sorted(unique_tracks.values(), 
                                  key=lambda x: x['play_count'], 
                                  reverse=True)[:3]
                
                for track in top_tracks:
                    track_id = track['uri'].split(':')[-1]
                    seed_tracks.append(track_id)
                
                # Get recommendations
                if seed_tracks:
                    recommendations = server.spotify.recommendations(
                        seed_tracks=seed_tracks[:5],  # Max 5 seeds
                        limit=20
                    )
                else:
                    # Fallback to genre-based
                    recommendations = server.spotify.recommendations(
                        seed_genres=['pop'],
                        limit=20
                    )
            else:
                recommendations = server.spotify.recommendations(
                    seed_genres=['pop', 'rock', 'electronic'],
                    limit=20
                )
            
            if recommendations and recommendations['tracks']:
                track = random.choice(recommendations['tracks'])
                track_uri = track['uri']
                track_name = f"{track['name']} by {track['artists'][0]['name']}"
                source = "recommendations"
                
                logger.info(f"Lucky pick from recommendations: {track_name}")
                
                # Start playback
                server.spotify.start_playback(uris=[track_uri])
            else:
                return {"error": "Could not find recommendations"}, 404
        
        # Handle duration and session tracking (same as before)
        duration_seconds = server.parse_duration(duration)
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        # Save session
        cursor = server.conn.cursor()
        cursor.execute('''
            INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, 'playing'))
        
        session_id = cursor.lastrowid
        server.conn.commit()
        
        # Stop any existing session
        server.stop_current_session()
        
        # Set timer
        server.session_timer = threading.Timer(duration_seconds, server.stop_playback_timer)
        server.session_timer.start()
        
        server.current_session = {
            'id': session_id,
            'track_name': track_name,
            'track_uri': track_uri,
            'start_time': start_time,
            'end_time': end_time,
            'duration_seconds': duration_seconds
        }
        
        return {
            "message": f"Lucky pick: {track_name}",
            "duration": duration,
            "ends_at": end_time.isoformat(),
            "source": source
        }, 200
        
    except Exception as e:
        logger.error(f"Lucky pick error: {e}")
        return {"error": str(e)}, 500

# QUEUE ENDPOINTS

@app.route('/queue/add', methods=['POST'])
def add_to_queue():
    """Add a track to the queue"""
    try:
        data = request.get_json()
        query = data.get('query')
        duration_str = data.get('duration', '30m')
        
        if not query:
            return {"error": "Missing query"}, 400
        
        if not server.spotify:
            return {"error": "Spotify not authenticated"}, 500
        
        # Search for track
        results = server.spotify.search(q=query, type='track', limit=1)
        if not results['tracks']['items']:
            return {"error": f"No tracks found for '{query}'"}, 404
        
        track = results['tracks']['items'][0]
        track_uri = track['uri']
        track_name = f"{track['name']} by {track['artists'][0]['name']}"
        
        # Parse duration
        duration_seconds = server.parse_duration(duration_str)
        
        # Get current max position
        cursor = server.conn.cursor()
        cursor.execute('''
            SELECT MAX(position) FROM queue WHERE status = 'pending'
        ''')
        max_pos = cursor.fetchone()[0]
        next_pos = (max_pos or 0) + 1
        
        # Add to queue
        cursor.execute('''
            INSERT INTO queue (track_name, track_uri, duration_seconds, added_at, position)
            VALUES (?, ?, ?, ?, ?)
        ''', (track_name, track_uri, duration_seconds, datetime.now().isoformat(), next_pos))
        
        queue_id = cursor.lastrowid
        server.conn.commit()
        
        # If nothing is playing, start processing queue
        if not server.current_session:
            server.process_queue()
            return {
                "message": f"Added to queue and started playing: {track_name}",
                "queue_id": queue_id,
                "position": 1,
                "duration": duration_str
            }, 200
        else:
            # Get queue position
            cursor.execute('''
                SELECT COUNT(*) FROM queue 
                WHERE status = 'pending' AND position < ?
            ''', (next_pos,))
            ahead_count = cursor.fetchone()[0]
            
            return {
                "message": f"Added to queue: {track_name}",
                "queue_id": queue_id,
                "position": ahead_count + 1,
                "duration": duration_str
            }, 200
        
    except Exception as e:
        logger.error(f"Add to queue error: {e}")
        return {"error": str(e)}, 500

@app.route('/queue', methods=['GET'])
def get_queue():
    """Get current queue"""
    try:
        cursor = server.conn.cursor()
        
        # Get pending tracks
        cursor.execute('''
            SELECT id, track_name, duration_seconds, added_at, position
            FROM queue
            WHERE status = 'pending'
            ORDER BY position ASC
        ''')
        
        queue_items = []
        for row in cursor.fetchall():
            queue_items.append({
                'id': row[0],
                'track_name': row[1],
                'duration_seconds': row[2],
                'added_at': row[3],
                'position': row[4]
            })
        
        # Get currently playing from queue
        currently_playing_queued = None
        if server.current_session:
            cursor.execute('''
                SELECT id FROM queue 
                WHERE track_uri = ? AND status = 'playing'
                LIMIT 1
            ''', (server.current_session.get('track_uri'),))
            
            if cursor.fetchone():
                currently_playing_queued = server.current_session
        
        return {
            'queue': queue_items,
            'total': len(queue_items),
            'currently_playing_from_queue': currently_playing_queued is not None
        }, 200
        
    except Exception as e:
        logger.error(f"Get queue error: {e}")
        return {"error": str(e)}, 500

@app.route('/queue/<int:queue_id>', methods=['DELETE'])
def remove_from_queue(queue_id):
    """Remove a track from the queue"""
    try:
        cursor = server.conn.cursor()
        
        # Check if exists and is pending
        cursor.execute('''
            SELECT position FROM queue 
            WHERE id = ? AND status = 'pending'
        ''', (queue_id,))
        
        result = cursor.fetchone()
        if not result:
            return {"error": "Queue item not found or already played"}, 404
        
        old_position = result[0]
        
        # Remove from queue
        cursor.execute('''
            DELETE FROM queue WHERE id = ?
        ''', (queue_id,))
        
        # Update positions
        cursor.execute('''
            UPDATE queue 
            SET position = position - 1 
            WHERE position > ? AND status = 'pending'
        ''', (old_position,))
        
        server.conn.commit()
        
        return {"message": "Removed from queue"}, 200
        
    except Exception as e:
        logger.error(f"Remove from queue error: {e}")
        return {"error": str(e)}, 500

@app.route('/queue/clear', methods=['DELETE'])
def clear_queue():
    """Clear all pending items from queue"""
    try:
        cursor = server.conn.cursor()
        cursor.execute('''
            DELETE FROM queue WHERE status = 'pending'
        ''')
        
        affected = cursor.rowcount
        server.conn.commit()
        
        return {
            "message": f"Cleared {affected} items from queue"
        }, 200
        
    except Exception as e:
        logger.error(f"Clear queue error: {e}")
        return {"error": str(e)}, 500

@app.route('/skip', methods=['POST'])
def skip():
    """Skip current track and play next in queue"""
    try:
        if not server.current_session:
            return {"error": "Nothing currently playing"}, 404
        
        # Stop current session
        server.stop_current_session()
        
        # Process queue will be called automatically by stop_current_session
        # But let's check if there's something in queue
        cursor = server.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM queue WHERE status = 'pending'
        ''')
        
        queue_count = cursor.fetchone()[0]
        
        if queue_count > 0:
            # Queue processing will happen automatically
            return {"message": "Skipped to next track in queue"}, 200
        else:
            return {"message": "Skipped. Queue is empty"}, 200
        
    except Exception as e:
        logger.error(f"Skip error: {e}")
        return {"error": str(e)}, 500

if __name__ == '__main__':
    # Check for required environment variables
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        exit(1)
    
    app.run(host='0.0.0.0', port=8080, debug=False)