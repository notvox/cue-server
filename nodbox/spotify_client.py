"""
Spotify client wrapper for NotVox
"""

import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging

logger = logging.getLogger(__name__)


class SpotifyClient:
    def __init__(self):
        self.spotify = None
        self.init_spotify()
    
    def init_spotify(self):
        """Initialize Spotify client with auth"""
        try:
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
    
    def is_authenticated(self):
        """Check if Spotify is authenticated"""
        return self.spotify is not None
    
    def refresh_token(self):
        """Refresh Spotify auth token"""
        try:
            if self.spotify and self.spotify.auth_manager:
                token_info = self.spotify.auth_manager.get_cached_token()
                if token_info:
                    # Check if token needs refresh (10 minute buffer)
                    expires_at = token_info.get('expires_at', 0)
                    if time.time() > (expires_at - 600):
                        logger.info("Refreshing Spotify token...")
                        self.spotify.auth_manager.refresh_access_token(token_info['refresh_token'])
                        logger.info("Token refreshed successfully")
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
    
    def search_track(self, query, limit=1):
        """Search for tracks"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.search(q=query, type='track', limit=limit)
        return results['tracks']['items']
    
    def play_track(self, track_uri):
        """Start playback of a track"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        self.spotify.start_playback(uris=[track_uri])
    
    def pause_playback(self):
        """Pause current playback"""
        if not self.spotify:
            return
        
        try:
            self.spotify.pause_playback()
        except Exception as e:
            logger.error(f"Error pausing playback: {e}")
    
    def get_recently_played(self, limit=50):
        """Get recently played tracks from Spotify"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        return self.spotify.current_user_recently_played(limit=min(limit, 50))
    
    def get_recommendations(self, seed_tracks=None, seed_genres=None, limit=20):
        """Get track recommendations"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        kwargs = {'limit': limit}
        if seed_tracks:
            kwargs['seed_tracks'] = seed_tracks[:5]  # Max 5 seeds
        if seed_genres:
            kwargs['seed_genres'] = seed_genres[:5]  # Max 5 seeds
        
        return self.spotify.recommendations(**kwargs)
    
    def get_track_details(self, track_ids):
        """Get details for multiple tracks"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        return self.spotify.tracks(track_ids)
    
    def get_artist_details(self, artist_ids):
        """Get details for multiple artists"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        return self.spotify.artists(artist_ids)