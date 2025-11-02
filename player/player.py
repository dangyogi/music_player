# player.py

r'''Music player.

Plays music from musicxml files.  Takes it's expression as midi commands (e.g., from expression
console using my control-console github repo).

Here "Tick" refers to the tick used for queuing in ALSA.  The "tick" rate (ppq) is set by a command
line argument (--ppq).  This defaults to 960 (so 40 ALSA queue "ticks" per MIDI CLOCK).
'''

from .expressions import Exp_CC_commands, linear, modify, modify_param
from . import states

from .tools.midi_utils import *


Max_note_on_advance_clocks = None  # max clocks that note on may be advanced
Min_note_on_advance_clocks = None  # min clocks that note on may be advanced
Final_clock = 0

Transpose = 0
Velocity = 43

def init(ppq, max_advance, min_advance, verbose):
    global Verbose, Max_note_on_advance_clocks, Min_note_on_advance_clocks, Ticks_per_clock
    global Control_port, Control_port_addr, Synth_port, Timer_port, Timer_port_addr

    Verbose = states.Verbose = verbose
    Max_note_on_advance_clocks = max_advance
    Min_note_on_advance_clocks = min_advance
    Ticks_per_clock = fraction(ppq, 24)
    trace(f"init: {Max_note_on_advance_clocks=}, {Min_note_on_advance_clocks=},")
    trace(f"      {ppq=}, {Verbose=}, {Ticks_per_clock=}")
    midi_set_verbose(verbose)
    midi_init("Player")
    Control_port = states.Control_port =  midi_create_inout_port("Control", default=False,
                                                  connect_to=["Net Client"],
                                                  connect_from=["Net Client"])
    Control_port_addr = midi_address((Control_port.client_id, Control_port.port_id))

    # default port
    Synth_port = midi_create_output_port("Synth", connect_to=["FLUID Synth:"])

    Clock_port = midi_create_output_port("Clock", default=False, clock_port=True,
                                                  connect_to=["Net Client", "FLUID Synth"])
    midi_create_queue("Player Queue", ppq, default=True)
    midi_process_fn(process_event)

def channel(value):
    states.Channel = min(15, value)
    return False

scale_transpose = linear(1, -12)

def transpose(value):
    r'''Positive values transpose to higher pitches, negative values to lower pitches.
    '''
    global Transpose
    Transpose = scale_transpose(value)
    return False

def dynamics(value):
    global Velocity
    Velocity = value

def tempo(value):
    global Clocks_per_second
    bpm = data_to_bpm(value)   # bpm (beats per minute).  "beat" == "quarter note" == 24 clocks
    Clocks_per_second = bpm * 24 / 60  # 12 at bpm == 30, 80 at bpm == 200
    #ticks = int(math.ceil(Ticks_per_clock * Clocks_per_second * Latency)) # 3-16 at 960 ppq
    #Latency_clocks = fraction(ticks, Ticks_per_clock)
    midi_set_tempo(bpm)
    if Verbose:
        trace(f"Got tempo {bpm=}, {Clocks_per_second=}")

Ch2_CC_commands = {  # human channel 2.  does not include tempo Sys Common function
    0x55: channel,
    0x56: transpose,
    0x57: dynamics,
}

def process_event(event):
    r'''Callback function, called by midi_pause to process all incoming midi events.
    '''
    if event.source.client_id == 0:
        # ignore these gratuitous events from the System client...
        return
    assert event.dest == Control_port_addr, \
           f"process_event({event=}): expected dest {Control_port_addr=}, got {event.dest=}"
    # Only events from the exp console make it this far!
    if Verbose:
        trace(f"process_event({event=}): {event.source=}, event.type={Event_type_names[event.type]}")
    if event.type == EventType.SYSTEM and event.event == Tempo_status:
        tempo(event.result)   # don't leave this to midi_process_clock...
    elif event.type != EventType.CONTROLLER or event.channel == 0:
        trace(f"process_event({event=}): SYSTEM or channel 0(1) event, "
               "forwarding to states.process_ch1_event")
        states.process_ch1_event(event)
    # event.type == EventType.CONTROLLER
    elif event.channel == 1:  # human channel 2
        # Global settings: Channel, Transpose, Channel Volume, Pedals
        if event.param not in Ch2_CC_commands:
            trace(f"process_event({event=}): unknown ch2 CONTROLLER event.param, "
                  f"{event.param=:#X}, forwarding")
            event.tick = 0
            event.dest = None
            event.channel = states.Channel
            midi_send_event(event)
        else:
            trace(f"process_event({event=}): channel 1(2) {event.param=:#X}, {event.value=}")
            Ch2_CC_commands[event.param](event.value)
    elif event.channel in (2, 3):  # human channels 3, 4
        # All note related settings
        cc_key = event.channel, event.param
        if cc_key not in Exp_CC_commands:
            trace(f"process_event({event=}): unknown ({event.channel=}, {event.param=}) "
                  "-- forwarding")
            event.tick = 0
            event.dest = None
            event.channel = states.Channel
            midi_send_event(event)
        else:
            trace(f"process_event({event=}): ({event.channel=}, {event.param=:#X}) = {event.value=}")
            Exp_CC_commands[cc_key](event.value)
    else:
        trace(f"process_event({event=}): unknown channel, {event.channel=} -- forwarding")
        event.tick = 0
        event.dest = None
        event.channel = states.Channel
        midi_send_event(event)

def send_parts():
    global Final_clock
    while True:
        if Verbose:
            trace("send_parts called, entering top midi_pause loop")
        while True:
            try:
                if Verbose:
                    trace("send_parts top loop calling midi_pause")
                midi_pause()
            except states.BackToTopException:
                trace("send_parts: WARNING caught BackToTopException in start up")
                pass  # stay in loop
            except states.StartPlayingException as e:
                if Verbose:
                    trace("send_parts caught StartPlayingException in start up")
                spp = e.spp
                Final_clock = 0
                break
        while True:  # loops on BackToTopException
            if Verbose:
                trace("send_parts starting play loop")
            try:
                if Verbose:
                    trace("send_parts starting play")
                # FIX: Should this play all parts?  If so, set measure_no to 0 after first part
                info, measures = states.Parts[spp.part_no]
                trace("part", info.id)
                send_measures(measures, spp.measure_no, spp.note_no)
                states.State.end_song(Final_clock)
                trace("send_parts: WARNING end_song did not raise Exception")
                break
            except states.StartPlayingException as e:
                if Verbose:
                    trace("send_parts caught BackToTopException playing")
                spp = e.spp
            except states.BackToTopException:
                if Verbose:
                    trace("send_parts caught BackToTopException playing")
                break
        if Verbose:
            trace("send_parts exiting play loop, returning to start up loop")

def send_measures(measures, first_measure, first_note):
    notes_played = 0
    for i in range(first_measure, len(measures)):
        measure = measures[i]
        trace(f"send_measures: measure={measure.number}, index={measure.index}, {i=}, "
              f"start={measure.start}, duration_clocks={measure.duration_clocks}")
        if hasattr(measure, "time"):
            trace(f"send_measures: measure {measure.number} has time sig, calling "
                   "midi_set_time_signature {measure.time=}")
            midi_set_time_signature(*measure.time, port=Control_port)
        notes_played += send_notes(measure, first_note)
        first_note = 0
    trace("total notes played", notes_played)

def send_notes(measure, first_note):
    notes_played = 0
    notes = measure.sorted_notes
    if Verbose:
        trace(f"send_notes({measure.number=}, {first_note=})")
    for i in range(first_note, len(notes)):
        note = notes[i]
        if note.ignore:
            continue
        if play(measure, note):
            notes_played += 1
    midi_drain_output()
    if Verbose:
        trace("  notes played:", notes_played)
    return notes_played

def play(measure, note):
    r'''Caller needs to do midi_drain_output().
    '''
    global Final_clock

    start_clock = modify_param(note, "note_on", note.start)
   #if note.grace is not None:
   #    trace(f"play: grace note; note={note.note}, {note.start=} -- setting end == start")
   #    end_clock = note.start
   #else:
   #    end_clock = note.start + note.duration_clocks
    current_clock = midi_queue_time()
    advance = Max_note_on_advance_clocks

    while advance >= Min_note_on_advance_clocks:
        # wait to last minute to allow expressions to be updated
        trigger_clock = start_clock - advance
        if Verbose:
            trace(f"play: note={note.note}, {start_clock=}, duration={note.duration_clocks}, "
                  f"{end_clock=}, {current_clock=}, {trigger_clock=}")
        if current_clock >= trigger_clock:
            break
        if Verbose:
            trace(f"play calling midi_pause, to_clock={trigger_clock}")
        midi_pause(to_clock=trigger_clock)
        current_clock = midi_queue_time()
        start_clock = modify_param(note, "note_on", note.start)
        if current_clock > trigger_clock:
            trace(f"play: note={note.note}, {trigger_clock=}, {current_clock=}, {start_clock=}")
        advance //= 2

    # apply expressions:
    channel = states.Channel
    velocity = Velocity
    new_specs = modify(note, channel + 1, velocity)

    if not note.rest:
        assert new_specs is not None, \
               f"play(measure={measure.number}, {note.note}): new_specs is None!"
        trace(f"modify({note.note}, start={note.start=}, "
              f"duration_clocks={getattr(note, 'duration_clocks', 0)}, "
              f"{Velocity=}, {current_clock=}) -> {new_specs}")
        channel, start_clock, end_clock, velocity = new_specs
        if start_clock < current_clock - 0.1:
            trace(f"play(measure={measure.number}, note={note.note}): missed note start by",
                  current_clock - start_clock, "clocks")
        midi_send_event(
          NoteOnEvent(note.midi_note + Transpose, channel - 1, velocity, tick=to_ticks(start_clock)))
        midi_send_event(
          NoteOffEvent(note.midi_note + Transpose, channel - 1, 0, tick=to_ticks(end_clock)))
        if end_clock > Final_clock:
            Final_clock = end_clock

def run():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--ppq', '-p', type=int, default=960)
    parser.add_argument('--max_advance', '-M', type=int, default=18,  # 75% of qtr note (24)
                        help="in clocks")                             # 750mSec @ 60 bpm
                                                                      # 225mSec @ 200 bpm
    parser.add_argument('--min_advance', '-m', type=int, default=2,   #  8% of qtr note (24)
                        help="in clocks")                             #  83mSec @ 60 bpm
                                                                      #  25mSec @ 200 bpm
    parser.add_argument('--verbose', '-v', action="store_true", default=False)

    args = parser.parse_args()

    #trace(f"{args=}")

    try:
        init(args.ppq, args.max_advance, args.min_advance, args.verbose)
        send_parts()
    finally:
        if Final_clock:
            if Verbose:
                trace(f"run.finally {Final_clock=}, calling midi_pause to_clock={Final_clock + 2}")
            midi_pause(to_clock=Final_clock + 2)  # give queue a chance to drain before killing it
            trace(f"midi_pause done: {midi_queue_time()=}")
        midi_stop()
        #midi_pause(0.5)
        midi_close()

