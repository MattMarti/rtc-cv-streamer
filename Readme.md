# RTC CV Streamer

## Requirements

1. python 3.8
1. node.js
1. npm

## Setup

I'll update this in the future

## Usage

There are two HTML pages in the "js" folder:
1. Server.html - Obtains camera stream, and transmits to clients
1. client.html - Logs in to signaling room, and receives video stream. Press "start" button to start streams, "stop" to stop

Run the python server by running "python-server/aiortcDriver.py". It logs in to the signaling room, and sends video to clients.

For now, the python server breaks when clients disconnect or stop the video feed.
