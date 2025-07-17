"""
Queue management for NotVox
"""

import logging

logger = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, database, session_manager=None):
        self.database = database
        self.session_manager = session_manager
        self.enabled = True
    
    def set_session_manager(self, session_manager):
        """Set session manager (to avoid circular imports)"""
        self.session_manager = session_manager
    
    def add_to_queue(self, track_name, track_uri, duration_seconds):
        """Add track to queue"""
        queue_id, position = self.database.add_to_queue(
            track_name, track_uri, duration_seconds
        )
        
        # If nothing is playing, start processing queue
        if self.session_manager and not self.session_manager.has_active_session():
            self.process_next()
            return {
                'queue_id': queue_id,
                'position': 1,
                'started': True
            }
        else:
            # Get actual position in queue
            ahead_count = self.database.get_queue_position(position)
            return {
                'queue_id': queue_id,
                'position': ahead_count + 1,
                'started': False
            }
    
    def process_next(self):
        """Process the next item in the queue"""
        if not self.enabled or not self.session_manager:
            return
        
        try:
            # Get next item
            next_item = self.database.get_next_queue_item()
            if not next_item:
                logger.info("Queue is empty")
                return
            
            queue_id, track_uri, track_name, duration_seconds = next_item
            
            # Mark as playing
            self.database.update_queue_status(queue_id, 'playing')
            
            # Start session
            self.session_manager.start_session(track_name, track_uri, duration_seconds)
            
            # Mark as completed
            self.database.update_queue_status(queue_id, 'completed')
            
            logger.info(f"Started from queue: {track_name}")
            
        except Exception as e:
            logger.error(f"Queue processing error: {e}")
    
    def get_queue(self):
        """Get current queue state"""
        queue_items = self.database.get_queue()
        
        # Check if currently playing from queue
        currently_from_queue = False
        if self.session_manager and self.session_manager.current_session:
            track_uri = self.session_manager.current_session.get('track_uri')
            currently_from_queue = self.database.is_playing_from_queue(track_uri)
        
        return {
            'queue': queue_items,
            'total': len(queue_items),
            'currently_playing_from_queue': currently_from_queue
        }
    
    def remove_from_queue(self, queue_id):
        """Remove item from queue"""
        return self.database.remove_from_queue(queue_id)
    
    def clear_queue(self):
        """Clear all pending items"""
        count = self.database.clear_queue()
        return {'cleared': count}
    
    def skip_current(self):
        """Skip current track and play next in queue"""
        if not self.session_manager:
            raise Exception("Session manager not available")
        
        if not self.session_manager.has_active_session():
            raise Exception("Nothing currently playing")
        
        # Stop current session
        self.session_manager.stop_current_session()
        
        # Check if there's something in queue
        queue_items = self.database.get_queue()
        
        if queue_items:
            # Process next will be called automatically
            return {'queue_remaining': len(queue_items)}
        else:
            return {'queue_remaining': 0}