import json
import asyncio
import traceback
from io import StringIO
from pyee import AsyncIOEventEmitter

"""
Some notes

it would be a good idea to have a watchdog that flushes the buffers
if it times out after waiting for like 0.1 second
"""

class ScaledroneDriver(AsyncIOEventEmitter):
    room_hash = "smitty_werbenjagermanjensen"
    room_members = [] # TODO: Update this in a function
    clients_dict = {} # TODO: Update this in a function
    clientId = "" # TODO: Update this in a function
    _sp = None # Subprocess which runs Scaledrone.js
    
    # See "ScaledroneDriver.js" for the events that can emit
    event_list = ["literal", "join", "member_join", "member_leave", "data"]
    
    def __init__(self, room_hash: str):
        super().__init__()
        self.room_hash = room_hash
    
    def __del__(self):
        self.kill()
    
    def kill(self):
        if self._sp != None:
            self._sp.kill()
            self._sp = None
    
    def flush(self):
        pass # TODO: Is there a way to flush asyncio subprocesses?
        #self._sp.stdin.flush()
        #self._sp.stdout.flush()
    
    async def run_loop(self):
        self._sp = await asyncio.create_subprocess_exec(
            *["node", "ScaledroneDriver.js", self.room_hash],
            stdin = asyncio.subprocess.PIPE, 
            stdout = asyncio.subprocess.PIPE,
            stderr = asyncio.subprocess.PIPE
        )
        await asyncio.wait([
            self._read_stdin(),
            self._read_stderr()
        ])
    
    def publish(self, string: str):
        if self._sp is None:
            return
        string = string.replace("'" ,"\"")
        self._sp.stdin.write(bytes(string + "\n", 'utf-8'))
    
    async def _read_stdin(self):
        while self._sp is not None: #TODO: Make this smarter
            bytes_in = await self._sp.stdout.readline()
            if bytes_in:
                json_string = str(bytes_in, 'utf-8').strip()
                await self._process_line(json_string)
                
    async def _read_stderr(self):
        while self._sp is not None: #TODO: Make this smarter
            bytes_in = await self._sp.stderr.readline()
            if bytes_in:
                pass # TODO
    
    async def _process_line(self, json_string):
        print(">> Recieved String ->", json_string)
        try:
            json_data = json.loads(json_string)
            for event in self.event_list:
                if event in json_data:
                    data = json.dumps(json_data[event])
                    if event == "join":
                        self.clientId = json_data[event]
                    self.emit(event, data)
        except Exception as error:
            self.emit('exception', error)


# ------ Example Use Case ------

if __name__ == '__main__':
    """
    This is an example of running the ScaledroneDriver class
    """

    sdd = ScaledroneDriver(default_room_hash)
    
    # Define callbacks after initializing the Scaledrone object
    
    @sdd.on('exception')
    def print_error(e):
        print('>> Exception:', str(e))

    @sdd.on('join')
    def join_callback(id_json):
        id = json.loads(id_json)
        print(">> Joined room with id", id)
        
    @sdd.on('member_join')
    def print_member_join(str):
        json_data = json.loads(str)
        name = json_data["clientData"]["name"]
        id = json_data["id"]
        print(">> New member:", name + "-" + id)
        
    @sdd.on('member_leave')
    def print_member_join(str):
        json_data = json.loads(str)
        name = json_data["clientData"]["name"]
        id = json_data["id"]    
        print(">> Member leave:", name + "-" + id)
    
    @sdd.on('data')
    def print_event(event):
        json_data = json.loads(event)
        if "sdp" in json_data:
            print(">> SDP:", json_data["member"]["clientData"]["name"] + "-" + json_data["member"]["id"])
        if "candidate" in json_data:
            print(">> ICE:", json_data["member"]["clientData"]["name"] + "-" + json_data["member"]["id"])
    
    asyncio.run(sdd.run_loop())