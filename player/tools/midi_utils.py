# midi_utils.py

r'''Midi utils that deal with the alsa_midi library.

Timing:
    "tick" means queue ticks, as in event.tick.
    "clock" means standard MIDI CLOCK events, always 24 per quarter note.
            83.3 mSecs at 30 bpm, 12.5 mSecs at 200 bpm.
    "bpm" means "beats per minute", where "beat" means quarter note, regardless of time signature.
    "ppq" means "pulses per quarter note", where "pulse" means queue tick.
          Always multiple of clock (24).
    "spp" means "song position pointer".  This always updates once per 16th note,
                                          so 4 per quarter note; or 6 CLOCKS per spp.

    Time is standardized here as "clocks", which may be fractional, as it is in the musicxml
    parsing routines.

Utility:
    Log_1_01505 = math.log(1.01505) for bpm encoding

    data_to_bpm(data) -> bpm
    bpm_to_data(bpm) -> data byte for Tempo message (bpm is 30-200 as float)
    time_sig_to_data(beats, beat_type) -> data byte for Time_sig message
    data_to_time_sig(data) -> (beats, beat_type), e.g., (6, 8)
    ppq_to_data(ppq) -> data byte for ControlChangeEvent to clock-master
    data_to_ppq(data) -> ppq
    midi_queue_status(queue_name|queue=None) -> QueueStatus
    midi_queue_time(queue_name|queue=None) -> current raw queue tick value.
                                              doesn't update if queue is stopped
    to_ticks(clocks)  # returns an int (rounded)
    fraction(n, d)    # returns int if Fraction(n, d).denomintor == 1
    trace(*msgs)      # adds truncated time to front

    Event_type_names[event.type] -> name
    Port_names[port.port_id] -> name

Initialization:

    midi_set_verbose(verbose=True) -> None
    midi_init(client_name, streams=DUPLEX) -> client
    midi_create_queue(name, ppq, info=None, default=True) -> Queue
    midi_create_input_port(name, caps=WRITE_PORT, type=DEFAULT_PORT_TYPE, connect_from=None)
      -> Port (generally not needed)
    midi_create_output_port(name, caps=READ_PORT, type=DEFAULT_PORT_TYPE,
                            default=True, clock_port=False, connect_to=None)
      -> Port (generally not needed)
    midi_create_inout_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_port=False, connect_from=None, connect_to=None)
      -> Port (generally not needed)
    midi_create_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE, default=True, clock_port=False,
                     connect_from=None, connect_to=None):
      -> Port (generally not needed)
    midi_connect_to(port, addr) -> None
    midi_connect_from(port, addr) -> None
    midi_list_ports() -> List[PortInfo]
    midi_get_client_id() -> Client.client_id
    midi_get_client_info(client_id=None) -> ClientInfo (.name and .client_id useful)
    midi_get_port_info(addr) -> PortInfo (.name, .client_id, .port_id and .capability useful)
    midi_get_address(addr) -> "client_name(client_id):port_name(port_id)", addr may be PortInfo
    midi_address(address) -> Address or None, "client_name:port_name" or (client, port) may be used
    midi_process_fn(fn) -> None, must be called prior to first call to midi_pause.
                    fn(event) -> None, caller must call midi_drain_output
    midi_get_named_queue(name) -> Queue
    midi_close_queue(name) -> None
    midi_close() -> None, closes all ports, queues and client

I/O:
    midi_send_event(event, queue=None, port=None, dest=None, no_defaults=False, drain_output=False)
      -> None
    midi_drain_output() -> None, calls drain_output if needed.  Call periodically.
    midi_pause(secs=None, to_tick=None, post_fns=None) -> None,
        reads and processes events while paused.

        If to_tick is None, just does a select(secs) and returns when the first event(s) are received
        (after processing them).  So secs == 0 does a quick check, secs == None, waits forever, other
        secs waits up to that long for the first event(s).

        If to_tick is not None, the pause will end when the queue reaches that tick; even in the face
        of intervening tempo changes and queue stop/start/continues.  If the Queue is not running, it
        will only wait up to secs seconds for the Queue to start running.  Once the Queue is running,
        secs is ignored.

        post_fns should be an empty list that will loaded by the fn registered with midi_process_fn
        with fns to process after all events have been received and drain_output has been called.
        These are called with no arguments and return nothing.
    midi_process_clock(event) -> True if event was a clock event
                                 (Start, Stop, Continue, tempo, spp)
                                 Register midi_process_clock_fn rather than midi_process_clock if
                                 that's all you need.
                                 Caller must call midi_drain_output
    midi_process_clock_fn(event) -> can be passed to midi_process_fn if no other events require
                                    processing.

To timing and queues:

    midi_set_time_signature(beats, beat_type, port=None) -> None, caller must call midi_drain_output
        Sends Time Signature SystemEvent if port is set.
    midi_set_tempo(bpm) -> None, sets tempo on all queues, caller must call midi_drain_output
    midi_start() -> None, starts all queues, caller must call midi_drain_output
    midi_stop() -> Clocks_sent, stops all queues, caller must call midi_drain_output
    midi_continue() -> None, continues all queues, caller must call midi_drain_output
    midi_spp(position) -> None, updates Queue_sync_ticks, caller must call midi_drain_output
'''

import time
import math
import selectors
from fractions import Fraction

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
   SysExEvent,
)
from alsa_midi.client import StreamOpenType
from alsa_midi.port import DEFAULT_PORT_TYPE

SND_SEQ_QUEUE_DIRECT = alsa.SND_SEQ_QUEUE_DIRECT

# Midi beat clock commands:
#
#   tempo defaults to 120 bpm, here "beat" in bpm means quarter note
#
#   0xF8 - Clock; std 24 clocks (CLOCK messages) per quarter note
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
Tempo_status = 0xF4     # 244
Time_sig_status = 0xF5  # 245

# Event_type_names[event.type] -> name
Event_type_names = {e_value.value: e_value.name for e_value in EventType}

# Port_names[port.port_id] -> name
Port_names = {}

Sel = None
Client = None
Ports = {}
Default_port = None
Clock_port = None
Queues = {}
Default_queue = None
Process_fn = None      # Process_fn(event) -> None, caller must call midi_drain_output
Drain_needed = False   # set by all functions as needed

Clocks_per_quarter_note = 24
Ticks_per_clock = None # 80 gives 1 mSec at 30 bpm
Clocks_per_spp = Clocks_per_quarter_note // 4 # (16ths/qtr_note)
Clock_interval = None  # secs between clocks at bpm * Clocks_per_quarter_note
                       # 83.3 mSec at 30 bpm, 12.5 mSec at 200 bpm
Queue_sync_ticks = 0   # ticks to add to queue ticks to sync with last SPP
Do_start = False       # continue will do start, rather than continue, to clear the queue
Clock_advance = 4      # max CLOCK events to queue up.  333 mSec at 30 bpm, 50 mSec at 200 bpm
Clocks_sent = 0        # since START
Next_clock_to_queue = None
Furthest_behind = None
Queue_running = False

Time_signature = None  # (beats, beat_type)

# bpm = 30 * 1.01505^data
# bpm = 30 * exp(Log_1_01505*data)
# data = log(bpm / 30) / log(1.01505)
# data = log(bpm / 30) / Log_1_01505
Log_1_01505 = math.log(1.01505)
Tempo_m = (200 - 30) / 127


class WakeUpException(Exception):
    pass


def data_to_bpm(data):
    r'''result bpm is rounded to a sensible number of decimals.
    '''
    return round(Tempo_m * data + 30)
   #  FIX: use exponential scale fn?
   #raw = 30 * math.exp(Log_1_01505*data)
   #if raw >= 67:
   #    return round(raw)
   #return round(raw, 1)

def bpm_to_data(bpm):
    r'''Can encode bpm between 30 and 200 inclusive.
    '''
    return round((bpm - 30) / Tempo_m)
   #return round(math.log(bpm / 30) / Log_1_01505)

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
    r'''Returns fractional clocks.
    '''
    if queue is None:
        queue = Default_queue
    elif isinstance(queue, str):
        queue = Queues[queue]
    return fraction(midi_queue_status(queue).tick_time + Queue_sync_ticks, Ticks_per_clock)

def to_ticks(clocks):
    r'''Returns an int.
    '''
    return round(clocks * Ticks_per_clock - Queue_sync_ticks)

def fraction(n, d):
    ans = Fraction(n, d)
    if ans.denominator == 1:
        return ans.numerator
    return ans

def trace(*msgs):
    r'''adds truncated time to front
    '''
    print(f"{round(time.clock_gettime(time.CLOCK_MONOTONIC) % 10, 5):<07}", *msgs)

def midi_set_verbose(verbose=True):
    global Verbose
    Verbose = verbose
    if Verbose:
        trace(f"midi_set_verbose({verbose=})")

def midi_init(client_name, streams=StreamOpenType.DUPLEX):
    r'''Creates Client.  All ports for the client share the same input and output memory pools.
    '''
    global Client
    global Sel
    global Ports, Port_names, Default_port, Clock_port
    global Queues, Default_queue, Queue_running
    global Process_fn

    global Clock_interval, Time_signature

    Client = None
    Sel = None

    # Don't create new dicts because importers only have access to the original dicts
    Ports.clear()
    Port_names.clear()
    Default_port = None
    Clock_port = None
    Queues.clear()
    Default_queue = None
    Queue_running = False

    Process_fn = None      # Process_fn(event) -> None, called must call midi_drain_output

    Clock_interval = None  # secs between ticks at bpm * Clocks_per_quarter_note
    Time_signature = None  # (beats, beat_type)

    Client = SequencerClient(client_name, streams=streams)
        # client_name,
        # streams (default StreamOpenType.DUPLEX -- also OUTPUT, INPUT), applies to sequencer
        # mode (default OpenMode.NONBLOCK -- or 0), applies to both read and write operations,
        #                                           must be NONBLOCK
        # sequencer_name (default "default"), special meaning to ALSA, usually want "default"
    if Verbose:
        trace(f"{Client.client_id=}")     # client_ids are globally unique
    return Client

def midi_create_queue(name, ppq, info=None, default=True):
    r'''Creates an ALSA queue.

    queue_ids are globally unique
    '''
    global Default_queue, Ticks_per_clock

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
        assert ppq % Clocks_per_quarter_note == 0, \
               f"midi_create_queue({name=}, {ppq=}): ppq must be multiple of {Clocks_per_quarter_note}"
        Ticks_per_clock = ppq // Clocks_per_quarter_note
        if Verbose:
            trace(f"midi_create_queue({name}, {ppq}): {Ticks_per_clock=}")
    return queue

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

def midi_get_client_id():
    return Client.client_id

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
                            default=True, clock_port=False, connect_to=None):
    return midi_create_port(name, caps, type, default=default, clock_port=clock_port,
                            connect_to=connect_to)

def midi_create_inout_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE,
                           default=True, clock_port=False, connect_from=None, connect_to=None):
    return midi_create_port(name, caps, type, default=default, clock_port=False,
                            connect_from=connect_from, connect_to=connect_to)

def midi_create_port(name, caps=RW_PORT, type=DEFAULT_PORT_TYPE, default=True, clock_port=False,
                     connect_from=None, connect_to=None):
    r'''Returns port.
    '''
    global Default_port, Clock_port

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
    if clock_port:
        Clock_port = port
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

def midi_address(address):
    r'''Returns an Address, or None if address has an unknown name.

    address may be: an Address, Port, PortInfo, "client", "client:port", or (client,) or
    (client, port) where client and/or port may be a name or number.  An omitted client (or "")
    is taken as this app's client_id.  An omitted port (or "") is taken as 0.

    Client and port names only have to be unique prefixes of the actual client/port names.
    '''
    if isinstance(address, Address):
        return address
    if isinstance(address, (Port, PortInfo)):
        return Address(address)
    if isinstance(address, (tuple, list)):
        if len(address) == 1:
            client = address[0]
            port = 0
        else:
            client, port = address
    elif ':' in address:
        client, port = address.split(':')
    else:
        client = address
        port = 0
    if client == "":
        client = Client.client_id
    elif isinstance(client, int) or client.isdigit():
        client = int(client)
    else:
        client_info = None
        client_id = None
        while True:
            client_info = Client.query_next_client(client_info)
            if client_info is None:
                if client_id is None:
                    print(f"midi_address({address}): client {client} not found")
                    return None
                break
            if client_info.name.startswith(client):
                if client_id is not None:
                    print(f"midi_address: {client=} is not unique")
                client_id = client_info.client_id
        client = client_id
    if port == "":
        port = 0
    if isinstance(port, int) or port.isdigit():
        port = int(port)
    else:
        port_info = None
        port_id = None
        while True:
            port_info = Client.query_next_port(client, port_info)
            if port_info is None:
                if port_id is None:
                    print(f"midi_address({address}): port {port} not found")
                    return None
                break
            if port_info.name.startswith(port):
                if port_id is not None:
                    print(f"midi_address: {port=} is not unique")
                port_id = port_info.port_id
        port = port_id
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
    global Drain_needed

    if isinstance(queue, str):
        if queue not in Queues:
            print(f"midi_send_event: unknown queue {queue!r} -- not sent!")
            return
        else:
            queue = Queues[queue]
    elif queue is None and event.tick and Default_queue is not None and not no_defaults:
        queue = Default_queue
    if isinstance(port, str):
        if port not in Ports:
            print(f"midi_send_event: unknown port {port!r} -- not sent!")
            return
        else:
            port = Ports[port]
    elif port is None and Default_port is not None and not no_defaults:
        port = Default_port
    if dest is not None:
        addr = midi_address(dest)
        if addr is None:
            print(f"midi_send_event: unknown dest {dest!r} -- not sent!")
            return
        else:
            dest = addr
    Client.event_output(event, queue=queue, port=port, dest=dest)
    Drain_needed = True  # needed to trigger midi_drain_output
    if drain_output:
        midi_drain_output()

def midi_drain_output(force=False):
    global Drain_needed
    if Drain_needed or force:
        if Verbose:
            trace(f"midi_drain_output({force=}): {Drain_needed=}, calling drain_output")
        Client.drain_output()
        Drain_needed = False

def midi_pause(secs=None, to_clock=None, post_fns=None):
    r'''Pause secs or to_clock, whichever occurs first, waiting for events.

    Calls the process_fn registered with midi_process_fn for each event received. 

    If to_clock is None, just does a select(secs) and returns when the first event(s) are received
    (after processing them).  So secs == 0 does a quick check, secs == None, waits forever, other secs
    waits up to that long for the first event(s).

    If to_clock is not None, the pause will end when the queue reaches to_clock; even in the face of
    intervening tempo changes and queue stop/start/continues.  If the Queue is not running, it will
    only wait up to secs seconds for the Queue to start runing.  Once the Queue is running, secs is
    ignored.

    post_fns is a list of functions to call after drain_output is called.  These are called with
    no arguments and return nothing.  The caller must arrange for this list to also be available
    to the process_fn registered with midi_process_fn, so that it can append functions to it.
    This list is cleared between each batch of events received so the midi_pause caller will
    always see an empty list after the call to midi_pause (and not see the functions added by
    the process_fn).
    '''
    global Sel
    if Sel is None:
        Sel = selectors.DefaultSelector()
        Sel.register(Client._fd, selectors.EVENT_READ, Process_fn)

    if Verbose:
        trace(f"midi_pause({secs=}, {to_clock=}): {Next_clock_to_queue=}")
        if Client.event_output_pending():
            trace(f"midi_pause: output_pending on entry pending={Client.event_output_pending()}")

    if secs is not None:
        next_secs = secs
        end = time.clock_gettime(time.CLOCK_MONOTONIC) + secs

    def wait_once(wait_secs):
        r'''Wait up to wait_secs for one (set of) event(s).  wait_secs is interpreted by Sel.select.

            - call midi_drain_output before each select call.
            - send clock events as needed
            - Process all events received
            - run (and clear) post_fns
            - return (nothing)

        wait_secs can be None or 0.
        '''
        global Next_clock_to_queue, Furthest_behind, Clocks_sent
        nonlocal secs, end
        if Verbose:
            trace(f"wait_once({wait_secs=})")
        exc = None

        if Queue_running and Clock_port is not None:
            # generate CLOCKs
            now = midi_queue_time()
            clocks_to_next_clock = Next_clock_to_queue - now
            if clocks_to_next_clock < 0 and Furthest_behind is None \
               or Furthest_behind is not None and clocks_to_next_clock < Furthest_behind:
                Furthest_behind = clocks_to_next_clock
                trace(f"{Furthest_behind=} now clocks")
            if clocks_to_next_clock < 1:
                # queue up another Clock_advance CLOCK events.
                for clock in range(Next_clock_to_queue, Next_clock_to_queue + Clock_advance): 
                    midi_send_event(ClockEvent(tick=to_ticks(clock)), port=Clock_port)
                    Clocks_sent += 1
                Next_clock_to_queue += Clock_advance
            wait_secs2 = (Next_clock_to_queue - now - 1) * Clock_interval
            if wait_secs is None or wait_secs2 < wait_secs:
                wait_secs = wait_secs2

        midi_drain_output()

        # There is only one registered fileobj, so only ever 1 returned event here...
        for sk, sel_event in Sel.select(wait_secs):
            # This next loop handles multiple MIDI events arriving at the same time.
            num_pending = Client.event_input_pending(True)
            for i in range(1, num_pending + 1):
                #trace("reading", i)
                event = Client.event_input()
                pre_pending = Client.event_output_pending()
                try:
                    sk.data(event)  # Process_fn
                    post_pending = Client.event_output_pending()
                    if Drain_needed:
                        if post_pending == pre_pending:
                            trace(f"wait_once: Drain needed, but nothing new buffered")
                    else: # Drain not needed
                        if post_pending > pre_pending:
                            trace(f"wait_once: Drain not needed, but something was buffered")
                except WakeUpException as e:
                    if Verbose:
                        trace(f"wait_once: caught WakeUpException {e=}")
                    exc = e
                    # Continue to finish processing all pending MIDI events.
                    # Then re-raise exc when done.

        midi_drain_output()
        pending = Client.event_output_pending()
        if pending:
            trace(f"wait_once: {pending=} after midi_drain_output()")
        if post_fns:
            if Verbose:
                trace("wait_once: running post_fns")
            for fn in post_fns:
                fn()
            post_fns.clear()
            midi_drain_output()
        if exc is not None:
            if Verbose:
                trace(f"wait_once: raising {exc=}")
            raise exc
        if Verbose:
            trace(f"wait_once({wait_secs=}) exiting")

    if to_clock is None and (secs is None or secs == 0):
        if Verbose:
            trace(f"to_clock is None, {secs=}, doing one call to wait_once({secs})")
        wait_once(secs)
    else:  # to_clock is not None or (secs is not None and secs != 0)
        def tick_override():
            # only called when to_tick is not None
            if secs is None:  # to_clock is not None
                while not Queue_running:
                    if Verbose:
                        trace(f"tick_override: queue not running, doing wait_once(None)")
                    wait_once(None)
            if Queue_running:
                # secs now ignored
                clocks_remaining = to_clock - midi_queue_time()
                remaining_secs = clocks_remaining * Clock_interval
                #if Verbose:
                #    trace(f"tick_override: {ticks_remaining=}, {remaining_secs=}")
                return remaining_secs
            return next_secs
        if to_clock is not None:
            next_secs = tick_override()
        while next_secs > 0:
            wait_once(next_secs)
            if secs is not None:  # to_clock is not None or secs != 0
                next_secs = end - time.clock_gettime(time.CLOCK_MONOTONIC)
            if to_clock is not None:
                next_secs = tick_override()
    if Verbose:
        trace(f"midi_pause: exiting: {to_clock=}, {midi_queue_time()=}, {Next_clock_to_queue=}")

def process_start(event):
    r'''Returns True if event processed.
    '''
    midi_start()
    return True

def process_stop(event):
    r'''Returns True if event processed.
    '''
    midi_stop()
    return True

def process_continue(event):
    r'''Returns True if event processed.
    '''
    midi_continue()
    return True

def process_songpos(event):
    r'''This is only allowed while stopped.

    Returns True if event processed.
    '''
    midi_spp(event.value)
    return True

def process_system(event):
    r'''Returns True if event processed.
    '''
    if event.event == Tempo_status:
        bpm = data_to_bpm(event.result)
        if Verbose:
            trace(f"Got tempo message, {bpm=}, Clock_interval={round(Clock_interval, 5)}")
        midi_set_tempo(bpm)
        return True
    return False

# These all return True if the event is handled.
Event_fns = {
    EventType.START: process_start,
    EventType.STOP: process_stop,
    EventType.CONTINUE: process_continue,
    EventType.SONGPOS: process_songpos,
    EventType.SYSTEM: process_system,     # tempo
}

def midi_process_clock(event):
    r'''Processes: Clock, Start, Stop, Continue, tempo, time_signature, spp

    Returns True if the event was handled, False otherwise.

    Caller must eventually call midi_drain_output.
    '''
    if event.type in Event_fns:
        return Event_fns[event.type](event)
    return False

def midi_process_clock_fn(event):
    r'''Calls midi_process_clock, and returns False.

    Caller must eventually call midi_drain_output.
    '''
    midi_process_clock(event)
    return False

def midi_set_time_signature(beats, beat_type, port=None):
    r'''Sends a Time Signature SystemEvent event if port is set.
    '''
    global Time_signature
    Time_signature = (beats, beat_type)
    if port is not None:
        midi_send_event(SystemEvent(Time_sig_status, time_sig_to_data(beats, beat_type)), port=port)

def midi_set_tempo(bpm):
    global Clock_interval
    if Verbose:
        trace(f"midi_set_tempo: {bpm=}")
    for queue in Queues.values():
        queue.set_tempo(bpm=bpm, ppq=queue.ppq_setting)  # drain not required?
    Clock_interval = 60.0 / (bpm * Clocks_per_quarter_note)  # in secs

def midi_start(reset_sync_ticks=True):
    global Queue_running, Queue_sync_ticks, Next_clock_to_queue, Drain_needed, Do_start
    global Clocks_sent
    if Verbose:
        trace("midi_start")
    if Queues:
        if Verbose:
            trace("midi_start: starting queues")
        for queue in Queues.values():
            queue.start()   # drain_output needs to be called
        Queue_running = True
        Drain_needed = True
        Do_start = False
        Clocks_sent = 0
        if reset_sync_ticks:  # not called from continue
            if Verbose:
                trace("midi_start: reseting Queue_sync_ticks and Next_clock_to_queue to 0")
            Queue_sync_ticks = 0
            Next_clock_to_queue = 0
    
def midi_stop():
    global Queue_running, Drain_needed
    if Verbose:
        trace("midi_stop")
    if Queues:
        if Verbose:
            trace("midi_stop: stopping queues")
        for queue in Queues.values():
            queue.stop()   # drain_output needs to be called
        Queue_running = False
        Drain_needed = True
    return Clocks_sent

def midi_continue():
    global Queue_running, Drain_needed, Do_start
    if Verbose:
        trace("midi_continue")
    if Do_start:
        # Queue_sync_ticks already set from midi_spp
        if Verbose:
            trace("midi_continue: Do_start -- calling midi_start instead")
        midi_start(reset_sync_ticks=False)
    elif Queues:
        if Verbose:
            trace("midi_continue: continuing queues")
        for queue in Queues.values():
            queue.continue_()   # drain_output needs to be called
        Queue_running = True
        Drain_needed = True

def midi_spp(song_position):
    global Queue_sync_ticks, Next_clock_to_queue, Do_start
    if Verbose:
        trace("midi_song_position", song_position)
    if Queue_running:
        trace(f"midi_spp({song_position=}): ERROR: queue is running -- ignored")
    else:
        Do_start = True
        clocks = song_position * Clocks_per_spp
        Queue_sync_ticks = clocks * Ticks_per_clock  # Queue_sync_ticks for start (queue.ticks == 0)
        Next_clock_to_queue = clocks
        if Verbose:
            trace(f"midi_song_position: {Queue_sync_ticks=}, {Next_clock_to_queue=}")

def midi_get_named_queue(name):
    if name in Queues:
        return Queues[name]
    return Client.get_named_queue(name)

def midi_close_queue(name):
    global Default_queue
    if name not in Queues:
        trace(f"midi_close_queue: {name=} unknown -- ignored")
    else:
        if Verbose:
            trace(f"midi_close_queue, {name=}, {Queues[name]=}, {Default_queue=}, "
                  f"pending before={Client.event_output_pending()}")
        Queues[name].close()
        if Verbose:
            trace(f"midi_close_queue, {name=}, pending after={Client.event_output_pending()}")
        if Queues[name] is Default_queue:
            Default_queue = None  # remove reference, so client._queues gets updated!
        del Queues[name]

def midi_close():
    if Verbose:
        trace("midi_close")
    if Sel is not None:
        if Verbose:
            trace("midi_close: closing Selector")
        Sel.close()
    if Verbose and Ports:
        trace("midi_close: closing ports")
    for port in Ports.values():
        port.close()
    if Verbose and Queues:
        trace("midi_close: closing queues")
    for queue in Queues.values():
        queue.close()
    if Client is not None:
        if Verbose:
            trace("midi_close: closing Client")
        Client.close()
    if Verbose:
        trace("midi_close: done!")

