"""
NotVox Modes System - Smart contextual playback modes
"""

import json
import os
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Default mode configurations
DEFAULT_MODES = {
    "focus": {
        "duration": "2h",
        "volume": 40,
        "genres": ["lo-fi", "ambient", "classical", "study"],
        "energy": "low",
        "instrumentalness": 0.8,  # Prefer instrumental
        "description": "Deep concentration and flow state",
        "search_terms": ["focus", "study", "concentration", "deep work"],
        "skip_threshold": 3  # More skips allowed in focus mode
    },
    "party": {
        "duration": "3h",
        "volume": 80,
        "genres": ["pop", "dance", "hip-hop", "party"],
        "energy": "high",
        "valence": 0.8,  # Happy songs
        "danceability": 0.7,  # Danceable
        "description": "Time to celebrate and have fun!",
        "search_terms": ["party hits", "dance hits", "friday night"],
        "skip_threshold": 1  # Quick skips for party killers
    },
    "sleep": {
        "duration": "45m",
        "volume": 20,
        "genres": ["ambient", "classical", "nature sounds", "meditation"],
        "energy": "minimal",
        "valence": 0.3,  # Calm/neutral
        "tempo_max": 80,  # Slow tempo
        "fade_out": "30m",
        "description": "Drift off peacefully to dreamland",
        "search_terms": ["sleep", "calm", "meditation", "relaxing"],
        "skip_threshold": 5  # Don't disturb sleep
    },
    "workout": {
        "duration": "1h",
        "volume": 70,
        "genres": ["electronic", "hip-hop", "rock", "workout"],
        "energy": "maximum",
        "tempo_min": 120,  # High BPM
        "description": "Push your limits and crush your goals",
        "search_terms": ["workout", "gym", "training", "pump up"],
        "skip_threshold": 2
    },
    "morning": {
        "duration": "30m",
        "volume": 50,
        "genres": ["indie", "folk", "acoustic", "coffee shop"],
        "energy": "medium",
        "valence": 0.7,  # Positive vibes
        "acousticness": 0.5,
        "description": "Ease into your day with good vibes",
        "search_terms": ["morning coffee", "wake up happy", "good morning"],
        "skip_threshold": 3
    },
    "chill": {
        "duration": "1h",
        "volume": 50,
        "genres": ["chillhop", "downtempo", "lo-fi hip hop", "jazz"],
        "energy": "low-medium",
        "instrumentalness": 0.6,
        "description": "Relax and unwind without sleeping",
        "search_terms": ["chill vibes", "relax", "downtempo", "mellow"],
        "skip_threshold": 4
    }
}


class ModeManager:
    def __init__(self, spotify_client=None, database=None):
        self.spotify_client = spotify_client
        self.database = database
        self.config_file = Path.home() / ".notvox" / "modes.json"
        self.current_mode = None
        self.modes = self.load_modes()
        
    def load_modes(self):
        """Load custom modes from config file, merge with defaults"""
        modes = DEFAULT_MODES.copy()
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    custom_modes = json.load(f)
                    modes.update(custom_modes)
            except Exception as e:
                logger.error(f"Error loading custom modes: {e}")
        
        return modes
    
    def save_modes(self):
        """Save current modes to config file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.modes, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving modes: {e}")
    
    def get_mode(self, mode_name):
        """Get a specific mode configuration"""
        return self.modes.get(mode_name.lower())
    
    def list_modes(self):
        """List all available modes"""
        return {
            name: {
                "description": config.get("description", ""),
                "duration": config.get("duration", "30m"),
                "volume": config.get("volume", 50)
            }
            for name, config in self.modes.items()
        }
    
    def create_mode(self, name, config):
        """Create a new custom mode"""
        if name.lower() in self.modes:
            raise ValueError(f"Mode '{name}' already exists")
        
        # Validate required fields
        if "duration" not in config:
            config["duration"] = "1h"
        if "volume" not in config:
            config["volume"] = 50
        if "description" not in config:
            config["description"] = f"Custom {name} mode"
        
        self.modes[name.lower()] = config
        self.save_modes()
        
        return config
    
    def update_mode(self, name, updates):
        """Update an existing mode configuration"""
        if name.lower() not in self.modes:
            raise ValueError(f"Mode '{name}' does not exist")
        
        self.modes[name.lower()].update(updates)
        self.save_modes()
        
        return self.modes[name.lower()]
    
    def delete_mode(self, name):
        """Delete a custom mode (cannot delete default modes)"""
        if name.lower() in DEFAULT_MODES:
            raise ValueError(f"Cannot delete default mode '{name}'")
        
        if name.lower() not in self.modes:
            raise ValueError(f"Mode '{name}' does not exist")
        
        del self.modes[name.lower()]
        self.save_modes()
    
    def set_current_mode(self, mode_name):
        """Set the current active mode"""
        if mode_name and mode_name.lower() not in self.modes:
            raise ValueError(f"Unknown mode: {mode_name}")
        
        self.current_mode = mode_name.lower() if mode_name else None
        logger.info(f"Mode set to: {self.current_mode or 'none'}")
    
    def get_current_mode(self):
        """Get the current active mode"""
        return self.current_mode
    
    def get_search_query(self, mode_name, additional_query=None):
        """Generate a search query based on mode"""
        mode = self.get_mode(mode_name)
        if not mode:
            return additional_query or ""
        
        # Use mode search terms
        search_terms = mode.get("search_terms", [])
        if search_terms and not additional_query:
            # Pick a random search term for variety
            import random
            base_query = random.choice(search_terms)
        else:
            base_query = additional_query or mode_name
        
        # Add genre hints
        genres = mode.get("genres", [])
        if genres and not additional_query:
            # Sometimes add a genre to the search
            if len(genres) > 0 and hash(datetime.now().isoformat()) % 3 == 0:
                base_query = f"{random.choice(genres)} {base_query}"
        
        return base_query
    
    def get_recommendations_params(self, mode_name, seed_tracks=None):
        """Get Spotify recommendation parameters based on mode"""
        mode = self.get_mode(mode_name)
        if not mode:
            return {}
        
        params = {}
        
        # Audio features from mode
        if "energy" in mode:
            energy_map = {
                "minimal": 0.2,
                "low": 0.3,
                "low-medium": 0.4,
                "medium": 0.5,
                "high": 0.7,
                "maximum": 0.9
            }
            if mode["energy"] in energy_map:
                params["target_energy"] = energy_map[mode["energy"]]
        
        if "valence" in mode:
            params["target_valence"] = mode["valence"]
        
        if "danceability" in mode:
            params["target_danceability"] = mode["danceability"]
        
        if "instrumentalness" in mode:
            params["target_instrumentalness"] = mode["instrumentalness"]
        
        if "acousticness" in mode:
            params["target_acousticness"] = mode["acousticness"]
        
        if "tempo_min" in mode:
            params["min_tempo"] = mode["tempo_min"]
        
        if "tempo_max" in mode:
            params["max_tempo"] = mode["tempo_max"]
        
        # Seed genres if no seed tracks
        if not seed_tracks and "genres" in mode:
            # Spotify only accepts specific genre seeds, so we need to be careful
            valid_genres = ["acoustic", "ambient", "blues", "chill", "classical", 
                          "dance", "electronic", "folk", "hip-hop", "indie", 
                          "jazz", "latin", "metal", "pop", "rock", "soul", "study"]
            
            mode_genres = [g for g in mode["genres"] if g in valid_genres]
            if mode_genres:
                params["seed_genres"] = mode_genres[:3]  # Max 3 genres
        
        return params
    
    def should_skip(self, mode_name, skip_count):
        """Determine if we should allow skip based on mode tolerance"""
        mode = self.get_mode(mode_name)
        if not mode:
            return True
        
        threshold = mode.get("skip_threshold", 3)
        return skip_count < threshold
    
    def get_volume_adjustment(self, mode_name, current_hour=None):
        """Get volume adjustment based on mode and time"""
        mode = self.get_mode(mode_name)
        if not mode:
            return None
        
        base_volume = mode.get("volume", 50)
        
        # Time-based adjustments
        if current_hour is None:
            current_hour = datetime.now().hour
        
        # Quieter at night for most modes
        if mode_name != "party" and (current_hour >= 22 or current_hour <= 6):
            base_volume = int(base_volume * 0.8)
        
        # Louder on Friday/Saturday nights for party mode
        if mode_name == "party" and datetime.now().weekday() in [4, 5]:
            base_volume = min(100, int(base_volume * 1.1))
        
        return base_volume
    
    def log_mode_usage(self, mode_name, duration_seconds, track_count, skip_count):
        """Log mode usage statistics for learning"""
        # This could be extended to save to database for analytics
        logger.info(f"Mode usage: {mode_name} - Duration: {duration_seconds}s, "
                   f"Tracks: {track_count}, Skips: {skip_count}")
        
        # TODO: Save to database for future analytics
        # self.database.log_mode_usage(mode_name, duration_seconds, track_count, skip_count)