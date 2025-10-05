# drop_test_receiver.py

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

Client = SequencerClient("Receiver", streams=StreamOpenType.DUPLEX)
Port = Client.create_port("Input", WRITE_PORT, DEFAULT_PORT_TYPE)

for port in Client.list_ports():
    if port.client_name == "Sender":
        Port.connect_from(port)
        break
else:
    print('Could not find "Sender" to connect from')

while True:
    input("Hit Enter to receive event: ")
    print("Calling event_input()")
    event = Client.event_input()
    print("Got", event)

