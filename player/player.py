# player.py

r'''Music player.

Plays music from musicxml files.  Takes it's expression as midi commands (e.g., from expression
console using my control-console github repo).

Here "Tick" refers to the tick used for queuing in ALSA.  The "tick" rate (ppq) is set by a command
line argument (--ppq).  This defaults to 960 (so 40 ALSA queue "ticks" per MIDI CLOCK).
'''

from .expressions import Ch2_CC_commands, linear, exponential
from . import states

from .tools.midi_utils import *


Tick_offset = 0      # changed by SPP/start
Latency = None       # secs, default 0.005
Tick_latency = None  # number of ticks in Latency period, altered by change in Tempo
Final_tick = 0

Channel = 0
Transpose = 0

def init(tag, ppq, latency, verbose):
    global Tag, Verbose, Latency, Ppq, Ticks_per_clock, Control_port, Control_port_addr
    global Synth_port, Clock_master_port, Clock_master_port_addr

    Tag = tag
    Verbose = states.Verbose = verbose
    Latency = latency
    Ppq = ppq
    Ticks_per_clock = fraction(Ppq, 24)
    midi_set_verbose(verbose)
    midi_init("Player")
    Control_port = midi_create_inout_port("Control", default=False,
                                               connect_from=["Clock Master:To Player"],
                                               connect_to=["Clock Master:To Exp_console"])
    Control_port_addr = midi_address((Control_port.client_id, Control_port.port_id))
    Synth_port = midi_create_output_port("Synth",
                                               connect_to=["Clock Master:To Synth"])
    Clock_master_port = midi_create_inout_port("Clock Master", clock_master=True,
                                               connect_from=["Clock Master:Timer"],
                                               connect_to=["Clock Master:Input"])
    Clock_master_port_addr = midi_address((Clock_master_port.client_id, Clock_master_port.port_id))
    midi_set_tag(tag)
    midi_set_ppq(ppq)
    midi_process_fn(process_event)

def channel(value):
    global Channel
    Channel = min(15, value)
    return False

scale_transpose = linear(1, -12)

def transpose(value):
    r'''Positive values transpose to higher pitches, negative values to lower pitches.
    '''
    global Transpose
    Transpose = scale_transpose(value)
    return False

scale_tempo = exponential(1.01506, 30)

def tempo(value):
    global Clocks_per_second, Tick_latency
    bpm = scale_tempo(value)   # bpm (beats per minute).  "beat" == "quarter note"
    Clocks_per_second = fraction(bpm * 24, 60)
    Tick_latency = int(math.ceil(Clocks_per_second * Latency))  # ticks in latency period
                                                                # Looks like this will always be 1!
    if Verbose:
        trace(f"Got tempo {bpm=}, {Clocks_per_second=}, {Tick_latency=}, forwarding to Clock Master")
    midi_send_event(SystemEvent(Tempo_status, value), port=Clock_master_port)
    return False

def synth_volume_msb(value):
    global Synth_volume_msb
    # FIX: code
    trace(f"synth_volume_msb({value=})")
    return False

def synth_volume_lsb(value):
    # FIX: code
    trace(f"synth_volume_lsb({value=})")
    return False

def sustain_pedal(value):
    event = ControlChangeEvent(Channel, 0x40, value)
    midi_send_event(event)
    return True

def sostenuto_pedal(value):
    event = ControlChangeEvent(Channel, 0x42, value)
    midi_send_event(event)
    return True

def soft_pedal(value):
    event = ControlChangeEvent(Channel, 0x43, value)
    midi_send_event(event)
    return True


Ch3_CC_commands = {  # does not include tempo Sys Common function
    0x55: channel,
    0x56: transpose,
    0x07: synth_volume_msb,
    0x27: synth_volume_lsb,
    0x40: sustain_pedal,
    0x42: sostenuto_pedal,
    0x43: soft_pedal,
}

def process_event(event):
    r'''Callback function, called by midi_pause to process all incoming midi events.

    Returns True to midi_pause if midi_drain_output needs to be done.
    '''
    if event.dest == Clock_master_port_addr:
        midi_process_clock(event)
        return False
    if event.source.client_id == 0:
        # ignore these gratuitous events from the System client...
        return False
    assert event.dest == Control_port_addr, \
           f"process_event({event=}): expected dest {Control_port_addr=}, got {event.dest=}"
    # Only events from the exp console make it this far!
    if Verbose:
        trace(f"process_event({event=}): {event.source=}, event.type={Event_type_names[event.type]}")
    if event.type == EventType.SYSTEM and event.event == Tempo_status:
        return tempo(event.result)
    if event.type != EventType.CONTROLLER or event.channel == 0:
        trace(f"process_event({event=}): SYSTEM or channel 0(1) event, "
               "forwarding to states.process_ch1_event")
        return states.process_ch1_event(event)
    # event.type == EventType.CONTROLLER
    if event.channel == 1:
        # All note related settings
        if event.param not in Ch2_CC_commands:
            trace(f"process_event({event=}): unknown ch2 event.param, {event.param=:#X}, ignored")
            return False
        trace(f"process_event({event=}): channel 1(2) {event.param=:#X}, {event.value=}")
        return Ch2_CC_commands[event.param](event.value)
    if event.channel == 2:
        # Global settings: Transpose, Tempo, Synth Volume
        if event.param not in Ch3_CC_commands:
            trace(f"process_event({event=}): unknown ch3 CONTROLLER event.param, "
                  f"{event.param=:#X}, ignored")
            return False
        trace(f"process_event({event=}): channel 2(3) {event.param=:#X}, {event.value=}")
        return Ch3_CC_commands[event.param](event.value)
    trace(f"process_event({event=}): unknown channel, {event.channel=}, ignored")
    return False

def send_parts():
    if Verbose:
        trace("send_parts called, entering top midi_pause loop")
    try:
        while True:
            midi_pause()
    except states.BackToTopException as e:
        spp = e.spp
    if Verbose:
        trace("send_parts entering play loop")
    while True:
        try:
            # FIX: Should this play all parts?
            info, measures = states.Parts[spp.part_no]
            trace("part", info.id)
            send_measures(measures, spp.measure_no, spp.note_no)
        except states.BackToTopException as e:
            spp = e.spp

def send_measures(measures, first_measure, first_note):
    global Tick_offset

    notes_played = 0
    Tick_offset = round(measures[first_measure].sorted_notes[first_note].start * Ticks_per_clock)
    for i in range(first_measure, len(measures)):
        measure = measures[i]
        trace(f"send_measures: measure={measure.number}, index={measure.index}, {i=}, "
              f"start={measure.start}, duration_clocks={measure.duration_clocks}")
        if measure.time:
            midi_set_time_signature(*measure.time)
        notes_played += send_notes(measure, first_note)
        first_note = 0
    trace("total notes played", notes_played)

def send_notes(measure, first_note):
    notes_played = 0
    drain_output = False
    notes = measure.sorted_notes
    for i in range(first_note, len(notes)):
        note = notes[i]
        if note.ignore:
            continue
        if play(note, drain_output):
            notes_played += 1
            drain_output = True
    if drain_output:
        midi_drain_output()
    if Verbose:
        trace("  notes played:", notes_played)
    return notes_played

def play(note, drain_output):
    r'''Caller needs to do midi_drain_output() if return is 1 (not 0).
    '''
    global Final_tick

    start_tick = round(note.start * Ticks_per_clock) - Tick_offset
    if note.grace is not None:
        # FIX
        trace(f"play: skipping grace note; note={note.note}, {start_tick=}")
        end_tick = start_tick
        return 0
    end_tick = round((note.start + note.duration_clocks) * Ticks_per_clock) - Tick_offset
    current_tick = midi_tick_time()
    trigger_tick = start_tick - Tick_latency
    if Verbose:
        trace(f"play: note={note.note}, {start_tick=}, duration={note.duration_clocks}, {end_tick=}, "
              f"{current_tick=}, {trigger_tick=}")
    if current_tick < trigger_tick:
        if drain_output:
            midi_drain_output()
        midi_pause(to_tick=trigger_tick)
    note_on, note_off = prepare_note(note, start_tick, end_tick)
    midi_send_event(note_on)
    midi_send_event(note_off)
    if end_tick > Final_tick:
        Final_tick = end_tick
    return 1

def prepare_note(note, start_tick, end_tick):
    return (NoteOnEvent(note.midi_note + Transpose, Channel, 43, tick=start_tick, tag=Tag),
            NoteOffEvent(note.midi_note + Transpose, Channel, 0, tick=end_tick, tag=Tag))

def run():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', '-t', type=int, default=17)
    parser.add_argument('--ppq', '-p', type=int, default=960)
    parser.add_argument('--latency', '-l', type=float, default=0.005, help="in seconds")
    parser.add_argument('--verbose', '-v', action="store_true", default=False)

    args = parser.parse_args()

    #trace(f"{args=}")

    try:
        init(args.tag, args.ppq, args.latency, args.verbose)
        send_parts()
    finally:
        if Final_tick:
            midi_pause(to_tick=Final_tick + 2)  # give queue a chance to drain before killing it
        midi_stop()
        midi_pause(0.5)  # give queue a chance to drain before killing it
        midi_close()

