#!/usr/bin/env python3
"""
NotVox Integration Test Script
Tests all commands against a running NotVox server
Updated for current command structure
"""

import subprocess
import time
import sys
import json
from datetime import datetime
from pathlib import Path

# Test configuration
TEST_TRACK = "Never Gonna Give You Up"  # Classic test track
TEST_DURATION = "15s"  # Short duration for testing
SERVER_URL = "http://localhost:8080"

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class NotVoxTester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
        
    def run_command(self, command, expect_failure=False):
        """Run a notvox command and return result"""
        try:
            # Use shell=True to properly handle quoted arguments
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if expect_failure:
                return result.returncode != 0
            else:
                if result.returncode != 0:
                    print(f"Command failed: {command}")
                    print(f"STDOUT: {result.stdout}")
                    print(f"STDERR: {result.stderr}")
                return result.returncode == 0, result.stdout, result.stderr
                
        except subprocess.TimeoutExpired:
            print(f"Command timed out: {command}")
            return False, "", "Timeout"
        except Exception as e:
            print(f"Command error: {e}")
            return False, "", str(e)
    
    def test(self, name, func):
        """Run a test and track results"""
        print(f"\n{BLUE}Testing: {name}{RESET}")
        try:
            result = func()
            if result:
                print(f"{GREEN}✓ PASSED{RESET}")
                self.passed += 1
            else:
                print(f"{RED}✗ FAILED{RESET}")
                self.failed += 1
            self.tests.append((name, result))
            return result
        except Exception as e:
            print(f"{RED}✗ FAILED: {e}{RESET}")
            self.failed += 1
            self.tests.append((name, False))
            return False
    
    def wait(self, seconds, message="Waiting"):
        """Wait with progress indicator"""
        print(f"{message}...", end='', flush=True)
        for i in range(seconds):
            print(".", end='', flush=True)
            time.sleep(1)
        print(" done")
    
    def summary(self):
        """Print test summary"""
        print(f"\n{'='*50}")
        print(f"{BLUE}TEST SUMMARY{RESET}")
        print(f"{'='*50}")
        
        total = self.passed + self.failed
        if total == 0:
            print("No tests run!")
            return
        
        for name, passed in self.tests:
            status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
            print(f"{name:<40} [{status}]")
        
        print(f"\n{GREEN}Passed: {self.passed}{RESET}")
        print(f"{RED}Failed: {self.failed}{RESET}")
        print(f"Total: {total}")
        
        success_rate = (self.passed / total) * 100
        color = GREEN if success_rate >= 80 else YELLOW if success_rate >= 60 else RED
        print(f"{color}Success Rate: {success_rate:.1f}%{RESET}")


def main():
    tester = NotVoxTester()
    
    print(f"{BLUE}NotVox Integration Test Suite{RESET}")
    print(f"{'='*50}")
    print(f"Server URL: {SERVER_URL}")
    print(f"Test Track: {TEST_TRACK}")
    print(f"Test Duration: {TEST_DURATION}")
    
    # BASIC TESTS
    # Test 1: Health check
    def test_health():
        success, stdout, _ = tester.run_command("notvox health")
        return success and "Server is healthy" in stdout
    
    tester.test("Health Check", test_health)
    
    # Test 2: Configuration
    def test_config():
        success, stdout, _ = tester.run_command("notvox config")
        return success and "Server URL:" in stdout
    
    tester.test("Configuration Display", test_config)
    
    # Test 3: Stop (ensure clean state)
    def test_initial_stop():
        success, _, _ = tester.run_command("notvox stop")
        return success
    
    tester.test("Initial Stop (Clean State)", test_initial_stop)
    
    # Test 4: Status when idle
    def test_idle_status():
        success, stdout, _ = tester.run_command("notvox status")
        return success and "No active session" in stdout
    
    tester.test("Status When Idle", test_idle_status)
    
    # Test 5: Play a track
    def test_play():
        success, stdout, _ = tester.run_command(f'notvox cue "{TEST_TRACK}" {TEST_DURATION}')
        return success and ("Now playing:" in stdout or "[OK]" in stdout)
    
    tester.test("Play Track", test_play)
    
    tester.wait(3, "Letting track play")
    
    # Test 6: Status while playing
    def test_playing_status():
        success, stdout, _ = tester.run_command("notvox status")
        return success and "[PLAYING]" in stdout
    
    tester.test("Status While Playing", test_playing_status)
    
    # Test 7: Extend session
    def test_extend():
        success, stdout, _ = tester.run_command("notvox extend 5s")
        return success and "extended" in stdout
    
    tester.test("Extend Session", test_extend)
    
    # Test 8: Stop playback
    def test_stop():
        success, stdout, _ = tester.run_command("notvox stop")
        return success and "stopped" in stdout.lower()
    
    tester.test("Stop Playback", test_stop)
    
    # Test 9: History
    def test_history():
        success, stdout, _ = tester.run_command("notvox history --limit 5")
        return success and ("Recent playback sessions" in stdout or "playback history" in stdout)
    
    tester.test("Show History", test_history)
    
    # Test 10: Search
    def test_search():
        success, stdout, _ = tester.run_command(f'notvox search "{TEST_TRACK}"')
        return success and "Search results" in stdout
    
    tester.test("Search Tracks", test_search)
    
    # QUEUE TESTS
    # Test 11: Queue operations
    def test_queue_add():
        success, stdout, _ = tester.run_command(f'notvox queue add "{TEST_TRACK}" 15s')
        return success and ("[QUEUED]" in stdout or "[OK]" in stdout)
    
    tester.test("Add to Queue", test_queue_add)
    
    # Test 12: Show queue
    def test_queue_show():
        success, stdout, _ = tester.run_command("notvox queue")
        return success
    
    tester.test("Show Queue", test_queue_show)
    
    # Test 13: Lucky mode
    def test_lucky():
        # Ensure we have some history first
        tester.run_command(f'notvox cue "Test Track" 5s')
        time.sleep(1)
        tester.run_command("notvox stop")
        time.sleep(1)
        
        success, stdout, _ = tester.run_command(f"notvox lucky {TEST_DURATION}")
        return success and ("[LUCKY]" in stdout or "Lucky pick:" in stdout)
    
    tester.test("Lucky Mode", test_lucky)
    
    tester.wait(3, "Waiting for lucky track")
    
    # Test 14: Skip
    def test_skip():
        success, stdout, _ = tester.run_command("notvox skip")
        return success and "[SKIP]" in stdout
    
    tester.test("Skip Track", test_skip)
    
    # Test 15: Resume (need to stop something first)
    def test_resume():
        # First play and stop something
        tester.run_command(f'notvox cue "{TEST_TRACK}" 30s')
        time.sleep(2)
        tester.run_command("notvox stop")
        time.sleep(1)
        
        # Now try to resume
        success, stdout, _ = tester.run_command("notvox resume")
        return success and ("Resumed:" in stdout or "[OK]" in stdout)
    
    tester.test("Resume Session", test_resume)
    
    # Test 16: Clear queue
    def test_queue_clear():
        # Add something to queue first
        tester.run_command(f'notvox queue add "test song" 30s')
        
        # Clear queue with auto-confirmation
        success, stdout, _ = tester.run_command("echo y | notvox queue clear")
        
        return success and ("Cleared" in stdout or "[OK]" in stdout)
    
    tester.test("Clear Queue", test_queue_clear)
    
    # Test 17: Quietly cue
    def test_quietly():
        success, stdout, _ = tester.run_command(f'notvox quietly cue "{TEST_TRACK}" {TEST_DURATION}')
        # Quiet mode should have minimal output
        return success and len(stdout.strip()) < 100
    
    tester.test("Quietly Cue", test_quietly)
    
    # Test 18: Combined history
    def test_combined_history():
        success, stdout, _ = tester.run_command("notvox history --combined")
        return success
    
    tester.test("Combined History", test_combined_history)
    
    # MODE TESTS
    # Test 19: List modes
    def test_mode_list():
        success, stdout, _ = tester.run_command("notvox mode list")
        return success and "Available modes" in stdout
    
    tester.test("List Modes", test_mode_list)
    
    # Test 20: Quick focus mode
    def test_focus_mode():
        success, stdout, _ = tester.run_command(f"notvox focus -d {TEST_DURATION}")
        return success and "[FOCUS MODE]" in stdout
    
    tester.test("Focus Mode", test_focus_mode)
    
    tester.wait(2, "Testing focus mode")
    
    # Test 21: Check current mode
    def test_current_mode():
        success, stdout, _ = tester.run_command("notvox mode")
        return success and "[CURRENT MODE]" in stdout and "focus" in stdout
    
    tester.test("Current Mode Check", test_current_mode)
    
    # Test 22: Stop mode
    def test_mode_stop():
        success, stdout, _ = tester.run_command("notvox mode stop")
        return success and "[STOP]" in stdout
    
    tester.test("Stop Mode", test_mode_stop)
    
    # Test 23: Party mode
    def test_party_mode():
        success, stdout, _ = tester.run_command(f"notvox party -d {TEST_DURATION}")
        return success and "[PARTY MODE]" in stdout
    
    tester.test("Party Mode", test_party_mode)
    
    tester.wait(2, "Testing party mode")
    tester.run_command("notvox stop")
    
    # Test 24: Create custom mode
    def test_create_mode():
        success, stdout, _ = tester.run_command('notvox mode create "test-mode" --based-on focus --description "Test mode for testing"')
        return success and "[OK]" in stdout and "Created mode" in stdout
    
    tester.test("Create Custom Mode", test_create_mode)
    
    # Test 25: Start custom mode
    def test_custom_mode():
        success, stdout, _ = tester.run_command(f'notvox mode start test-mode -d {TEST_DURATION}')
        return success and "[MODE]" in stdout
    
    tester.test("Start Custom Mode", test_custom_mode)
    
    tester.wait(2, "Testing custom mode")
    tester.run_command("notvox stop")
    
    # Test 26: Configure mode
    def test_configure_mode():
        success, stdout, _ = tester.run_command('notvox mode config test-mode --volume 60')
        return success and "[OK]" in stdout
    
    tester.test("Configure Mode", test_configure_mode)
    
    # Test 27: Delete custom mode
    def test_delete_mode():
        # Use echo to auto-confirm
        success, stdout, _ = tester.run_command('echo "y" | notvox mode delete test-mode')
        return success and "[OK]" in stdout
    
    tester.test("Delete Custom Mode", test_delete_mode)
    
    # Test 28: Mode with lucky
    def test_mode_lucky():
        # Start a mode first
        tester.run_command(f"notvox focus -d 30s")
        time.sleep(1)
        
        # Lucky should be mode-aware
        success, stdout, _ = tester.run_command(f"notvox lucky {TEST_DURATION}")
        result = success and ("[LUCKY]" in stdout or "Lucky pick:" in stdout)
        
        # Clean up
        tester.run_command("notvox mode stop")
        return result
    
    tester.test("Mode-Aware Lucky", test_mode_lucky)

    # VOLUME & DEVICE TESTS
    # Test 29: Get current volume
    def test_get_volume():
        # Make sure something is playing first
        tester.run_command(f'notvox cue "test" 30s')
        time.sleep(2)
        
        success, stdout, _ = tester.run_command("notvox volume")
        result = success and "Current volume:" in stdout
        
        tester.run_command("notvox stop")
        return result

    tester.test("Get Volume", test_get_volume)

    # Test 30: Set volume
    def test_set_volume():
        tester.run_command(f'notvox cue "test" 30s')
        time.sleep(2)
        
        success, stdout, _ = tester.run_command("notvox volume 50")
        result = success and "[OK]" in stdout and "50%" in stdout
        
        tester.run_command("notvox stop")
        return result

    tester.test("Set Volume", test_set_volume)

    # Test 31: Relative volume with -- separator
    def test_relative_volume():
        tester.run_command(f'notvox cue "test" 30s')
        time.sleep(2)
        
        # Set baseline
        tester.run_command("notvox volume 40")
        
        # Test positive relative
        success1, stdout1, _ = tester.run_command("notvox volume +20")
        plus_ok = success1 and "[OK]" in stdout1 and "60%" in stdout1
        
        # Test negative relative (need -- to separate negative number from options)
        success2, stdout2, _ = tester.run_command("notvox volume -- -15")
        minus_ok = success2 and "[OK]" in stdout2 and "45%" in stdout2
        
        result = plus_ok and minus_ok
        
        tester.run_command("notvox stop")
        return result

    tester.test("Relative Volume", test_relative_volume)

    # Test 32: List devices
    def test_list_devices():
        success, stdout, _ = tester.run_command("notvox device")
        return success and ("Available Spotify devices" in stdout or "No Spotify devices" in stdout)

    tester.test("List Devices", test_list_devices)

    # Test 33: Device list command
    def test_device_list_command():
        success, stdout, _ = tester.run_command("notvox device list")
        return success

    tester.test("Device List Command", test_device_list_command)

    # Test 34: Mode with volume
    def test_mode_with_volume():
        # Start with a known volume
        tester.run_command(f'notvox cue "test" 15s')
        time.sleep(1)
        tester.run_command("notvox volume 30")
        tester.run_command("notvox stop")
        
        # Start party mode
        success, stdout, _ = tester.run_command(f"notvox party -d {TEST_DURATION}")
        result = success and "[PARTY MODE]" in stdout
        
        time.sleep(2)
        
        # Check if volume was set to party level (should be 80 or adjusted for time)
        vol_success, vol_stdout, _ = tester.run_command("notvox volume")
        volume_changed = vol_success and "Current volume:" in vol_stdout and "30%" not in vol_stdout
        
        tester.run_command("notvox stop")
        return result and volume_changed

    tester.test("Mode Sets Volume", test_mode_with_volume)

    # CUE SUBCOMMAND TESTS
    # Test 35: Cue track subcommand
    def test_cue_track():
        success, stdout, _ = tester.run_command(f'notvox cue track "{TEST_TRACK}" {TEST_DURATION}')
        result = success and ("Now playing:" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
        
        return result

    tester.test("Cue Track Subcommand", test_cue_track)

    # Test 36: Cue playlist subcommand
    def test_cue_playlist():
        success, stdout, _ = tester.run_command('notvox cue playlist "Today\'s Top Hits" 30s')
        result = success and ("Now playing:" in stdout or "No playlists found" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
            tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Cue Playlist Subcommand", test_cue_playlist)

    # Test 37: Cue album subcommand
    def test_cue_album():
        success, stdout, _ = tester.run_command('notvox cue album "Abbey Road" 30s')
        result = success and ("Now playing:" in stdout or "No albums found" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
            tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Cue Album Subcommand", test_cue_album)

    # Test 38: Cue artist subcommand
    def test_cue_artist():
        success, stdout, _ = tester.run_command('notvox cue artist "The Beatles" 30s')
        result = success and ("Now playing:" in stdout or "No artists found" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
            tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Cue Artist Subcommand", test_cue_artist)

    # Test 39: Cue radio subcommand
    def test_cue_radio():
        success, stdout, _ = tester.run_command('notvox cue radio "Let It Be" 30s')
        result = success and ("Now playing:" in stdout or "Creating radio" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
            tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Cue Radio Subcommand", test_cue_radio)

    # Test 40: Cue genre subcommand
    def test_cue_genre():
        success, stdout, _ = tester.run_command('notvox cue genre jazz 30s')
        result = success and ("Now playing:" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
            tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Cue Genre Subcommand", test_cue_genre)

    # Test 41: Cue with --lucky flag
    def test_cue_lucky_flag():
        success, stdout, _ = tester.run_command(f'notvox cue --lucky {TEST_DURATION}')
        result = success and ("[LUCKY]" in stdout or "Lucky pick:" in stdout or "[OK]" in stdout)
        
        if success:
            time.sleep(2)
            tester.run_command("notvox stop")
        
        return result

    tester.test("Cue with Lucky Flag", test_cue_lucky_flag)

    # Test 42: Cue with --select flag
    def test_cue_select_flag():
        # This will likely need user interaction or might fail if not supported in non-interactive mode
        success, stdout, stderr = tester.run_command(f'notvox cue --select "Beatles" 30s')
        # Just check it doesn't crash - might not work in automated testing
        result = success or "interactive" in stderr.lower() or "select" in stderr.lower()
        
        if success:
            time.sleep(1)
            tester.run_command("notvox stop")
        
        return result

    tester.test("Cue with Select Flag", test_cue_select_flag)

    # Test 43: Basic cue (no subcommand)
    def test_basic_cue():
        success, stdout, _ = tester.run_command(f'notvox cue "Beatles" 30s')
        result = success and ("Now playing:" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
        
        return result

    tester.test("Basic Cue (No Subcommand)", test_basic_cue)

    # Test 44: Cue full duration (no duration specified)
    def test_cue_full_duration():
        success, stdout, _ = tester.run_command('notvox cue track "Short Song"')
        result = success and ("Now playing:" in stdout or "[OK]" in stdout)
        
        if success and "Now playing:" in stdout:
            time.sleep(2)
            tester.run_command("notvox stop")
        
        return result

    tester.test("Cue Full Duration", test_cue_full_duration)

    # Test 45: Invalid duration handling
    def test_invalid_duration():
        success, stdout, stderr = tester.run_command('notvox cue "test" invalid')
        # Should fail gracefully
        return not success and ("Invalid duration" in stderr or "invalid" in stderr.lower())

    tester.test("Invalid Duration Handling", test_invalid_duration)

    # Test 46: Status JSON output
    def test_status_json():
        tester.run_command(f'notvox cue "test" 30s')
        time.sleep(2)
        
        success, stdout, _ = tester.run_command("notvox status --json")
        result = success
        if success:
            try:
                data = json.loads(stdout)
                result = "session_id" in data or "active" in data
            except:
                result = False
        
        tester.run_command("notvox stop")
        return result

    tester.test("Status JSON Output", test_status_json)

    # Test 47: History JSON output
    def test_history_json():
        success, stdout, _ = tester.run_command("notvox history --json --limit 5")
        result = success
        if success:
            try:
                data = json.loads(stdout)
                result = isinstance(data, list) or "sessions" in data
            except:
                result = False
        
        return result

    tester.test("History JSON Output", test_history_json)

    # Test 48: Queue next
    def test_queue_next():
        # Add multiple items to queue
        tester.run_command(f'notvox queue add "Song 1" 30s')
        tester.run_command(f'notvox queue add "Song 2" 30s')
        tester.run_command(f'notvox queue add "Song 3" 30s')
        
        # Play next from queue
        success, stdout, _ = tester.run_command("notvox queue next")
        result = success and ("[OK]" in stdout or "Playing next" in stdout)
        
        time.sleep(2)
        tester.run_command("notvox stop")
        tester.run_command("echo y | notvox queue clear")
        
        return result

    tester.test("Queue Next", test_queue_next)

    # Test 49: Version command
    def test_version():
        success, stdout, _ = tester.run_command("notvox --version")
        return success and "notvox" in stdout and "0.1.0" in stdout

    tester.test("Version Display", test_version)

    # Cleanup - stop any playing track
    tester.run_command("notvox stop")
    
    # Print summary
    tester.summary()
    
    # Exit with appropriate code
    sys.exit(0 if tester.failed == 0 else 1)


if __name__ == "__main__":
    main()