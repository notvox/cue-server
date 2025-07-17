"""
Database operations for NotVox
"""

import sqlite3
from datetime import datetime
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path='notvox.db'):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_cursor(self):
        """Context manager for database operations"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize SQLite database tables"""
        with self.get_cursor() as cursor:
            # Sessions table
            cursor.execute('''
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
            cursor.execute('''
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
    
    # Session operations
    def create_session(self, track_name, track_uri, start_time, end_time, duration_seconds, status='playing'):
        """Create a new session"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO sessions (track_name, track_uri, start_time, end_time, duration_seconds, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (track_name, track_uri, start_time.isoformat(), end_time.isoformat(), duration_seconds, status))
            return cursor.lastrowid
    
    def update_session_status(self, session_id, status):
        """Update session status"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                UPDATE sessions SET status = ? WHERE id = ?
            ''', (status, session_id))
    
    def update_session_time(self, session_id, end_time, duration_seconds):
        """Update session end time and duration"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                UPDATE sessions 
                SET end_time = ?, duration_seconds = ?
                WHERE id = ?
            ''', (end_time.isoformat(), duration_seconds, session_id))
    
    def get_history(self, limit=20, since=None):
        """Get playback history"""
        with self.get_cursor() as cursor:
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
            
            # Get play counts
            cursor.execute('''
                SELECT track_name, COUNT(*) as play_count
                FROM sessions
                GROUP BY track_uri
            ''')
            
            play_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Add play count to each session
            for session in sessions:
                session['play_count'] = play_counts.get(session['track_name'], 1)
            
            return sessions
    
    def get_track_history(self, cutoff_time, limit=50):
        """Get track play counts for lucky mode"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT track_uri, track_name, COUNT(*) as play_count
                FROM sessions
                WHERE start_time < ?
                GROUP BY track_uri
                ORDER BY play_count DESC
                LIMIT ?
            ''', (cutoff_time, limit))
            
            return cursor.fetchall()
    
    def get_last_stopped_session(self):
        """Get the most recent stopped session"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT track_uri, track_name, duration_seconds
                FROM sessions
                WHERE status = 'stopped'
                ORDER BY start_time DESC
                LIMIT 1
            ''')
            return cursor.fetchone()
    
    def get_session_by_id(self, session_id):
        """Get session by ID"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT track_uri, track_name, duration_seconds
                FROM sessions
                WHERE id = ?
            ''', (session_id,))
            return cursor.fetchone()
    
    # Queue operations
    def add_to_queue(self, track_name, track_uri, duration_seconds):
        """Add track to queue"""
        with self.get_cursor() as cursor:
            # Get next position
            cursor.execute('''
                SELECT MAX(position) FROM queue WHERE status = 'pending'
            ''')
            max_pos = cursor.fetchone()[0]
            next_pos = (max_pos or 0) + 1
            
            # Insert into queue
            cursor.execute('''
                INSERT INTO queue (track_name, track_uri, duration_seconds, added_at, position)
                VALUES (?, ?, ?, ?, ?)
            ''', (track_name, track_uri, duration_seconds, datetime.now().isoformat(), next_pos))
            
            return cursor.lastrowid, next_pos
    
    def get_queue(self):
        """Get pending queue items"""
        with self.get_cursor() as cursor:
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
            
            return queue_items
    
    def get_next_queue_item(self):
        """Get next item from queue"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT id, track_uri, track_name, duration_seconds
                FROM queue
                WHERE status = 'pending'
                ORDER BY position ASC
                LIMIT 1
            ''')
            return cursor.fetchone()
    
    def update_queue_status(self, queue_id, status):
        """Update queue item status"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                UPDATE queue SET status = ? WHERE id = ?
            ''', (status, queue_id))
    
    def remove_from_queue(self, queue_id):
        """Remove item from queue and reorder"""
        with self.get_cursor() as cursor:
            # Get position
            cursor.execute('''
                SELECT position FROM queue 
                WHERE id = ? AND status = 'pending'
            ''', (queue_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
            
            old_position = result[0]
            
            # Remove from queue
            cursor.execute('DELETE FROM queue WHERE id = ?', (queue_id,))
            
            # Update positions
            cursor.execute('''
                UPDATE queue 
                SET position = position - 1 
                WHERE position > ? AND status = 'pending'
            ''', (old_position,))
            
            return True
    
    def clear_queue(self):
        """Clear all pending queue items"""
        with self.get_cursor() as cursor:
            cursor.execute('DELETE FROM queue WHERE status = "pending"')
            return cursor.rowcount
    
    def get_queue_position(self, position):
        """Get number of items ahead in queue"""
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT COUNT(*) FROM queue 
                WHERE status = 'pending' AND position < ?
            ''', (position,))
            return cursor.fetchone()[0]
    
    def is_playing_from_queue(self, track_uri):
        """Check if current track is from queue"""
        if not track_uri:
            return False
            
        with self.get_cursor() as cursor:
            cursor.execute('''
                SELECT id FROM queue 
                WHERE track_uri = ? AND status = 'playing'
                LIMIT 1
            ''', (track_uri,))
            return cursor.fetchone() is not None