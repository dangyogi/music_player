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
    midi_queue_status(queue_name|queue=None) -> QueueStatus
    midi_queue_time(queue_name|queue=None) -> current queue tick value
    trace(*msgs) # adds truncated time to front

    Event_type_names[event.type] -> name
    Port_names[port.port_id] -> name

Initialization:

    midi_set_verbose(verbose=True) -> None
    midi_raise_SPPException(raise_spp=True) -> None
    midi_init(client_name, streams=DUPLEX) -> client
    midi_create_queue(name, ppq, info=None, default=True) -> Queue (only used by clock_master)
    midi_create_input_port(name, caps=WRITE_PORT, type=DEFAULT_PORT_TYPE, connect_from=None)
      -> Port (generally not needed)
    midi_create_output_port(name, caps=READ_PORT, type=DEFAULT_PORT_TYPE,
                            default=True, clock_master=False, connect_to=None)
      -> Port (generally not needed)
    midi_create_inout_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_master=False, connect_from=None, connect_to=None)
      -> Port (generally not needed)
    midi_create_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE, default=True, clock_master=False,
                     connect_from=None, connect_to=None):
      -> Port (generally not needed)
    midi_connect_to(port, addr) -> None
    midi_connect_from(port, addr) -> None
    midi_list_ports() -> List[PortInfo]
    midi_get_client_info(client_id=None) -> ClientInfo (.name and .client_id useful)
    midi_get_port_info(addr) -> PortInfo (.name, .client_id, .port_id and .capability useful)
    midi_get_address(addr) -> "client_name(client_id):port_name(port_id)", addr may be PortInfo
    midi_address(address) -> Address or None, client_name:port_name may be used
    midi_process_fn(fn) -> None, fn(event) -> bool to drain_output
    midi_close() -> None, closes tag with clock-master, all ports, queues and client

I/O:
    midi_send_event(event, queue=None, port=None, dest=None, no_defaults=False, drain_output=False)
      -> None
    midi_drain_output() -> None
    midi_pause(secs=None, post_fns=None) -> None, reads and processes events while paused.
                                            post_fns should be an empty list that will loaded by
                                            the fn registered with midi_process_fn with fns to process
                                            after all events have been received and drain_output has
                                            been called.  These are called with no arguments and must
                                            return True if drain_output needs to be called (again).
    midi_process_clock(event) -> True if event was a clock event
                                 (Clock, Start, Stop, Continue, tempo, time_signature, spp)
                                 No drain_output required on any of these (i.e., if True returned).
                                 Register midi_process_clock_fn rather than midi_process_clock if
                                 that's all you need.
                                 Raises SPPException if midi_raise_SPPException has been called.
    midi_process_clock_fn(event) -> can be passed to midi_process_fn if no other events require
                                    processing.

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

Verbose = False
Raise_SPPException = False
Spp = None   # set by midi_process_clock, reset by midi_pause if Raise_SPPException is True.
Tempo_status = 0xF4
Time_sig_status = 0xF5

# Event_type_names[event.type] -> name
Event_type_names = {e_value.value: e_value.name for e_value in EventType}

# Port_names[port.port_id] -> name
Port_names = {}

Clock_master_channel = 15
Clock_master_CC_ppq = 44          # ppq_data = ppq // 24
Clock_master_CC_close_queue = 45  # tag
Clock_master_tag = None
Pulses_per_clock = 20

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
Clocks = 0             # CLOCKs received since last START at 24 per quarter note (24 ppq)
Last_clock_time = None
Time_signature = None  # (beats, beat_type)

# bpm = 30 * 1.01506^data
# bpm = 30 * exp(Log_1_01506*data)
# data = log(bpm / 30) / log(1.01506)
# data = log(bpm / 30) / Log_1_01506
Log_1_01506 = math.log(1.01506)


class SppException(Exception):
    def __init__(self, spp):
        self.spp = spp


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

def midi_queue_status(queue=None):
    if isinstance(queue, str):
        if queue not in Queues:
            print(f"midi_queue_status got unknown queue, {queue!r}")
            return None
        queue = Queues[queue]
    if queue is None:
        assert Default_queue is not None, f"midi_queue_status: Default_queue is not set"
        queue = Default_queue
    return queue.get_status()

def midi_queue_time(queue=None):
    return midi_queue_status(queue).tick_time

def trace(*msgs):
    r'''adds truncated time to front
    '''
    print(f"{round(time.clock_gettime(time.CLOCK_MONOTONIC) % 10, 5):<07}", *msgs)

def midi_set_verbose(verbose=True):
    global Verbose
    Verbose = verbose

def midi_raise_SPPException(raise_spp=True):
    global Raise_SPPException
    Raise_SPPException = raise_spp

def midi_init(client_name, streams=StreamOpenType.DUPLEX):
    r'''Creates Client.  All ports for the client share the same input and output memory pools.
    '''
    global Client
    global Clock_master_tag
    global Sel
    global Ports, Port_names, Default_port, Clock_master_port
    global Queues, Default_queue, Queue_running
    global Process_fn

    global Bpm, Ppq, Ppc, Tick_interval, Time_signature
    global Spp, Spp_countdown, Clocks, Last_clock_time

    Client = None
    Clock_master_tag = None
    Sel = None

    # Don't create new dicts because importers only have access to the original dicts
    Ports.clear()
    Port_names.clear()
    Default_port = None
    Clock_master_port = None
    Queues.clear()
    Default_queue = None
    Queue_running = False

    Process_fn = None      # Process_fn(event) -> bool to drain_output

    Bpm = None             # Beats (quarter notes) per minute
    Ppq = None             # ppq setting on ALSA queue (usually maintained by clock-master)
    Ppc = None             # pulses per CLOCK pulse
    Tick_interval = None   # secs between ticks at Ppq * Bpm
    Time_signature = None  # (beats, beat_type)
    Spp = 0                # Song Position Pointer
    Spp_countdown = None   # CLOCKs left to next SPP increment
    Clocks = 0             # CLOCKs received since last START
    Last_clock_time = None

    Client = SequencerClient(client_name, streams=streams)
        # client_name,
        # streams (default StreamOpenType.DUPLEX -- also OUTPUT, INPUT), applies to sequencer
        # mode (default OpenMode.NONBLOCK -- or 0), applies to both read and write operations,
        #                                           must be NONBLOCK
        # sequencer_name (default "default"), special meaning to ALSA, usually want "default"
    if Verbose:
        trace(f"{Client.client_id=}")     # client_ids are globally unique
    return Client

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
    if Verbose:
        trace(f"Queue {name}(queue_id={queue.queue_id})")   # queue_ids are globally unique
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

def midi_connect_to(port, addr):
    r'''Returns True if successful.
    '''
    if isinstance(port, str):
        if port not in Ports:
            print("midi_connect_to: unknown port", port)
            return False
        port = Ports[port]
    address = midi_address(addr)
    if address is None:
        return False
    try:
        port.connect_to(address)
    except ALSAError:
        return False
    return True

def midi_connect_from(port, addr):
    r'''Returns True if successful.
    '''
    if isinstance(port, str):
        if port not in Ports:
            print("midi_connect_from: unknown port", port)
            return False
        port = Ports[port]
    address = midi_address(addr)
    if address is None:
        return False
    try:
        port.connect_from(address)
    except ALSAError:
        return False
    return True

def midi_list_ports():
    return Client.list_ports()

def midi_get_client_info(client_id=None):
    r'''Returns ALSA ClientInfo.
    '''
    if client_id is None:
        return Client.get_client_info()
    return Client.get_client_info(client_id)

def midi_get_port_info(addr):
    if isinstance(addr, PortInfo):
        return addr
    return Client.get_port_info(midi_address(addr))

def midi_get_address(addr):
    r'''Returns "client_name(client_id):port_name(port_id)"
    '''
    port_info = midi_get_port_info(addr)
    client_info = midi_get_client_info(port_info.client_id)
    return f"{client_info.name}({client_info.client_id}):{port_info.name}({port_info.port_id})"

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
    if Verbose:
        trace(f"Port {name}(port_id={port.port_id})")      # port_ids are only unique to the client
    Ports[name] = port
    Port_names[port.port_id] = name
    if default:
        Default_port = port
    if clock_master:
        Clock_master_port = port
        if Clock_master_tag is not None and Ppq is not None:
            midi_send_ppq()
    if connect_from:
        connections = 0
        for addr in connect_from:
            if midi_connect_from(port, addr):
                connections += 1
        if connections != len(connect_from):
            print(f"port({name}): {len(connect_from) - connections} connect_from addresses failed")
    if connect_to:
        connections = 0
        for addr in connect_to:
            if midi_connect_to(port, addr):
                connections += 1
        if connections != len(connect_to):
            print(f"port({name}): {len(connect_to) - connections} connect_to addresses failed")
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
    if not client:
        client = Client.client_id
    elif client.isdigit():
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
def midi_send_event(event, queue=None, port=None, dest=None, no_defaults=False, drain_output=False):
    r'''Calls Client.event_output unpacking arguments for it.

    Also calls Client.drain_output if drain_output is True.

    queue may be a Queue object, queue_id, or queue name.  Defaults to Default_queue if event.tick.
    port may be a Port object, port_id, or port name.  Defaults to Default_port.
    dest may be an Address, Port object, PortInfo, (client_id, port_id) or "client_name/id:port_name/id".

    Defaults may be disabled by passing no_defaults=True.

    Returns nothing.
    '''
    if isinstance(queue, str):
        if queue not in Queues:
            print(f"midi_send_event: unknown queue {queue!r} -- not sent!")
            return
        else:
            queue = Queues[queue]
    elif queue is None and event.tick and Default_queue and not no_defaults:
        queue = Default_queue
    if isinstance(port, str):
        if port not in Ports:
            print(f"midi_send_event: unknown port {port!r} -- not sent!")
            return
        else:
            port = Ports[port]
    elif port is None and Default_port and not no_defaults:
        port = Default_port
    if isinstance(dest, str):
        addr = midi_address(dest)
        if addr is None:
            print(f"midi_send_event: unknown dest {dest!r} -- not sent!")
            return
        else:
            dest = addr
    Client.event_output(event, queue=queue, port=port, dest=dest)
    if drain_output:
        midi_drain_output()

def midi_drain_output():
    Client.drain_output()

def midi_pause(secs=None, post_fns=None):
    r'''Pause secs waiting for events.

    Calls the process_fn registered with midi_process_fn for each event received. 

    secs may be None (pause as long as it takes to receive an event), 0 (don't pause at all, just do a
    quick check), or a (perhaps fractional) number of secs to wait.  If a number is given, the program
    will be suspended for that many seconds (rather than returning when the first event is received).

    post_fns is a list of functions to call after drain_output is called.  These are called with
    no arguments and must return True if drain_output needs to be called (again).  The caller must
    arrange for this list to also be available to the process_fn registered with midi_process_fn,
    so that it can append functions to it.  When secs is a number, this list is cleared between
    each batch of events received.  In that case, the midi_pause caller will see an empty list
    after the call to midi_pause and not see the functions added by the process_fn.
    '''
    global Sel
    if Sel is None:
        Sel = selectors.DefaultSelector()
        Sel.register(Client._fd, selectors.EVENT_READ, Process_fn)

    def wait_once(secs):
        global Spp
        drain_output = False
        for sk, sel_event in Sel.select(secs):
            num_pending = Client.event_input_pending(True)
            for i in range(1, num_pending + 1):
                #print("reading", i)
                event = Client.event_input()
                if sk.data(event):
                    drain_output = True
        if drain_output:
            Client.drain_output()
        if post_fns:
            if Verbose:
                trace("midi_pause: running post_fns")
            drain_output = False
            for fn in post_fns:
                if fn():
                    drain_output = True
            if drain_output:
                Client.drain_output()
        if Spp and Raise_SPPException:
            spp = Spp
            Spp = None
            raise SppException(spp)

    if secs is None or secs == 0:
        wait_once(secs)
    else:
        end = time.clock_gettime(time.CLOCK_MONOTONIC) + secs
        while secs > 0:
            wait_once(secs)
            secs = end - time.clock_gettime(time.CLOCK_MONOTONIC)
            if post_fns:
                post_fns.clear()

def process_clock(event):
    global Spp, Queue_running, Spp_countdown, Clocks, Last_clock_time

    if Queue_running:
        Spp_countdown -= 1
        if Spp_countdown <= 0:
            Spp += 1
            Spp_countdown = Ppq // 6
        Clocks = event.tick // Pulses_per_clock
        Last_clock_time = time.clock_gettime(time.CLOCK_MONOTONIC)
        if Verbose and Clocks < 10:
            trace(f"process_clock: event={event}, source={event.source}, tag={event.tag}, "
                  f"tick={event.tick}, now={Last_clock_time}")
    return True

def process_start(event):
    global Spp, Queue_running, Spp_countdown, Clocks, Last_clock_time

    Queue_running = True
    Spp = 0
    Spp_countdown = Ppq // 6
    Clocks = 0
    Last_clock_time = None
    if Verbose:
        trace("process_start: Last_clock_time=None")
    return True

def process_stop(event):
    # we want to add time.CONTINUE = time.STOP to Last_clock_time
    global Queue_running, Last_clock_time

    Queue_running = False
    if Last_clock_time is not None:
        Last_clock_time -= time.clock_gettime(time.CLOCK_MONOTONIC)
        if Verbose:
            trace(f"process_stop: Last_clock_time={round(Last_clock_time, 5)}")
    return True

def process_continue(event):
    global Queue_running, Last_clock_time

    Queue_running = True
    if Last_clock_time is not None:
        Last_clock_time += time.clock_gettime(time.CLOCK_MONOTONIC)
        if Verbose:
            trace(f"process_continue: Last_clock_time={round(Last_clock_time, 5)}")
    return True

def process_songpos(event):
    global Spp, Spp_countdown

    Spp = event.value
    Spp_countdown = Ppq // 6
    return True

def process_system(event):
    global Bpm, Tick_interval, Time_signature

    if event.event == Tempo_status:
        Bpm = data_to_bpm(event.result)
        Tick_interval = 60.0 / (Bpm * Ppq)  # in secs
        if Verbose:
            trace(f"Got tempo message, {Bpm=}, {Ppq=}, Tick_interval={round(Tick_interval, 5)}")
        return True
    if event.event == Time_sig_status:
        Time_signature = data_to_time_sig(event.result)
        return True
    return False

Event_fns = {
    EventType.CLOCK: process_clock,
    EventType.START: process_start,
    EventType.STOP: process_stop,
    EventType.CONTINUE: process_continue,
    EventType.SONGPOS: process_songpos,
    EventType.SYSTEM: process_system,
}

def midi_process_clock(event):
    r'''Processes: Clock, Start, Stop, Continue, tempo, time_signature, spp

    Returns True if the event was handled, False otherwise.

    No drain_output required on any of these.
    '''
    if event.type in Event_fns:
        return Event_fns[event.type](event)
    return False

def midi_process_clock_fn(event):
    r'''Calls midi_process_clock, and returns False (no drain_output required).
    '''
    midi_process_clock(event)
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
    if Verbose:
        trace(f"midi_set_ppq: {Ppq=}, {Ppc=}")
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
    if Verbose:
        trace(f"midi_set_tempo: {bpm=}")
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
    if Verbose:
        trace("midi_start")
    if Clock_master_port:
        Client.event_output(StartEvent(), port=Clock_master_port)
    else:
        for queue in Queues.values():
            queue.start()
    Client.drain_output()

def midi_stop(tick=None):
    if Verbose:
        trace("midi_stop")
    if Clock_master_port:
        Client.event_output(StopEvent(tag=Clock_master_tag, tick=tick), port=Clock_master_port)
    else:
        if tick:
            print(f"midi_stop: tick ignored, effective immediately!")
        for queue in Queues.values():
            queue.stop()
    Client.drain_output()

def midi_continue():
    if Verbose:
        trace("midi_continue")
    if Clock_master_port:
        Client.event_output(ContinueEvent(tag=Clock_master_tag), port=Clock_master_port)
    else:
        for queue in Queues.values():
            queue.continue_()
    Client.drain_output()

def midi_spp(song_position, tick=None):
    if Verbose:
        trace("midi_song_position")
    if Clock_master_port:
        Client.event_output(SongPositionPointerEvent(0, song_position, tag=Clock_master_tag, tick=tick),
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
        if Last_clock_time is None:
            return 0
        if Queue_running:
            delta_t = time.clock_gettime(time.CLOCK_MONOTONIC) - Last_clock_time
        else:
            delta_t = -Last_clock_time
        ans = Ppc * Clocks + int(round(delta_t / Tick_interval))
        if Verbose:
            trace(f"midi_tick_time: {Clocks=}, {Ppc=}, delta_t={round(delta_t, 5)}, "
                  f"Tick_interval={round(Tick_interval, 5)}, {ans=}")
        return ans
    if Default_queue is not None:
        return Default_queue.get_status().tick_time
    print(f"midi_tick_time: no default queue")
    return 0

def midi_close():
    if Clock_master_tag is not None and Ppq is not None and Clock_master_port is not None:
        midi_close_queue()
    if Sel is not None:
        Sel.close()
    for port in Ports.values():
        port.close()
    for queue in Queues.values():
        queue.close()
    if Client is not None:
        Client.close()

