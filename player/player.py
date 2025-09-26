# player.py

from .expressions import Ch2_CC_commands, linear, exponential
import states

from .tools.midi_utils import *


Tick_offset = 0      # changed by SPP/start
Latency = None       # secs, default 0.005
Tick_latency = None  # number of ticks in Latency period, altered by change in Tempo
Final_tick = 0

Channel = 0
Transpose = 0

def init(tag, ppq, latency, verbose):
    global Tag, Verbose, Latency, Ppq, Control_port, Control_port_addr, Synth_port
    global Clock_master_port, Clock_master_port_addr

    Tag = tag
    Verbose = verbose
    Latency = latency
    Ppq = ppq
    midi_set_verbose(verbose)
    midi_init("Player")
    Control_port = midi_create_inout_port("Control", connect_from=["Clock Master:To Player"],
                                                     connect_to=["Clock Master:To Exp_console"])
    Control_port_addr = midi_address((Control_port.client_id, Control_port.port_id))
    Synth_port = midi_create_output_port("Synth",    connect_to=["Clock Master:To Synth"])
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
    tempo = scale_tempo(value)
    # FIX: code
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
    if Verbose:
        trace(f"process_event({event=}): {event.source=}, event.type={Event_type_names[event.type]}")
    if event.type == EventType.SYSTEM:
        if event.event == 0xF4:
            return tempo(event.result)
        return states.process_ch1_event(event)
    if event.channel == 0:
        return states.process_ch1_event(event)
    if event.channel == 1:
        # All note related settings
        if event.type != EventType.CONTROLLER:
            trace(f"process_event({event=}): unknown ch2 event.type, "
                  f"event.type={Event_type_names[event.type]}, ignored")
            return False
        # event is CONTROLLER event.
        if event.param not in Ch2_CC_commands:
            trace(f"process_event({event=}): unknown ch2 event.param, {event.param=:#X}, ignored")
            return False
        return Ch2_CC_commands[event.param](event.value)
    if event.channel == 2:
        # Global settings: Transpose, Tempo, Synth Volume
        if event.type == EventType.CONTROLLER:
            if event.param not in Ch3_CC_commands:
                trace(f"process_event({event=}): unknown ch3 CONTROLLER event.param, "
                      f"{event.param=:#X}, ignored")
                return False
            return Ch3_CC_commands[event.param](event.value)
        trace(f"process_event({event=}): unknown ch3 event.type, "
              f"event.type={Event_type_names[event.type]}, ignored")
        return False
    trace(f"process_event({event=}): unknown channel, {event.channel=}, ignored")
    return False

def send_parts(measure_number):
    try:
        while True:
            midi_pause()
    except BackToTopExeception:
        pass
    while True:
        try:
            for info, measures in states.Parts:
                trace("part", info.id)
                send_measures(measures, first_measure, last_measure, bpm, measure_number)
        except BackToTopExeception:
            pass

def send_measures(measures, first_measure, last_measure, bpm, measure_number):
    global Final_tick, Tick_offset

    send_info(measures[0], bpm)
    spp_division = None
    notes_played = 0
    i = 0
    if first_measure is not None:
        for i, measure in enumerate(measures):
            #trace(f"send_measure got {measure.number!r}, looking for {first_measure!r}")
            if str(measure.number) == first_measure:
                Tick_offset = round(measure.start * Ticks_per_division)
                break
        else:
            raise ValueError(f"send_measures: first_measure={first_measure} not found")
    midi_start()
    while i < len(measures):
        try:
            if measure_number is None:
                notes_played += send_notes(measures[i], spp_division)
            elif measures[i].number == measure_number:
                Tick_offset = measures[i].start * Ticks_per_division - midi_tick_time()
                notes_played += send_notes(measures[i], spp_division)
            spp_division = None
        except SPPException as x:
            spp_division = x.spp * Divisions_per_16th

            # estimate starting point of search, this could err on the high or low side...
            i = spp_division // Divisions_per_measure

            # if i errs on the low side, search up to first measure.start >= spp_division
            while i + 1 < len(measures) and measures[i].start < spp_division:
                i += 1

            # now i is on the high side, search down to first measure.start <= spp_division
            while i > 0 and measures[i].start > spp_division:
                i -= 1
            Final_tick = 0
        else:
            if last_measure is not None and str(measures[i].number) == last_measure:
                break
            i += 1
    trace("total notes played", notes_played)

def send_info(first_measure, bpm):
    global Tempo, Divisions, Divisions_per_16th, Divisions_per_measure
    global Ticks_per_division, Tick_latency

    trace("send_info:")
    key = first_measure.key
    if hasattr(key, 'mode'):
        trace(f"  key_sig: fifths={key.fifths}, mode={key.mode}")
    else:
        trace(f"  key_sig: fifths={key.fifths}")
    trace(f"  time_sig={first_measure.time}")
    midi_set_time_signature(*first_measure.time)
    if bpm is None:
        Tempo = first_measure.tempo
    else:
        Tempo = bpm
    trace(f"  tempo={Tempo}")
    midi_set_tempo(Tempo)
    trace(f"  volume={first_measure.volume}")
    trace(f"  dynamics={first_measure.dynamics}")
    Divisions = first_measure.divisions
    trace(f"  divisions={Divisions}")
    Divisions_per_16th = first_measure.divisions_per_16th
    trace(f"  divisions_per_16th={Divisions_per_16th}")
    Divisions_per_measure = first_measure.divisions_per_measure
    trace(f"  divisions_per_measure={Divisions_per_measure}")
    Ticks_per_division = fraction(Ppq, Divisions)
    Tick_latency = int(math.ceil((Ppq * Tempo) * Latency / 60))

def send_notes(measure, starting_division):
    global Tick_offset

    trace(f"send_notes({starting_division=}): measure={measure.number}, index={measure.index}, "
          f"start={measure.start}, start_spp={measure.start_spp}, duration={measure.duration}")
    notes_played = 0
    drain_output = False
    for note in measure.sorted_notes:
        if note.ignore:
            continue
        if starting_division is not None:
            if note.start + measure.start >= starting_division:
                Tick_offset = round(starting_division * Ticks_per_division)
                starting_division = None
            else:
                continue
        if play(note, measure.start, drain_output):
            notes_played += 1
            drain_output = True
        #midi_set_tempo(bpm)
        #midi_set_time_signature(time_sig)
    if drain_output:
        midi_drain_output()
    if Verbose:
        trace("  notes played:", notes_played)
    return notes_played

def play(note, measure_start, drain_output):
    r'''Caller needs to do midi_drain_output() if return is 1 (not 0).
    '''
    global Final_tick

    start_tick = round((note.start + measure_start) * Ticks_per_division) - Tick_offset
    if note.grace is not None:
        # FIX
        trace(f"play: skipping grace note; note={note.note}, {start_tick=}")
        return 0
    end_tick = round((note.start + measure_start + note.duration) * Ticks_per_division) - Tick_offset
    current_tick = midi_tick_time()
    trigger_tick = start_tick - Tick_latency
    if Verbose:
        trace(f"play: note={note.note}, {start_tick=}, duration={note.duration}, {end_tick=}, "
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
    parser.add_argument('--latency', '-l', type=float, default=0.005)
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument('--measure', '-m', default=None)
    #parser.add_argument('--range', '-r', default="", help="start_measure-end_measure")
    #parser.add_argument('--bpm', '-b', type=int, default=None)
    #FIX: parser.add_argument("music_file")

    args = parser.parse_args()

    #trace(f"{args=}")

    try:
        init(args.tag, args.ppq, args.latency, args.verbose)
        import time
        time.sleep(10)
        '''
        parts = read_musicxml(args.music_file)
        send_parts(args.measure)
        '''
    finally:
        if Final_tick:
            midi_pause(to_tick=Final_tick + 2)  # give queue a chance to drain before killing it
        midi_stop()
        midi_pause(0.5)  # give queue a chance to drain before killing it
        midi_close()

