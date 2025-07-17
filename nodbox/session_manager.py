"""
Session and timer management for NotVox
"""

import threading
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, spotify_client, database, queue_manager=None):
        self.spotify_client = spotify_client
        self.database = database
        self.queue_manager = queue_manager
        self.current_session = None
        self.session_timer = None
    
    def set_queue_manager(self, queue_manager):
        """Set queue manager (to avoid circular imports)"""
        self.queue_manager = queue_manager
    
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
    
    def format_duration(self, seconds):
        """Format seconds back to duration string"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        else:
            return f"{seconds // 3600}h"
    
    def start_session(self, track_name, track_uri, duration_seconds):
        """Start a new playback session"""
        # Stop any existing session
        self.stop_current_session()
        
        # Start playback
        self.spotify_client.play_track(track_uri)
        
        # Calculate times
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)
        
        # Save to database
        session_id = self.database.create_session(
            track_name, track_uri, start_time, end_time, 
            duration_seconds, 'playing'
        )
        
        # Set timer
        self.session_timer = threading.Timer(duration_seconds, self._on_timer_complete)
        self.session_timer.start()
        
        # Update current session
        self.current_session = {
            'id': session_id,
            'track_name': track_name,
            'track_uri': track_uri,
            'start_time': start_time,
            'end_time': end_time,
            'duration_seconds': duration_seconds
        }
        
        logger.info(f"Started session: {track_name} for {duration_seconds}s")
        
        return {
            'session_id': session_id,
            'ends_at': end_time.isoformat()
        }
    
    def _on_timer_complete(self):
        """Called when session timer completes"""
        try:
            # Pause playback
            self.spotify_client.pause_playback()
            
            if self.current_session:
                # Update database
                self.database.update_session_status(
                    self.current_session['id'], 'completed'
                )
                
                logger.info(f"Session completed: {self.current_session['track_name']}")
                self.current_session = None
            
            # Process queue if available
            if self.queue_manager:
                self.queue_manager.process_next()
                
        except Exception as e:
            logger.error(f"Error in timer completion: {e}")
    
    def stop_current_session(self):
        """Manually stop current session"""
        if self.session_timer:
            self.session_timer.cancel()
            self.session_timer = None
        
        if self.current_session:
            try:
                # Pause playback
                self.spotify_client.pause_playback()
                
                # Update database
                self.database.update_session_status(
                    self.current_session['id'], 'stopped'
                )
                
                logger.info(f"Session stopped: {self.current_session['track_name']}")
                
            except Exception as e:
                logger.error(f"Error stopping session: {e}")
            
            self.current_session = None
    
    def extend_session(self, additional_seconds):
        """Extend or reduce current session"""
        if not self.current_session:
            raise Exception("No active session to extend")
        
        # Calculate new end time
        current_end = self.current_session['end_time']
        new_end = current_end + timedelta(seconds=additional_seconds)
        
        # Don't allow extending into the past
        if new_end <= datetime.now():
            raise Exception("Cannot extend session to past time")
        
        # Update session
        self.current_session['end_time'] = new_end
        new_duration = int((new_end - self.current_session['start_time']).total_seconds())
        self.current_session['duration_seconds'] = new_duration
        
        # Update database
        self.database.update_session_time(
            self.current_session['id'], new_end, new_duration
        )
        
        # Cancel old timer and set new one
        if self.session_timer:
            self.session_timer.cancel()
        
        time_remaining = (new_end - datetime.now()).total_seconds()
        self.session_timer = threading.Timer(time_remaining, self._on_timer_complete)
        self.session_timer.start()
        
        logger.info(f"Extended session by {additional_seconds}s, new end: {new_end}")
        
        return {
            'new_end_time': new_end.isoformat(),
            'total_duration': new_duration
        }
    
    def get_status(self):
        """Get current session status"""
        if not self.current_session:
            return {
                "status": "idle",
                "message": "No active session"
            }
        
        now = datetime.now()
        time_remaining = self.current_session['end_time'] - now
        
        return {
            "status": "playing",
            "track": self.current_session['track_name'],
            "started_at": self.current_session['start_time'].isoformat(),
            "ends_at": self.current_session['end_time'].isoformat(),
            "time_remaining": str(time_remaining).split('.')[0]  # Remove microseconds
        }
    
    def has_active_session(self):
        """Check if there's an active session"""
        return self.current_session is not None