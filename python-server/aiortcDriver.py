import time
import json
import threading
import sys

import asyncio

import cv2

import av

import aiortc

from ScaledroneDriver import ScaledroneDriver

"""
TODO:

Separate the image capture and the MediaTrack. The image capture
should be done in it's own thread. It would be good to create a 
circular buffer to store images. There needs to be one media track
per peer connection unfortunately.

Investigate using Coturn to create a STUN server. It's a good idea
to have our own STUN instead of using Google's STUN. Also, it might
speed things up.

Can we purchase space on a public server somewhere (Amzaon EC2?)

"""


# --------- CONSANTS ---------

cannyedge_min = 25
cannyedge_max = 100
frame_rate = 30

# Signaling Server Parameters
room_hash = "smitty_werbenjagermanjensen"

# Setup ICE Configuration for RTC object
stun_servers = ['stun:stun.l.google.com:19302']
ice_server = aiortc.RTCIceServer(stun_servers)
ice_config = aiortc.RTCConfiguration()

# AIORTC constants
rtcClientMap = {}


# --------- SETUP VIDEO TRACK ---------

class MyStreamClass(aiortc.VideoStreamTrack):
    """
    A video stream track that returns an image.
    """
    cap = None
    latestImage = None # TODO: Let run be it's own thread, and do thread locking on it
    
    imgLck = threading.Lock()
    
    # Required for AIORTC
    kind = "video"
    
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)
        
    def __del(self):
        print(">> !!! Deleting local stream !!!")
    
    async def asyncRun(self):
        """
        Continuously updates the current frame
        """
        while True:
            isGood, img = self.cap.read()
            if not isGood:
                await asyncio.sleep(1/float(frame_rate))
                continue
            
            # Processing here
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.Canny(img, cannyedge_min, cannyedge_max)
            
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            
            self.imgLck.acquire()
            try:
                self.latestImage = img
            finally:
                self.imgLck.release()
            
            await asyncio.sleep(1/float(frame_rate))
    
    def run(self):
        """
        Continuously updates the current frame
        """
        while True:
            isGood, img = self.cap.read()
            if not isGood:
                time.sleep(1/float(frame_rate))
                continue
            
            # Processing here
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.Canny(img, cannyedge_min, cannyedge_max)
            
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            
            self.imgLck.acquire()
            try:
                self.latestImage = img
            finally:
                self.imgLck.release()
            
            time.sleep(1/float(frame_rate))
    
    # Required for AIORTC
    async def recv(self) -> av.VideoFrame:
        """
        Returns the latest frame for AIORTC
        """
        pts, time_base = await self.next_timestamp()
        #frame = await self.track.recv()
        
        # Frame capture
        self.imgLck.acquire()
        try:
            img = self.latestImage
        finally:
            self.imgLck.release()
        
        # rebuild a VideoFrame, preserving timing information
        new_frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame
        
localStream = MyStreamClass()#VideoStreamTrack()


# --------- SETUP SCALEDRONE ---------

# Run Signaling Server and define callbacks
sdd = ScaledroneDriver(room_hash)

@sdd.on('exception')
def print_error(e):
    print('>> Exception!')

@sdd.on('literal')
def print_member_join(literal: str):
    print(">> Literal:", literal)

@sdd.on('member_join')
def print_member_join(jsonstr: str):
    json_data = json.loads(jsonstr)
    name = json_data["clientData"]["name"]
    id = json_data["id"]
    print(">> New member:", name + "-" + id)
    rtcClientMap[id] = RTC_Client_Connection(id)

@sdd.on('member_leave')
async def print_member_join(jsonstr: str):
    json_data = json.loads(jsonstr)
    name = json_data["clientData"]["name"]
    id = json_data["id"]    
    print(">> Member leave:", name + "-" + id)
    await rtcClientMap[id].close()
    del rtcClientMap[id]

@sdd.on('data')
async def data_event(event):
    json_data = json.loads(event)
    id = json_data["member"]["id"]
    print(">> Data Event", id)
    await rtcClientMap[id].reactToMessage(json_data)


# --------- AIORTC STUFF ---------

class RTC_Client_Connection:
    """
    This class is a wrapper for the AIORTC API that defines necessary
    callbacks. Each instance of this class is associated with a specific
    video streaming client, and contains an idStr which is the unique 
    ScaleDrone Room ID for the particular client.
    """
    
    id = ''
    __pc = None
    
    # Initialize the connection with the ScaleDrone id of the connected peer
    def __init__(self, id: str):
        self.id = id
        self.__pc = aiortc.RTCPeerConnection(ice_config)
        
        try:
            self.addTrack(localStream)
        except Exception as e:
            print(">> Exception on adding track: ", str(e))
    
    def __del__(self):
        pass
        # TODO: Raise exception if AIORTC isn't closed (or just do it)
    
    async def close(self):
        print(">> Closing", self.id)
        await self.__pc.close()
        self.__pc = None
    
    
    def addTrack(self, track: aiortc.MediaStreamTrack):
        self.__pc.addTrack(track)
    
    # This function defines behavior on receiving SDP and ICE messages
    async def reactToMessage(self, json_data): # TODO: Make async
        if "sdp" in json_data:
            if json_data["sdp"]["type"] != "offer":
                return
            desc = aiortc.RTCSessionDescription(json_data["sdp"]["sdp"], "offer")
            print(">> setting remote description ...")
            try:
                await self.__pc.setRemoteDescription(desc)
            except Exception as e:
                print('>> Exception:', str(e), 'Line 159')
                return
            if desc.type == "offer":
                print(">> Creating Answer")
                newLocalDesc = await self.__pc.createAnswer()
                await self.localDescCreated(newLocalDesc)
                # TODO: Error handling
        
        if "candidate" in json_data:
            try:
                icestr = json_data["candidate"]["candidate"]
                candidate = aiortc.sdp.candidate_from_sdp(icestr)
                candidate.sdpMid = json_data["candidate"]["sdpMid"]
                candidate.sdpMLineIndex = json_data["candidate"]["sdpMLineIndex"]
                self.__pc.addIceCandidate(candidate)
                print(">> Success on ICE!")
            except Exception as e:
                print(">> Exception on candidate:", e)
                # TODO: this.pc.restartIce()
    
    # This gets called when creating an offer and when answering one
    # It sets the local description, and then sends the local description in an SDP
    async def localDescCreated(self, desc): # TODO: Specify type
        print(">>", self.id, "Sending SDP")
        await self.__pc.setLocalDescription(desc)
        message = {}
        message["sdp"] = {}
        message["sdp"]["type"] = "answer"
        #message["sdp"]["sdp"] = str(desc.sdp)
        message["sdp"]["sdp"] = self.__pc.localDescription.sdp
        print(">> Sending SDP:", message)
        self.sendMessage(message)
        #self.tryICE()
    
    # Send targeted signaling data via Scaledrone
    def sendMessage(self, message: dict):
        message["targetId"] = self.id;
        sdd.publish(str(message))
        print(">> Published message")
    
    
# --------- DEFINE USER INTERFACE ---------
    
async def cmdline_interface():
    pass # TODO: Let the user enter commands

async def tasks():
    task_sd = asyncio.create_task(sdd.run_loop())
    task_ui = asyncio.create_task(cmdline_interface())
    
    task_stream = asyncio.create_task(localStream.asyncRun())
    await task_stream
    
    await task_sd
    await task_ui
    
def main():
    
    # Initialize signaling room
    #define_Scaledrone(sys.argv[1])

    # Start video stream
    #streamThread = threading.Thread(target = localStream.run)
    
    asyncio.run(tasks())
    
    #streamThread.join()
    
    
if __name__ == '__main__':
    main()
    