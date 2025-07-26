# player.py

import argparse

from .parse_xml import parse
from .unroll_repeats import unroll_parts
from .assign_starts import assign_parts
from .tie_notes import tie_parts

from .tools.midi_utils import *


def init(tag, ppq, verbose):
    global Verbose

    Verbose = verbose
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

def send_parts(parts):
    for info, measures in parts:
        print("part", info.id)
        send_measures(measures)

def send_measures(measures):
    i = 0
    send_info(measures[0])
    spp_division = None
    notes_played = 0
    while i < len(measures):
        try:
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
        else:
            i += 1
    print("total notes played", notes_played)

def send_info(first_measure):
    global Divisions, Divisions_per_16th, Divisions_per_measure, Spp_per_measure

    print("send_info:")
    key = first_measure.key
    if hasattr(key, 'mode'):
        print(f"  key_sig: fifths={key.fifths}, mode={key.mode}")
    else:
        print(f"  key_sig: fifths={key.fifths}")
    print(f"  time_sig={first_measure.time}")
    print(f"  tempo={first_measure.tempo}")
    print(f"  volume={first_measure.volume}")
    print(f"  dynamics={first_measure.dynamics}")
    Divisions = first_measure.divisions
    print(f"  divisions={Divisions}")
    Divisions_per_16th = first_measure.divisions_per_16th
    print(f"  divisions_per_16th={Divisions_per_16th}")
    Divisions_per_measure = first_measure.divisions_per_measure
    print(f"  divisions_per_measure={Divisions_per_measure}")
    Spp_per_measure = Divisions_per_measure // Divisions_per_16th

def send_notes(measure, starting_division):
    print(f"send_notes({starting_division=}): index={measure.index}, "
          f"start={measure.start}, start_spp={measure.start_spp}, duration={measure.duration}")
    notes_played = 0
    for note in measure.sorted_notes:
        if starting_division is not None:
            if note.start >= starting_division:
                starting_division = None
            else:
                continue
        if note.ignore:
            continue
        notes_played += 1
        #midi_set_tempo(bpm)
        #midi_set_time_signature(time_sig)
    print("  notes played:", notes_played)
    return notes_played

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', '-t', type=int, default=17)
    parser.add_argument('--ppq', '-p', type=int, default=960)
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument("music_file")

    args = parser.parse_args()

    #print(f"{args=}")

    try:
        init(args.tag, args.ppq, args.verbose)
        parts = read_musicxml(args.music_file)
        send_parts(parts)
    finally:
        midi_close()



if __name__ == "__main__":
    run()
