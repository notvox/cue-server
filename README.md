# cue-server
(noun) : something clever someday

### what is this?
this is the server component of notvox cue. Meant to be run on a "nodbox", but can be run locally too.  
Honestly it's better locally that way you can control playback to your machine instead of to some server meant to just play silently.  

#### setup
clone the repo.  
`cd nodbox`
probably make a venv if you don't want to clutter your global python environment.  
the makefile delegates server spinup and shutdown through a second script, `dev.sh`.  
use the makefile.  

You need spotify credentials.  
add them to a .env file in the format:  
```
export SPOTIFY_CLIENT_ID="your client id"
export SPOTIFY_CLIENT_SECRET="your client secret"
export SPOTIFY_REDIRECT_URI="http://127.0.0.1:8080/callback"
```

then `make start` to start the server