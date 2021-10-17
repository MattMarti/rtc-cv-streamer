import time
import json
import sys
import traceback
import asyncio

import cv2
import av
import aiortc

from ScaledroneDriver import ScaledroneDriver


# --------- CONSANTS ---------

cannyedge_min = 25
cannyedge_max = 100
FRAME_RATE = 20

# Signaling Server Parameters
room_hash = "smitty_werbenjagermanjensen"

# Setup ICE Configuration for RTC object
stun_servers = ['stun:stun.l.google.com:19302']
ice_server = aiortc.RTCIceServer(stun_servers)
ice_config = aiortc.RTCConfiguration()

# AIORTC constants
rtc_client_map = {}


# --------- SETUP VIDEO TRACK ---------

class FrameGetter():

    delta_t_frame = 1/float(FRAME_RATE)
    latest_image = None
    n_images = 0
    __cap = None

    def __init__(self):
        self.__cap = cv2.VideoCapture(0)
    
    def __captureFrame(self):
        is_good, img = self.__cap.read()
        if is_good:
            self.n_images += 1
            
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.Canny(img, cannyedge_min, cannyedge_max)
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            
            self.latest_image = img
    
    async def asyncRun(self):
        """
        Continuously updates the current frame
        """
        while True:
            self.__captureFrame()
            await asyncio.sleep(self.delta_t_frame)
    
    def run(self):
        """
        Continuously updates the current frame
        """
        while True:
            self.__captureFrame()
            time.sleep(self.delta_t_frame)

frame_getter = FrameGetter()


class MyStreamTrack(aiortc.VideoStreamTrack):
    """
    A video stream track that returns an image.
    """
    
    delta_t_frame = 0
    
    # Required for AIORTC
    kind = "video"
    
    def __init__(self):
        super().__init__()
        delta_t_frame = 1/float(FRAME_RATE)
    
    #async def next_timestamp(self):
    #    await asyncio.sleep(self.delta_t_frame)
    
    # Required for AIORTC
    async def recv(self) -> av.VideoFrame:
        """
        Returns the latest frame for AIORTC
        """
        pts, time_base = await self.next_timestamp()
        #frame = await self.track.recv()
        
        # Frame capture
        img = frame_getter.latest_image
        
        # rebuild a VideoFrame, preserving timing information
        new_frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame


# --------- SETUP SCALEDRONE ---------

sdd = ScaledroneDriver(room_hash)

@sdd.on('exception')
def print_error(e):
    print(f'>> Exception! {e}')

@sdd.on('literal')
def print_literal_message(literal:str):
    print(f">> Literal:{literal}")

@sdd.on('member_join')
def member_join(jsonstr:str):
    json_data = json.loads(jsonstr)
    name = json_data["clientData"]["name"]
    id = json_data["id"]
    print(f">> New member:{name}-{id}")
    rtc_client_map[id] = RTC_Client_Connection(id)

@sdd.on('member_leave')
async def member_leave(jsonstr:str):
    json_data = json.loads(jsonstr)
    name = json_data["clientData"]["name"]
    id = json_data["id"]    
    print(f">> Member leave:{name}-{id}")
    await rtc_client_map[id].close()
    rtc_client_map.pop(id)

@sdd.on('data')
async def data_event(event):
    json_data = json.loads(event)
    id = json_data["member"]["id"]
    print(f">> Data event from {id}")
    await rtc_client_map[id].reactToMessage(json_data)


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
    __local_stream = None
    
    # Initialize the connection with the ScaleDrone id of the connected peer
    def __init__(self, id:str):
        self.id = id
    
    async def close(self):
        print(">> Closing", self.id)
        if self.__pc is not None:
            await self.__pc.close()
    
    # This function defines behavior on receiving SDP and ICE messages
    async def reactToMessage(self, json_data):
        if "sdp" in json_data:
            if json_data["sdp"]["type"] != "offer":
                return
            
            self.__pc = aiortc.RTCPeerConnection(ice_config)
            self.__local_stream = MyStreamTrack()
            self.__pc.addTrack(self.__local_stream)
            
            desc = aiortc.RTCSessionDescription(json_data["sdp"]["sdp"], "offer")
            print(">> setting remote description ...")
            try:
                await self.__pc.setRemoteDescription(desc)
            except Exception as e:
                traceback.print_exc()
                return
            if desc.type == "offer":
                print(">> Creating Answer")
                newLocalDesc = await self.__pc.createAnswer()
                await self.localDescCreated(newLocalDesc)
                # TODO: Error handling
        
        if "candidate" in json_data and self.__pc is not None:
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
    async def localDescCreated(self, desc):
        if self.__pc is not None:
            print(f'>> Setting local description for {self.id}')
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

async def tasks():
    task_get_camera_frames = asyncio.create_task(frame_getter.asyncRun())
    task_signaling = asyncio.create_task(sdd.run_loop())
    await task_get_camera_frames
    await task_signaling

    
def main():
    asyncio.run(tasks())


if __name__ == '__main__':
    main()
    