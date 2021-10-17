const readline = require('readline');
const ScaleDrone = require('scaledrone-node');

// ---------------- Constants ----------------

/* Important global variables */
const DRONE_CLIENT_ID = 'C00ByYrXvpYm9Ror'; // ScaleDrone room id
let room; // Scaledrone room which we are subscribed to

let roomHash;
if (process.argv.length > 2) {
    roomHash = process.argv[2];
}
else {
    roomHash = 'smitty_werbenjagermanjensen';
}


// ---------------- Signalling Service Callbacks ----------------

// Subscribe to room
const roomName = 'videostream-' + roomHash; // This hash code is what makes you need the URL. If set to a known value, it'll always be the same room
const observableRoomName = 'observable-' + roomName;

const drone = new ScaleDrone(DRONE_CLIENT_ID, { data: { name: 'server' } });

// Define callbacks
drone.on('open', error => {
    if (error) {
        console.error(error);
        return;
    }
    
    // Subscribe to the ScaleDrone room.
    room = drone.subscribe(observableRoomName);
    room.on('open', error => {
        if (error) {
            console.error(error);
        }
        let output = {'join' : drone.clientId};
        console.log(JSON.stringify(output));
    });
    
    // Connected to room and receive array of members
    room.on('members', receivedMembers => {
        receivedMembers.forEach( (member) => {
            let output = {'member_join' : member};
            console.log(JSON.stringify(output));
        });
    });
    
    // Called when a new member joins the room
    room.on('member_join', member => {
        let output = {'member_join' : member};
        console.log(JSON.stringify(output));
    });
    
    // Called when a member leaves the room
    room.on('member_leave', (member) => {
        let output = {'member_leave' : member};
        console.log(JSON.stringify(output));
    });
    
    // Listen to signaling data from Scaledrone
    room.on('data', (message, sendingPeer) => {
        if(message.targetId !== drone.clientId) {
            return;
        }
        message.member = sendingPeer;
        let output = {'data' : message};
        console.log(JSON.stringify(output));
    });
});

// Listen for signals on standard in
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});
rl.on('line', (string) => {
    try {
        message = JSON.parse(string)
        drone.publish({
            room: observableRoomName,
            message
        });
    }
    catch (error) {
        console.error(error);
    }
});