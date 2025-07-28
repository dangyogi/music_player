# player.py

from fractions import Fraction
import argparse

from .parse_xml import parse
from .unroll_repeats import unroll_parts
from .assign_starts import assign_parts
from .tie_notes import tie_parts

from .tools.midi_utils import *


Tick_offset = 0      # changed by SPP/start
Latency = None       # secs, default 0.005
Tick_latency = None  # number of ticks in Latency period, altered by change in Tempo
Final_tick = 0

def init(tag, ppq, latency, verbose):
    global Tag, Verbose, Latency, Ppq

    Tag = tag
    Verbose = verbose
    Latency = latency
    Ppq = ppq
    midi_set_verbose(verbose)
    midi_init("Player")
    midi_create_input_port("Input", connect_from=["Net Client:Network", "Clock Master:Timer",
                                                  "Exp Console:Output"])
    midi_create_output_port("Output", clock_master=True,
                            connect_to=["Net Client:Network", "Clock Master:Input"])
    midi_set_tag(tag)
    midi_set_ppq(ppq)
    midi_process_fn(process_event)

def process_event(event):
    if midi_process_clock(event):
        return False


def read_musicxml(music_file):
    parts = parse(music_file)
    new_parts = unroll_parts(parts)
    assign_parts(new_parts)
    tie_parts(new_parts)
    return new_parts

def send_parts(parts, measure_number):
    for info, measures in parts:
        print("part", info.id)
        send_measures(measures, measure_number)

def send_measures(measures, measure_number):
    global Final_tick, Tick_offset

    i = 0
    send_info(measures[0])
    spp_division = None
    notes_played = 0
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
            i += 1
    print("total notes played", notes_played)

def send_info(first_measure):
    global Tempo, Divisions, Divisions_per_16th, Divisions_per_measure
    global Ticks_per_division, Tick_latency

    print("send_info:")
    key = first_measure.key
    if hasattr(key, 'mode'):
        print(f"  key_sig: fifths={key.fifths}, mode={key.mode}")
    else:
        print(f"  key_sig: fifths={key.fifths}")
    print(f"  time_sig={first_measure.time}")
    midi_set_time_signature(*first_measure.time)
    Tempo = first_measure.tempo
    print(f"  tempo={Tempo}")
    midi_set_tempo(Tempo)
    print(f"  volume={first_measure.volume}")
    print(f"  dynamics={first_measure.dynamics}")
    Divisions = first_measure.divisions
    print(f"  divisions={Divisions}")
    Divisions_per_16th = first_measure.divisions_per_16th
    print(f"  divisions_per_16th={Divisions_per_16th}")
    Divisions_per_measure = first_measure.divisions_per_measure
    print(f"  divisions_per_measure={Divisions_per_measure}")
    Ticks_per_division = Fraction(Ppq, Divisions)
    if Ticks_per_division.denominator == 1:
        Ticks_per_division = Ticks_per_division.numerator
    Tick_latency = int(math.ceil((Ppq * Tempo) * Latency / 60))

def send_notes(measure, starting_division):
    global Tick_offset

    print(f"send_notes({starting_division=}): measure={measure.number}, index={measure.index}, "
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
        play(note, measure.start, drain_output)
        drain_output = True
        notes_played += 1
        #midi_set_tempo(bpm)
        #midi_set_time_signature(time_sig)
    if drain_output:
        midi_drain_output()
    print("  notes played:", notes_played)
    return notes_played

def play(note, measure_start, drain_output):
    r'''Caller needs to do midi_drain_output().
    '''
    global Final_tick
    start_tick = round((note.start + measure_start) * Ticks_per_division) - Tick_offset
    end_tick = round((note.start + measure_start + note.duration) * Ticks_per_division) - Tick_offset
    current_tick = midi_tick_time()
    trigger_tick = start_tick - Tick_latency
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

def prepare_note(note, start_tick, end_tick):
    return (NoteOnEvent(note.midi_note, 0, 43, tick=start_tick, tag=Tag),
            NoteOffEvent(note.midi_note, 0, 0, tick=end_tick, tag=Tag))

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', '-t', type=int, default=17)
    parser.add_argument('--ppq', '-p', type=int, default=960)
    parser.add_argument('--latency', '-l', type=float, default=0.005)
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument('--measure', '-m', default=None)
    parser.add_argument("music_file")

    args = parser.parse_args()

    #print(f"{args=}")

    try:
        init(args.tag, args.ppq, args.latency, args.verbose)
        parts = read_musicxml(args.music_file)
        send_parts(parts, args.measure)
    finally:
        midi_pause(to_tick=Final_tick + 2)  # give queue a chance to drain before killing it
        midi_close()



if __name__ == "__main__":
    run()
