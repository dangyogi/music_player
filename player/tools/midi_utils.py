# midi_utils.py

r'''Midi utils that deal with the alsa_midi library.

Utility:
    Log_1_01506 = math.log(1.01506) for bpm encoding

    data_to_bpm(data) -> bpm
    bpm_to_data(bpm) -> data byte for Tempo message
    time_sig_to_data(beats, beat_type) -> data byte for Time_sig message
    data_to_time_sig(data) -> (beats, beat_type), e.g., (6, 8)
    ppq_to_data(ppq) -> data byte for ControlChangeEvent to clock-master
    data_to_ppq(data) -> ppq (30-200 as float)
    midi_queue_time(queue|queue_name) -> current queue tick value

Initialization:

    midi_init(client_name, streams=DUPLEX) -> None
    midi_create_queue(name, ppq, info=None, default=True) -> Queue (only used by clock_master)
    midi_create_input_port(name, caps=READ_PORT, type=DEFAULT_PORT_TYPE, connect_from=None)
      -> Port (generally not needed)
    midi_create_output_port(name, caps=WRITE_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_master=False, connect_to=None)
      -> Port (generally not needed)
    midi_create_inout_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_master=False, connect_from=None, connect_to=None)
      -> Port (generally not needed)
    midi_create_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE, default=True, clock_master=False,
                     connect_from=None, connect_to=None):
      -> Port (generally not needed)
    midi_address(address) -> Address or None, client_name:port_name may be used
    midi_process_fn(fn) -> None, fn(event) -> bool to drain_output
    midi_close() -> None, closes tag with clock-master, all ports, queues and client

I/O:
    midi_send_event(event, queue=None, port=None, dest=None, drain_output=False) -> None
    midi_drain_output() -> None
    midi_pause(secs) -> None, reads and processes events while paused
    midi_process_clock(event) -> True if event was a clock event
                                 (Clock, Start, Stop, Continue, tempo, time_signature, spp)
                                 no drain_output required on any of these (i.e., if True returned)

To interface with the clock-master:

    midi_set_tag(tag) -> None, unique identifier for clock-master
    midi_set_ppq(ppq) -> None, sends CC_ppq to clock-master to create a queue
    midi_close_queue() -> None, sends CC_close_queue to clock-master to close the queue
    midi_set_tempo(bpm) -> None, sends message to clock-master to set tempo on all queues
    midi_set_time_signature(beats, beat_type) -> None, sends message to clock-master
    midi_start() -> None, sends message to clock-master
    midi_stop(tick=None) -> None, sends message to clock-master
    midi_continue() -> None, sends message to clock-master
    midi_spp(position, tick=None) -> None, sends message to clock-master
    midi_tick_time() -> ticks at set_ppq and set_tempo rates since start
'''

import time
import math
import selectors

from alsa_midi import (
   SequencerClient, Port, PortInfo, PortCaps, READ_PORT, WRITE_PORT, RW_PORT,
   PortType,

   ALSAError,

   EventType, Address,
   NoteOnEvent, NoteOffEvent, KeyPressureEvent, ProgramChangeEvent, ChannelPressureEvent,
   PitchBendEvent, NonRegisteredParameterChangeEvent, RegisteredParameterChangeEvent,
   SetQueueTempoEvent, SongPositionPointerEvent, ControlChangeEvent, SystemEvent,
   TimeSignatureEvent, StartEvent, ContinueEvent, StopEvent, ClockEvent, MidiBytesEvent,
)
from alsa_midi.client import StreamOpenType
from alsa_midi.port import DEFAULT_PORT_TYPE

# Midi beat clock commands:
#
#   tempo defaults to 120 bpm, here "beat" in bpm means quarter note
#
#   0xF8 - Clock; std 24 pulses (clock messages) per quarter note
#   0xFA - Start; slave starts at next Clock message, always at SPP 0; ignore if already running
#   0xFB - Continue; preserve SPP; ignore if already running
#   0xFC - Stop; ignore if already stopped
#   <there are two undefined System Real Time messages: 0xF9 and 0xFD>
#
#   0xF2 - SPP + 2 bytes as 14-bit value LSB first == midi beats (beat == 6 clocks, or a 16th note) 
#                since the start of song.  Should not be sent while devices are in play.  Use Continue
#                to start playing (Start resets SPP to 0).
#   <there are two undefined System Common messages: 0xF4 and 0xF5, both allow data bytes>
#   we'll use 0xF4 for tempo (bpm = 30 * 1.01506^data)
#         and 0xF5 for time_signature (data = (beats << 4) | (beat_type >> 1))

Tempo_status = 0xF4
Time_sig_status = 0xF5

Clock_master_channel = 15
Clock_master_CC_ppq = 44          # ppq_data = ppq // 24
Clock_master_CC_close_queue = 45  # tag
Clock_master_tag = None

System_timer = Address(0, 0)



Sel = None
Client = None
Ports = {}
Default_port = None
Clock_master_port = None
Queues = {}
Default_queue = None
Process_fn = None      # Process_fn(event) -> bool to drain_output

Bpm = None             # Beats (quarter notes) per minute
Ppq = None             # ppq setting on ALSA queue (usually maintained by clock-master)
Tick_interval = None   # secs between ticks at Ppq * Bpm
Ppc = None             # pulses per CLOCK pulse
Spp = 0                # Song Position Pointer
Spp_countdown = None   # CLOCKs left to next SPP increment
Queue_running = False
Clocks = 0             # CLOCKs received since last START
Last_clock_time = None
Time_signature = None  # (beats, beat_type)

# bpm = 30 * 1.01506^data
# bpm = 30 * exp(Log_1_01506*data)
# data = log(bpm / 30) / log(1.01506)
# data = log(bpm / 30) / Log_1_01506
Log_1_01506 = math.log(1.01506)

def data_to_bpm(data):
    r'''result bpm is rounded to a sensible number of decimals.
    '''
    raw = 30 * math.exp(Log_1_01506*data)
    if raw >= 67:
        return round(30 * math.exp(Log_1_01506*data))
    return round(30 * math.exp(Log_1_01506*data), 1)

def bpm_to_data(bpm):
    return int(round(math.log(bpm / 30) / Log_1_01506))

def time_sig_to_data(beats, beat_type):
    return (beats << 4) | (beat_type >> 1)

def data_to_time_sig(data):
    r'''Returns beats, beat_type; given the data byte in the midi message.
    '''
    return data >> 4, (data & 0xF) << 1

def ppq_to_data(ppq):
    r'''ppq must be multiple of 24.
    '''
    return ppq // 24

def data_to_ppq(data):
    return data * 24

def midi_queue_time(queue):
    if isinstance(queue, str):
        if queue not in Queues:
            print(f"midi_queue_time got unknown queue, {queue!r}")
            return None
        queue = Queues[queue]
    return queue.get_status().tick_time

def midi_init(client_name, streams=StreamOpenType.DUPLEX):
    r'''Creates Client.  All ports for the client share the same input and output memory pools.
    '''
    global Client

    Client = SequencerClient(client_name, streams=streams)
        # client_name,
        # streams (default StreamOpenType.DUPLEX -- also OUTPUT, INPUT), applies to sequencer
        # mode (default OpenMode.NONBLOCK -- or 0), applies to both read and write operations,
        #                                           must be NONBLOCK
        # sequencer_name (default "default"), special meaning to ALSA, usually want "default"
    print(f"{Client.client_id=}")     # client_ids are globally unique
    #print(f"{Client.get_client_info()=}")
    #print(f"{Client.get_client_pool()=}")

    #print(dir(Client))
    #
    # client_id
    # create_queue
    # get_client_info
    # get_client_pool
    # get_named_queue
    # get_port_info
    # get_queue
    # get_queue_info
    # get_queue_status
    # get_sequencer_name
    # get_sequencer_type
    # get_system_info
    # list_ports
    # query_named_queue
    # set_client_info
    #help(Client.get_port_info)

def midi_create_queue(name, ppq, info=None, default=True):
    r'''Creates an ALSA queue.

    queue_ids are globally unique
    '''
    global Default_queue

    if name in Queues:
        print(f"midi_create_queue: queue name, {name}, already used")
        return
    queue = Client.create_queue(name, info)
        # name
        # info: QueueInfo
        #    queue_id: int
        #    name: str
        #    owner: int
        #    locked: bool
        #    flags: int
    print(f"{queue.queue_id=}")       # queue_ids are globally unique
    queue.ppq_setting = ppq
    Queues[name] = queue
    if default:
        Default_queue = queue
    return queue

    #help(Client.create_queue)
    #
    # name
    # info: QueueInfo: queue, name, owner, locked, flags

    #print(f"{Queue.control=}")
    #print(f"{Queue.get_info()=}")
    #print(f"{Queue.get_status()=}")
    #print(f"{Queue.get_tempo()=}")
    #print(f"{Queue.get_timer()=}")
    #print(f"{Queue.get_usage()=}")

    #print(dir(Queue))
    # 
    # control(EventType, value=0)     # sends queue control event
    # get_info
    # get_status
    # get_tempo
    # get_timer
    # get_usage
    # queue_id
    # set_info
    # set_tempo
    # set_timer
    # set_usage
    # start
    # stop

    # print(f"{dir(Queue.get_info())=}")
    #
    # flags
    # locked
    # name
    # owner
    # queue_id


def midi_create_input_port(name, caps=WRITE_PORT, type=DEFAULT_PORT_TYPE, connect_from=None):
    return midi_create_port(name, caps, type, connect_from=connect_from)

def midi_create_output_port(name, caps=READ_PORT, type=DEFAULT_PORT_TYPE,
                            default=True, clock_master=False, connect_to=None):
    return midi_create_port(name, caps, type, default=default, clock_master=clock_master,
                            connect_to=connect_to)

def midi_create_inout_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_master=False, connect_from=None, connect_to=None):
    return midi_create_port(name, caps, type, default=default, clock_master=clock_master,
                            connect_from=connect_from, connect_to=connect_to)

def midi_create_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE, default=True, clock_master=False,
                     connect_from=None, connect_to=None):
    r'''Returns port.
    '''
    global Default_port, Clock_master_port

    if name in Ports:
        print(f"midi_create_port: port name, {name}, already used -- ignored")
        return

    port = Client.create_port(name, caps, type)
                            # name,
                            # caps: PortCaps (READ, WRITE, DUPLEX, SUBS_READ, SUBS_WRITE, NO_EXPORT)
                            #  also: READ_PORT, WRITE_PORT, RW_PORT (these include SUBS)
                            # type: PortType (MIDI_GENERIC, SYNTH, SOFTWARE, PORT, APPLICATION)

                            # This isn't necessary.
                            # Causes ALSA to add timestamp to event using queue as time source.
                            # , timestamping=True, timestamp_real=False, timestamp_queue=Queue
    print(f"{port.port_id=}")       # port_ids are only unique to the client
    Ports[name] = port
    if default:
        Default_port = port
    if clock_master:
        Clock_master_port = port
        if Clock_master_tag is not None and Ppq is not None:
            midi_send_ppq()
    if connect_from:
        for addr in connect_from.split(','):
            address = midi_address(addr.strip())
            if address is not None:
                try:
                    port.connect_from(address)
                except ALSAError:
                    continue
                break
        else:
            print(f"port({name}): all connect_from addresses failed")
    if connect_to:
        for addr in connect_to.split(','):
            address = midi_address(addr.strip())
            if address is not None:
                try:
                    port.connect_to(address)
                except ALSAError:
                    continue
                break
        else:
            print(f"port({name}): all connect_to addresses failed")
    return port

    #help(Client.create_port)
    # type: PortType
    # timestamping: bool
    # timestamp_real: bool
    # timestamp_queue: queue

    # print(dir(Port))
    #
    # client
    # client_id
    # close
    # connect_from
    # connect_to
    # disconnect_from
    # disconnect_to
    # get_info
    # list_subscribers
    # port_id
    # set_info

    # print(f"{dir(Port.get_info())=}")
    #
    # capability (PortCap)
    # client_id
    # client_name
    # midi_channels
    # midi_voices
    # name
    # port_id
    # port_specified
    # read_use
    # synth_voices
    # timestamp_queue_id
    # timestamp_real
    # timestamping
    # type
    # write_use

def midi_address(address):
    r'''Returns an Address, or None if address has an unknown name.

    address may be: an Address, Port, PortInfo, "client", "client:port" where client
    and/or port may be a name or number.
    '''
    if isinstance(address, Address):
        return address
    if isinstance(address, (Port, PortInfo)):
        return Address(address)
    if ':' in address:
        client, port = address.split(':')
    else:
        client = address
        port = '0'
    if client.isdigit():
        client = int(client)
    else:
        client_info = None
        while True:
            client_info = Client.query_next_client(client_info)
            if client_info is None:
                print(f"midi_address({address}): client {client} not found")
                return None
            if client_info.name == client:
                client = client_info.client_id
                break
    if port.isdigit():
        port = int(port)
    else:
        port_info = None
        while True:
            port_info = Client.query_next_port(client, port_info)
            if port_info is None:
                print(f"midi_address({address}): port {port} not found")
                return None
            if port_info.name == port:
                port = port_info.port_id
                break
    return Address(client, port)

def midi_process_fn(fn):
    global Process_fn
    Process_fn = fn

# Works with queue specified here, but not in event.  Queue_id set in event by ALSA.
# Also works with queue specified in event, but not here.  Seems to be interchangable...
#
# Invalid queue_id in either location raises ALSAError: Invalid argument
#
def midi_send_event(event, queue=None, port=None, dest=None, drain_output=False):
    r'''queue, port and dest may be names.

    Returns nothing.
    '''
    if isinstance(queue, str):
        if queue not in Queues:
            print(f"midi_send_event: unknown queue {queue!r} -- not sent!")
            return
        else:
            queue = Queues[queue]
    elif queue is None and event.tick and Default_queue:
        queue = Default_queue
    if isinstance(port, str):
        if port not in Ports:
            print(f"midi_send_event: unknown port {port!r} -- not sent!")
            return
        else:
            port = Ports[port]
    elif port is None and Default_port:
        port = Default_port
    if isinstance(dest, str):
        if dest not in Ports:
            print(f"midi_send_event: unknown port {port!r} -- not sent!")
            return
        else:
            port = Ports[port]
    Client.event_output(event, queue=queue, port=port, dest=dest)
    if drain_output:
        midi_drain_output()

def midi_drain_output():
    Client.drain_output()

def midi_pause(secs=None):
    global Sel
    if Sel is None:
        Sel = selectors.DefaultSelector()
        Sel.register(Client._fd, selectors.EVENT_READ, Process_fn)

    drain_output = False
    for sk, sel_event in Sel.select(secs):
        num_pending = Client.event_input_pending(True)
        for i in range(1, num_pending + 1):
            #print("reading", i)
            event = client.event_input()
            if sk.data(event):
                drain_output = True
    if drain_output:
        Client.drain_output()

def midi_process_clock(event):
    r'''Processes: Clock, Start, Stop, Continue, tempo, time_signature, spp

    Returns True if the event was one of these, False otherwise.

    No drain_output required on any of these.
    '''
    global Bpm, Tick_interval, Time_signature
    global Spp, Queue_running, Spp_countdown, Clocks, Last_clock_time

    if event.type == EventType.CLOCK:
        if Queue_running:
            Spp_countdown -= 1
            if Spp_countdown <= 0:
                Spp += 1
                Spp_countdown = Ppq // 6
            Clocks += 1
            Last_clock_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        return True
    if event.type == EventType.START:
        Queue_running = True
        Spp = 0
        Spp_countdown = Ppq // 6
        Clocks = 0
        Last_clock_time = None
        return True
    if event.type == EventType.STOP:
        # we want to add time.CONTINUE = time.STOP to Last_clock_time
        Queue_running = False
        if Last_clock_time is not None:
            Last_clock_time -= time.clock_gettime(time.CLOCK_MONOTONIC)
        return True
    if event.type == EventType.CONTINUE:
        Queue_running = True
        if Last_clock_time is not None:
            Last_clock_time += time.clock_gettime(time.CLOCK_MONOTONIC)
        return True
    if event.type == EventType.SONGPOS:
        Spp = event.value
        Spp_countdown = Ppq // 6
        return True
    if event.type == EventType.SYSTEM:
        if event.event == Tempo_status:
            Bpm = data_to_bpm(event.value)
            Tick_interval = 60.0 / (Bpm * Ppq)  # in secs
            return True
        if event.event == Time_sig_status:
            Time_signature = data_to_time_sig(event.value)
            return True
    return False

def midi_set_tag(tag):
    global Clock_master_tag
    Clock_master_tag = tag
    if Clock_master_port is not None and Ppq is not None:
        midi_send_ppq()

def midi_set_ppq(ppq):
    r'''Sends message to clock-master.
    '''
    global Ppq, Ppc
    Ppq = ppq
    Ppc = ppq // 24  # pulses per CLOCK pulse
    if Clock_master_port is not None and Clock_master_tag is not None:
        midi_send_ppq()

def midi_send_ppq():
    Client.event_output(
      ControlChangeEvent(Clock_master_channel, Clock_master_CC_ppq, ppq_to_data(Ppq),
                         tag=Clock_master_tag),
      port=Clock_master_port)
    Client.drain_output()

def midi_close_queue():
    Client.event_output(
      ControlChangeEvent(Clock_master_channel, Clock_master_CC_close_queue, Clock_master_tag,
                         tag=Clock_master_tag),
      port=Clock_master_port)
    Client.drain_output()

def midi_set_tempo(bpm):
    print(f"midi_set_tempo: {bpm=}")
    if Clock_master_port:
        Client.event_output(SystemEvent(Tempo_status, bpm_to_data(bpm), tag=Clock_master_tag),
                            port=Clock_master_port)
        Client.drain_output()
    else:
        for queue in Queues.values():
            queue.set_tempo(bpm=bpm, ppq=queue.ppq_setting)

def midi_set_time_signature(beats, beat_type):
    r'''Sends message to clock-master
    '''
    global Time_signature
    if Clock_master_port:
        Client.event_output(SystemEvent(Time_sig_status, time_sig_to_data(beats, beat_type),
                                        tag=Clock_master_tag),
                            port=Clock_master_port)
        Client.drain_output()
    else:
        Time_signature = (beats, beat_type)

def midi_start():
    print("midi_start")
    if Clock_master_port:
        Client.event_output(StartEvent(), port=Clock_master_port)
    else:
        for queue in Queues.values():
            queue.start()
    Client.drain_output()

def midi_stop(tick=None):
    print("midi_stop")
    if Clock_master_port:
        Client.event_output(StopEvent(tag=Clock_master_tag, relative=False, tick=tick),
                            port=Clock_master_port)
    else:
        if tick:
            print(f"midi_stop: tick ignored, effective immediately!")
        for queue in Queues.values():
            queue.stop()
    Client.drain_output()

def midi_continue():
    print("midi_continue")
    if Clock_master_port:
        Client.event_output(ContinueEvent(tag=Clock_master_tag), port=Clock_master_port)
    else:
        for queue in Queues.values():
            queue.continue_()
    Client.drain_output()

def midi_spp(song_position, tick=None):
    print("midi_song_position")
    if Clock_master_port:
        Client.event_output(SongPositionPointerEvent(0, song_position, tag=Clock_master_tag,
                                                     relative=False, tick=tick),
                            port=Clock_master_port)
        Client.drain_output()
    else:
        Spp = song_position
        Spp_countdown = Ppq // 6

def midi_tick_time():
    r'''ticks since start.

    These are paused at "stop" and resumed at "continue".

    Based on set_ppq and set_tempo since last Clock received.
    '''
    if Clock_master_port:
        delta_t = time.clock_gettime(time.CLOCK_MONOTONIC) - Last_clock_time
        return Ppc * Clocks + int(round(delta_t / Tick_interval))
    if Default_queue is not None:
        return Default_queue.get_status().tick_time
    print(f"midi_tick_time: no default queue")
    return 0

def midi_close():
    if Clock_master_tag is not None and Ppq is not None and Clock_master_port is not None:
        midi_close_queue()
    for port in Ports.values():
        port.close()
    for queue in Queues.values():
        queue.close()
    if Client is not None:
        Client.close()

