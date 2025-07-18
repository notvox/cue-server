#!/usr/bin/env python3
"""
NotVox Server - Networked Spotify Control System
Main server file that coordinates all components
"""

import os
import sys
import threading
import schedule
import time
import random
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask, request, jsonify
import logging

# Import our modules
from database import Database
from spotify_client import SpotifyClient
from session_manager import SessionManager
from queue_manager import QueueManager
from modes import ModeManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize components
db = Database()
spotify = SpotifyClient()
session_mgr = SessionManager(spotify, db)
queue_mgr = QueueManager(db)
mode_mgr = ModeManager(spotify, db)

# Set circular references
session_mgr.set_queue_manager(queue_mgr)
queue_mgr.set_session_manager(session_mgr)


def start_auth_refresh():
    """Start background thread for token refresh"""
    def refresh_worker():
        schedule.every(50).minutes.do(spotify.refresh_token)
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    refresh_thread = threading.Thread(target=refresh_worker, daemon=True)
    refresh_thread.start()
    logger.info("Auth refresh thread started")


# API Routes
@app.route('/play', methods=['POST'])
def play():
    """Play a track for specified duration"""
    data = request.get_json()
    if not data or 'query' not in data or 'duration' not in data:
        return jsonify({"error": "Missing 'query' or 'duration' in request"}), 400
    
    if not spotify.is_authenticated():
        return jsonify({"error": "Spotify not authenticated"}), 500
    
    try:
        # Search for track
        tracks = spotify.search_track(data['query'], limit=1)
        if not tracks:
            return jsonify({"error": f"No tracks found for '{data['query']}'"}), 404
        
        track = tracks[0]
        track_uri = track['uri']
        track_name = f"{track['name']} by {track['artists'][0]['name']}"
        
        # Parse duration and start session
        duration_seconds = session_mgr.parse_duration(data['duration'])
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        return jsonify({
            "message": f"Now playing: {track_name}",
            "duration": data['duration'],
            "ends_at": result['ends_at']
        }), 200
        
    except Exception as e:
        logger.error(f"Playback error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/stop', methods=['DELETE'])
def stop():
    """Stop current playback session"""
    session_mgr.stop_current_session()
    return jsonify({"message": "Playback stopped"}), 200


@app.route('/status', methods=['GET'])
def status():
    """Get current playback status"""
    return jsonify(session_mgr.get_status()), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "spotify_connected": spotify.is_authenticated(),
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/history', methods=['GET'])
def history():
    """Get playback history with optional filters"""
    try:
        limit = request.args.get('limit', 20, type=int)
        since = request.args.get('since', None)
        
        sessions = db.get_history(limit=limit, since=since)
        
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
        data = request.get_json()
        duration_str = data.get('duration', '0m')
        
        # Parse duration (can be negative like "-10m")
        is_negative = duration_str.startswith('-')
        if is_negative:
            duration_str = duration_str[1:]
        
        additional_seconds = session_mgr.parse_duration(duration_str)
        if is_negative:
            additional_seconds = -additional_seconds
        
        result = session_mgr.extend_session(additional_seconds)
        
        return jsonify({
            "message": f"Session {'extended' if additional_seconds > 0 else 'reduced'} by {duration_str}",
            "new_end_time": result['new_end_time'],
            "total_duration": result['total_duration']
        }), 200
        
    except Exception as e:
        logger.error(f"Extend error: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/search', methods=['GET'])
def search():
    """Search for tracks and return multiple results"""
    try:
        query = request.args.get('q', '')
        limit = request.args.get('limit', 5, type=int)
        
        if not query:
            return jsonify({"error": "Missing search query"}), 400
        
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        # Search Spotify
        results = spotify.search_track(query, limit=limit)
        
        tracks = []
        for item in results:
            tracks.append({
                'id': item['id'],
                'uri': item['uri'],
                'name': item['name'],
                'artist': item['artists'][0]['name'] if item['artists'] else 'Unknown',
                'album': item['album']['name'],
                'duration_ms': item['duration_ms'],
                'popularity': item['popularity']
            })
        
        return jsonify({
            'query': query,
            'tracks': tracks,
            'total': len(tracks)
        }), 200
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/play-uri', methods=['POST'])
def play_uri():
    """Play a specific track by URI (for select mode)"""
    try:
        data = request.get_json()
        track_uri = data.get('uri')
        track_name = data.get('name', 'Unknown Track')
        duration_str = data.get('duration', '30m')
        
        if not track_uri:
            return jsonify({"error": "Missing track URI"}), 400
        
        duration_seconds = session_mgr.parse_duration(duration_str)
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        return jsonify({
            "message": f"Now playing: {track_name}",
            "duration": duration_str,
            "ends_at": result['ends_at']
        }), 200
        
    except Exception as e:
        logger.error(f"Play URI error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/resume', methods=['POST'])
def resume_session():
    """Resume a previous session"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if session_id:
            session = db.get_session_by_id(session_id)
        else:
            session = db.get_last_stopped_session()
        
        if not session:
            return jsonify({"error": "No session to resume"}), 404
        
        track_uri, track_name, original_duration = session
        
        # Use original duration or provided duration
        duration_str = data.get('duration')
        if duration_str:
            duration_seconds = session_mgr.parse_duration(duration_str)
        else:
            duration_seconds = original_duration
            duration_str = session_mgr.format_duration(duration_seconds)
        
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        return jsonify({
            "message": f"Resumed: {track_name}",
            "duration": duration_str,
            "ends_at": result['ends_at']
        }), 200
        
    except Exception as e:
        logger.error(f"Resume error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/spotify-history', methods=['GET'])
def spotify_history():
    """Get recently played tracks from Spotify"""
    try:
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        limit = request.args.get('limit', 50, type=int)
        
        # Get recently played
        recently_played = spotify.get_recently_played(limit=limit)
        
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
        
        return jsonify({
            'tracks': tracks,
            'total': len(tracks),
            'source': 'spotify'
        }), 200
        
    except Exception as e:
        logger.error(f"Spotify history error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/lucky', methods=['POST'])
def lucky():
    """Pick a random track based on combined history"""
    try:
        data = request.get_json()
        duration = data.get('duration', '30m')
        
        # Check if we're in a mode
        current_mode = mode_mgr.get_current_mode()
        
        # Get NotVox history (excluding last 24 hours)
        cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()
        history_data = db.get_track_history(cutoff_time)
        
        history_tracks = []
        notvox_uris = set()
        
        for row in history_data:
            uri, name, play_count = row
            notvox_uris.add(uri)
            # Weight by play count
            for _ in range(play_count):
                history_tracks.append({
                    'uri': uri,
                    'name': name,
                    'play_count': play_count,
                    'source': 'notvox'
                })
        
        # Get Spotify history if available
        if spotify.is_authenticated():
            try:
                recently_played = spotify.get_recently_played()
                
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
                
                logger.info(f"Combined history: {len(history_tracks)} weighted tracks")
                
            except Exception as e:
                logger.warning(f"Could not fetch Spotify history: {e}")
        
        # Decide whether to use history or discover new
        use_history = len(history_tracks) > 0 and random.random() < 0.7
        
        if use_history and history_tracks:
            # Pick from weighted combined history
            track = random.choice(history_tracks)
            logger.info(f"Lucky pick from {track['source']} history: {track['name']}")
            
            track_name = track['name']
            track_uri = track['uri']
            source = f"history-{track['source']}"
            
        else:
            # Get recommendations
            seed_tracks = []
            if history_tracks:
                # Get unique tracks
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
            
            # Get mode-specific parameters if in a mode
            if current_mode:
                rec_params = mode_mgr.get_recommendations_params(current_mode, seed_tracks[:3])
            else:
                rec_params = {'limit': 20}
                if seed_tracks:
                    rec_params['seed_tracks'] = seed_tracks[:3]
                else:
                    rec_params['seed_genres'] = ['pop']
            
            # Get recommendations with error handling
            try:
                recommendations = spotify.get_recommendations(**rec_params)
                
                if recommendations and recommendations['tracks']:
                    track = random.choice(recommendations['tracks'])
                    track_uri = track['uri']
                    track_name = f"{track['name']} by {track['artists'][0]['name']}"
                    source = f"recommendations{'-' + current_mode if current_mode else ''}"
                    
                    logger.info(f"Lucky pick from recommendations: {track_name}")
                else:
                    raise Exception("No recommendations returned")
                    
            except Exception as e:
                logger.warning(f"Recommendation API failed: {e}")
                # Fallback to history if available
                if history_tracks:
                    track = random.choice(history_tracks)
                    track_name = track['name']
                    track_uri = track['uri']
                    source = f"history-{track['source']}-fallback"
                    logger.info(f"Lucky pick from {track['source']} history (fallback): {track['name']}")
                else:
                    # Last resort: just search for a popular song
                    try:
                        results = spotify.search_track("today's top hits", limit=50)
                        if results:
                            track = random.choice(results)
                            track_uri = track['uri']
                            track_name = f"{track['name']} by {track['artists'][0]['name']}"
                            source = "search-fallback"
                            logger.info(f"Lucky pick from search fallback: {track_name}")
                        else:
                            return jsonify({"error": "Could not find any tracks for lucky pick"}), 404
                    except Exception as search_error:
                        logger.error(f"Search fallback also failed: {search_error}")
                        return jsonify({"error": "Could not find any tracks for lucky pick"}), 404
        
        # Start playback
        duration_seconds = session_mgr.parse_duration(duration)
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        response = {
            "message": f"Lucky pick: {track_name}",
            "duration": duration,
            "ends_at": result['ends_at'],
            "source": source
        }
        
        if current_mode:
            response["mode"] = current_mode
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Lucky pick error: {e}")
        return jsonify({"error": str(e)}), 500


# Queue endpoints
@app.route('/queue/add', methods=['POST'])
def add_to_queue():
    """Add a track to the queue"""
    try:
        data = request.get_json()
        query = data.get('query')
        duration_str = data.get('duration', '30m')
        
        if not query:
            return jsonify({"error": "Missing query"}), 400
        
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        # Search for track
        tracks = spotify.search_track(query, limit=1)
        if not tracks:
            return jsonify({"error": f"No tracks found for '{query}'"}), 404
        
        track = tracks[0]
        track_uri = track['uri']
        track_name = f"{track['name']} by {track['artists'][0]['name']}"
        
        # Parse duration
        duration_seconds = session_mgr.parse_duration(duration_str)
        
        # Add to queue
        result = queue_mgr.add_to_queue(track_name, track_uri, duration_seconds)
        
        if result['started']:
            message = f"Added to queue and started playing: {track_name}"
        else:
            message = f"Added to queue: {track_name}"
        
        return jsonify({
            "message": message,
            "queue_id": result['queue_id'],
            "position": result['position'],
            "duration": duration_str
        }), 200
        
    except Exception as e:
        logger.error(f"Add to queue error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/queue', methods=['GET'])
def get_queue():
    """Get current queue"""
    try:
        result = queue_mgr.get_queue()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Get queue error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/queue/<int:queue_id>', methods=['DELETE'])
def remove_from_queue(queue_id):
    """Remove a track from the queue"""
    try:
        if queue_mgr.remove_from_queue(queue_id):
            return jsonify({"message": "Removed from queue"}), 200
        else:
            return jsonify({"error": "Queue item not found or already played"}), 404
    except Exception as e:
        logger.error(f"Remove from queue error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/queue/clear', methods=['DELETE'])
def clear_queue():
    """Clear all pending items from queue"""
    try:
        result = queue_mgr.clear_queue()
        return jsonify({
            "message": f"Cleared {result['cleared']} items from queue"
        }), 200
    except Exception as e:
        logger.error(f"Clear queue error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/skip', methods=['POST'])
def skip():
    """Skip current track and play next in queue"""
    try:
        result = queue_mgr.skip_current()
        
        if result['queue_remaining'] > 0:
            return jsonify({"message": "Skipped to next track in queue"}), 200
        else:
            return jsonify({"message": "Skipped. Queue is empty"}), 200
            
    except Exception as e:
        logger.error(f"Skip error: {e}")
        return jsonify({"error": str(e)}), 400


# MODE ENDPOINTS
@app.route('/modes', methods=['GET'])
def get_modes():
    """Get all available modes"""
    try:
        modes = mode_mgr.list_modes()
        return jsonify({"modes": modes}), 200
    except Exception as e:
        logger.error(f"Error getting modes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/<mode_name>', methods=['GET'])
def get_mode(mode_name):
    """Get specific mode configuration"""
    try:
        config = mode_mgr.get_mode(mode_name)
        if not config:
            return jsonify({"error": f"Mode '{mode_name}' not found"}), 404
        
        return jsonify({
            "mode": mode_name,
            "config": config
        }), 200
    except Exception as e:
        logger.error(f"Error getting mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/current', methods=['GET'])
def get_current_mode():
    """Get current active mode"""
    try:
        current = mode_mgr.get_current_mode()
        if current:
            config = mode_mgr.get_mode(current)
            return jsonify({
                "mode": current,
                "config": config
            }), 200
        else:
            return jsonify({"mode": None}), 200
    except Exception as e:
        logger.error(f"Error getting current mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/start', methods=['POST'])
def start_mode():
    """Start a specific mode"""
    try:
        data = request.get_json()
        mode_name = data.get('mode')
        
        if not mode_name:
            return jsonify({"error": "Missing mode parameter"}), 400
        
        # Get mode configuration
        mode_config = mode_mgr.get_mode(mode_name)
        if not mode_config:
            return jsonify({"error": f"Unknown mode: {mode_name}"}), 404
        
        # Set current mode
        mode_mgr.set_current_mode(mode_name)
        
        # Override duration/volume if provided
        duration = data.get('duration', mode_config.get('duration', '1h'))
        volume = data.get('volume', mode_config.get('volume', 50))
        
        # Get search query based on mode
        search_query = mode_mgr.get_search_query(mode_name)
        
        # Search for appropriate tracks
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        # Try mode-specific search first
        tracks = spotify.search_track(search_query, limit=50)
        
        if not tracks:
            # Fallback to genre search
            genres = mode_config.get('genres', [])
            if genres:
                for genre in genres:
                    tracks = spotify.search_track(f"genre:{genre}", limit=50)
                    if tracks:
                        break
        
        if not tracks:
            return jsonify({"error": f"No tracks found for {mode_name} mode"}), 404
        
        # Pick a track (could be random or based on mode preferences)
        track = random.choice(tracks)
        track_uri = track['uri']
        track_name = f"{track['name']} by {track['artists'][0]['name']}"
        
        # Start playback
        duration_seconds = session_mgr.parse_duration(duration)
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        # TODO: Set volume when that feature is implemented
        # spotify.set_volume(volume)
        
        return jsonify({
            "message": f"Started {mode_name} mode",
            "mode": mode_name,
            "track": track_name,
            "duration": duration,
            "volume": volume,
            "ends_at": result['ends_at']
        }), 200
        
    except Exception as e:
        logger.error(f"Error starting mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/stop', methods=['POST'])
def stop_mode():
    """Stop current mode and playback"""
    try:
        # Clear current mode
        mode_mgr.set_current_mode(None)
        
        # Stop playback
        session_mgr.stop_current_session()
        
        return jsonify({"message": "Mode stopped"}), 200
    except Exception as e:
        logger.error(f"Error stopping mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/create', methods=['POST'])
def create_mode():
    """Create a new custom mode"""
    try:
        data = request.get_json()
        name = data.get('name')
        config = data.get('config', {})
        
        if not name:
            return jsonify({"error": "Missing mode name"}), 400
        
        mode_mgr.create_mode(name, config)
        
        return jsonify({
            "message": f"Created mode '{name}'",
            "mode": name,
            "config": config
        }), 201
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/<mode_name>', methods=['PUT'])
def update_mode(mode_name):
    """Update an existing mode"""
    try:
        data = request.get_json()
        updates = data.get('updates', {})
        
        updated_config = mode_mgr.update_mode(mode_name, updates)
        
        return jsonify({
            "message": f"Updated mode '{mode_name}'",
            "mode": mode_name,
            "config": updated_config
        }), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error updating mode: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/mode/<mode_name>', methods=['DELETE'])
def delete_mode(mode_name):
    """Delete a custom mode"""
    try:
        mode_mgr.delete_mode(mode_name)
        
        return jsonify({
            "message": f"Deleted mode '{mode_name}'"
        }), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error deleting mode: {e}")
        return jsonify({"error": str(e)}), 500
# VOLUME & DEVICE ENDPOINTS
@app.route('/volume', methods=['GET'])
def get_volume():
    """Get current volume"""
    try:
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        volume = spotify.get_volume()
        if volume is None:
            return jsonify({"error": "No active playback device"}), 404
        
        return jsonify({"volume": volume}), 200
        
    except Exception as e:
        logger.error(f"Error getting volume: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/volume', methods=['POST'])
def set_volume():
    """Set volume"""
    try:
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        data = request.get_json()
        volume_str = str(data.get('volume', '50'))
        
        # Handle relative volume changes
        if volume_str.startswith('+') or volume_str.startswith('-'):
            delta = int(volume_str)
            new_volume = spotify.adjust_volume(delta)
        else:
            new_volume = spotify.set_volume(int(volume_str))
        
        # If we're in a mode, update the mode's volume preference
        current_mode = mode_mgr.get_current_mode()
        if current_mode:
            mode_mgr.update_mode(current_mode, {'volume': new_volume})
        
        return jsonify({
            "volume": new_volume,
            "message": f"Volume set to {new_volume}%"
        }), 200
        
    except Exception as e:
        logger.error(f"Error setting volume: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/devices', methods=['GET'])
def get_devices():
    """Get available Spotify devices"""
    try:
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        devices = spotify.get_devices()
        active_device = spotify.get_active_device()
        
        return jsonify({
            "devices": devices,
            "active_device": active_device,
            "total": len(devices)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting devices: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/device/transfer', methods=['POST'])
def transfer_device():
    """Transfer playback to a specific device"""
    try:
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        data = request.get_json()
        device_identifier = data.get('device')
        
        if not device_identifier:
            return jsonify({"error": "Missing device parameter"}), 400
        
        # Try to find device by ID or name
        device = None
        devices = spotify.get_devices()
        
        # First try as device ID
        for d in devices:
            if d['id'] == device_identifier:
                device = d
                break
        
        # If not found, try by name
        if not device:
            device = spotify.find_device_by_name(device_identifier)
        
        if not device:
            return jsonify({"error": f"Device '{device_identifier}' not found"}), 404
        
        # Transfer playback
        spotify.transfer_playback(device['id'])
        
        return jsonify({
            "message": f"Playback transferred to {device['name']}",
            "device": device
        }), 200
        
    except Exception as e:
        logger.error(f"Error transferring device: {e}")
        return jsonify({"error": str(e)}), 500


# Update the mode start endpoint to set volume
@app.route('/mode/start', methods=['POST'])
def start_mode_with_volume():
    """Enhanced mode start that sets volume"""
    try:
        data = request.get_json()
        mode_name = data.get('mode')
        
        if not mode_name:
            return jsonify({"error": "Missing mode parameter"}), 400
        
        # Get mode configuration
        mode_config = mode_mgr.get_mode(mode_name)
        if not mode_config:
            return jsonify({"error": f"Unknown mode: {mode_name}"}), 404
        
        # Set current mode
        mode_mgr.set_current_mode(mode_name)
        
        # Override duration/volume if provided
        duration = data.get('duration', mode_config.get('duration', '1h'))
        volume = data.get('volume', mode_config.get('volume', 50))
        
        # Get time-adjusted volume
        adjusted_volume = mode_mgr.get_volume_adjustment(mode_name)
        if adjusted_volume:
            volume = adjusted_volume
        
        # Set volume before playing
        try:
            spotify.set_volume(volume)
        except Exception as e:
            logger.warning(f"Could not set volume: {e}")
        
        # Get search query based on mode
        search_query = mode_mgr.get_search_query(mode_name)
        
        # Search for appropriate tracks
        if not spotify.is_authenticated():
            return jsonify({"error": "Spotify not authenticated"}), 500
        
        # Try mode-specific search first
        tracks = spotify.search_track(search_query, limit=50)
        
        if not tracks:
            # Fallback to genre search
            genres = mode_config.get('genres', [])
            if genres:
                for genre in genres:
                    tracks = spotify.search_track(f"genre:{genre}", limit=50)
                    if tracks:
                        break
        
        if not tracks:
            return jsonify({"error": f"No tracks found for {mode_name} mode"}), 404
        
        # Pick a track (could be random or based on mode preferences)
        track = random.choice(tracks)
        track_uri = track['uri']
        track_name = f"{track['name']} by {track['artists'][0]['name']}"
        
        # Start playback
        duration_seconds = session_mgr.parse_duration(duration)
        result = session_mgr.start_session(track_name, track_uri, duration_seconds)
        
        return jsonify({
            "message": f"Started {mode_name} mode",
            "mode": mode_name,
            "track": track_name,
            "duration": duration,
            "volume": volume,
            "ends_at": result['ends_at']
        }), 200
        
    except Exception as e:
        logger.error(f"Error starting mode: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Check for required environment variables
    required_vars = ['SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        sys.exit(1)
    
    # Start auth refresh thread
    start_auth_refresh()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=8080, debug=False)