# drop_test_sender.py

from alsa_midi import (
   SequencerClient, Port, PortInfo, PortCaps, READ_PORT, WRITE_PORT, RW_PORT,
   PortType,

   SYSTEM_TIMER, SYSTEM_ANNOUNCE,

   alsa, ALSAError,

   EventType, Address,

   EventFlags,  # TIME_STAMP_TICK, TIME_MODE_ABS, EVENT_LENGTH_FIXED, PRIORITY_NORMAL are all 0

   NoteOnEvent, NoteOffEvent, KeyPressureEvent, ProgramChangeEvent, ChannelPressureEvent,
   PitchBendEvent, NonRegisteredParameterChangeEvent, RegisteredParameterChangeEvent,
   SetQueueTempoEvent, SongPositionPointerEvent, ControlChangeEvent, SystemEvent,
   TimeSignatureEvent, StartEvent, ContinueEvent, StopEvent, ClockEvent, MidiBytesEvent,
)
from alsa_midi.client import StreamOpenType
from alsa_midi.port import DEFAULT_PORT_TYPE

SND_SEQ_QUEUE_DIRECT = alsa.SND_SEQ_QUEUE_DIRECT

Client = SequencerClient("Sender", streams=StreamOpenType.DUPLEX)
Port = Client.create_port("Output", READ_PORT, DEFAULT_PORT_TYPE)

for port in Client.list_ports():
    if port.client_name == "Receiver":
        Port.connect_to(port)
        break
else:
    print('Could not find "Receiver" to connect to')

while True:
    command = input("s)end NoteOn, d)rain_output: ")
    if command[0] == 's':
        print("Sending NoteOn")
        # note, channel, velocity
        Client.event_output(NoteOnEvent(60, 0, 50), queue=SND_SEQ_QUEUE_DIRECT, port=Port)
    elif command[0] == 'd':
        print("Calling drain_output")
        Client.drain_output()
    else:
        print("Unrecognized command", repr(command))

