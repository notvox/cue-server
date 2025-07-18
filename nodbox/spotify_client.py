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
    
    def get_recommendations(self, seed_tracks=None, seed_genres=None, limit=20, **kwargs):
        """Get track recommendations"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        params = {'limit': limit}
        if seed_tracks:
            params['seed_tracks'] = seed_tracks[:5]  # Max 5 seeds
        if seed_genres:
            params['seed_genres'] = seed_genres[:5]  # Max 5 seeds
        
        # Add any additional parameters (for mode-specific recommendations)
        params.update(kwargs)
        
        return self.spotify.recommendations(**params)
    
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
    
    # VOLUME CONTROL METHODS
    def set_volume(self, volume_percent, device_id=None):
        """Set playback volume (0-100)"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        # Ensure volume is within bounds
        volume_percent = max(0, min(100, int(volume_percent)))
        
        try:
            self.spotify.volume(volume_percent, device_id=device_id)
            logger.info(f"Volume set to {volume_percent}%")
            return volume_percent
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            raise
    
    def get_volume(self):
        """Get current volume from active device"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        try:
            playback = self.spotify.current_playback()
            if playback and playback.get('device'):
                return playback['device'].get('volume_percent', 0)
            else:
                # No active playback
                return None
        except Exception as e:
            logger.error(f"Error getting volume: {e}")
            return None
    
    def adjust_volume(self, delta):
        """Adjust volume by a relative amount (+/- delta)"""
        current = self.get_volume()
        if current is None:
            raise Exception("No active playback device")
        
        new_volume = current + delta
        return self.set_volume(new_volume)
    
    # DEVICE CONTROL METHODS
    def get_devices(self):
        """Get available Spotify devices"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        try:
            devices_data = self.spotify.devices()
            devices = []
            
            for device in devices_data.get('devices', []):
                devices.append({
                    'id': device['id'],
                    'name': device['name'],
                    'type': device['type'],
                    'is_active': device['is_active'],
                    'volume': device.get('volume_percent', 0),
                    'is_restricted': device.get('is_restricted', False)
                })
            
            return devices
        except Exception as e:
            logger.error(f"Error getting devices: {e}")
            raise
    
    def get_active_device(self):
        """Get the currently active device"""
        devices = self.get_devices()
        for device in devices:
            if device['is_active']:
                return device
        return None
    
    def transfer_playback(self, device_id, force_play=True):
        """Transfer playback to a specific device"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        try:
            self.spotify.transfer_playback(device_id, force_play=force_play)
            logger.info(f"Playback transferred to device {device_id}")
        except Exception as e:
            logger.error(f"Error transferring playback: {e}")
            raise
    
    def find_device_by_name(self, device_name):
        """Find a device by name (case-insensitive partial match)"""
        devices = self.get_devices()
        device_name_lower = device_name.lower()
        
        # First try exact match
        for device in devices:
            if device['name'].lower() == device_name_lower:
                return device
        
        # Then try partial match
        for device in devices:
            if device_name_lower in device['name'].lower():
                return device
        
        return None
    
    # PLAYLIST, ALBUM, ARTIST METHODS
    def search_playlist(self, query, limit=10):
        """Search for playlists"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.search(q=query, type='playlist', limit=limit)
        return results['playlists']['items']

    def search_album(self, query, limit=10):
        """Search for albums"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.search(q=query, type='album', limit=limit)
        return results['albums']['items']

    def search_artist(self, query, limit=10):
        """Search for artists"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.search(q=query, type='artist', limit=limit)
        return results['artists']['items']

    def get_playlist_tracks(self, playlist_id, limit=100):
        """Get all tracks from a playlist"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        tracks = []
        offset = 0
        
        while True:
            results = self.spotify.playlist_tracks(
                playlist_id, 
                limit=min(limit - len(tracks), 100),
                offset=offset
            )
            
            for item in results['items']:
                if item['track'] and item['track']['id']:  # Skip local files
                    tracks.append(item['track'])
            
            if not results['next'] or len(tracks) >= limit:
                break
                
            offset += 100
        
        return tracks

    def get_album_tracks(self, album_id):
        """Get all tracks from an album"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.album_tracks(album_id, limit=50)
        tracks = results['items']
        
        # Get additional album info to add to tracks
        album_info = self.spotify.album(album_id)
        
        # Enhance track info with album details
        for track in tracks:
            track['album'] = {
                'id': album_info['id'],
                'name': album_info['name'],
                'images': album_info['images']
            }
            # Album tracks don't include artist info in the same way
            track['artists'] = album_info['artists']
        
        return tracks

    def get_artist_top_tracks(self, artist_id, country='US'):
        """Get top tracks for an artist"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        results = self.spotify.artist_top_tracks(artist_id, country=country)
        return results['tracks']

    def get_radio_recommendations(self, seed_tracks=None, seed_artists=None, seed_genres=None, limit=50):
        """Get radio-style recommendations based on seeds"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        # Ensure we have at least one seed
        if not any([seed_tracks, seed_artists, seed_genres]):
            raise ValueError("At least one seed (track, artist, or genre) is required")
        
        kwargs = {'limit': limit}
        
        if seed_tracks:
            kwargs['seed_tracks'] = seed_tracks[:5]
        if seed_artists:
            kwargs['seed_artists'] = seed_artists[:5]
        if seed_genres:
            kwargs['seed_genres'] = seed_genres[:5]
        
        return self.spotify.recommendations(**kwargs)

    def search_genre_tracks(self, genre, limit=50):
        """Search for tracks by genre"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        # Spotify doesn't have direct genre search, so we use recommendations
        # with just a genre seed
        try:
            recommendations = self.get_radio_recommendations(
                seed_genres=[genre.lower()],
                limit=limit
            )
            return recommendations['tracks']
        except Exception as e:
            # Fallback to searching for the genre term
            logger.warning(f"Genre recommendation failed, falling back to search: {e}")
            return self.search_track(f"genre:{genre}", limit=limit)

    def get_available_genre_seeds(self):
        """Get list of available genre seeds for recommendations"""
        if not self.spotify:
            raise Exception("Spotify not authenticated")
        
        result = self.spotify.recommendation_genre_seeds()
        return result['genres']