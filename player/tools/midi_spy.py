# midi_spy.py

import time
from collections import Counter

from .midi_utils import *

Show_clocks = False
Clock_bpm = None
First_clock = None
Last_clock = 0
Err_secs_counts = Counter()
Err_pulse_counts = Counter()
Clock_stat_period = None
Clocks_seen = 0

def process_event(event):
    # w/false, often 0, but there's still an event.
    # w/True, always at least 1, but often more
    global First_clock, Last_clock, Err_secs_counts, Err_pulse_counts
    global Clocks_seen, NoteOns_seen, NoteOffs_seen
    global Clock_queue, Clock_ppq, Clock_bpm, Pulses_per_clock, Secs_per_clock, Secs_per_pulse
    show_clock_stats = False
    if event.type != EventType.CLOCK or Show_clocks:
        #input_time = time.time()
        #trace("input", input_time - pending_time)
        trace("source", event.source, event,
              "tag", event.tag,
              "queue_id", event.queue_id, "tick", event.tick, "time", event.time)
        if event.type == EventType.PORT_START:
            #print(dir(event))
            #
            # addr (source port)
            # dest
            # flags
            # length
            # queue_id
            # raw_data
            # relative
            # source
            # tag
            # tick
            # time
            # type
            #print(f"{event.addr=}, {event.dest=}, {event.flags=}, {event.relative=}, {event.source=}")
            #print(f"{event.tag=}, {event.tick=}, {event.time=}, {event.type=}")
            #print(f"{event.addr=}, {event.flags=}")
            connect_from(event.addr)
    if event.type == EventType.CLOCK:
        Clocks_seen += 1
        if event.tag != 0:
            trace(f"CLOCK has non-zero tag {event.tag}")
        elif str(event.source) != CM_timer_addr:
            trace(f"CLOCK not from Clock Master:Timer, from {event.source}")
        else:
            if Clock_bpm:
                now = time.clock_gettime(time.CLOCK_MONOTONIC)
                if First_clock is None:
                    First_clock = now
                    Last_clock = now
                # report every Clock_stat_period secs
                elif Clock_stat_period is None or Last_clock - First_clock < Clock_stat_period:
                    # accumulate clock stats
                    err = round(now - Last_clock - Secs_per_clock, 4)
                    if err < 0.0:
                        #trace(f"Got clock period err < 0, {err=}")
                        err = -err
                    Err_secs_counts[err] += 1
                    Last_clock = now
                else:
                    show_clock_stats = True
            pulse_delay = midi_queue_time(Clock_queue) - event.tick
            err = round(pulse_delay * Secs_per_pulse, 4)
            if err < 0.0:
                trace(f"Got pulse err < 0, queue_time={midi_queue_time(Clock_queue)}, "
                      f"{event.tick=}, {err=}")
                err = -err
            Err_pulse_counts[err] += 1
    elif event.type == EventType.NOTEON:
        NoteOns_seen[str(event.source)] += 1
    elif event.type == EventType.NOTEOFF:
        NoteOffs_seen[str(event.source)] += 1
    elif event.type == EventType.START and str(event.source) == CM_timer_addr:
        Clocks_seen = 0
        NoteOns_seen = Counter()
        NoteOffs_seen = Counter()
        Clock_queue = midi_get_named_queue("Clock")
        queue_tempo = Clock_queue.get_tempo()
        Clock_ppq = queue_tempo.ppq
        Clock_bpm = queue_tempo.bpm
        Pulses_per_clock = Clock_ppq // 24
        Secs_per_clock = 60.0 / (Clock_bpm * 24)
        Secs_per_pulse = 60 / (Clock_bpm * Clock_ppq)
        trace(f"START: {Clock_ppq=}, {Clock_bpm=}, {Pulses_per_clock=}, {Secs_per_pulse=}")
    elif event.type == EventType.STOP and str(event.source) == CM_timer_addr:
        #def str_seen(seen):
        #    return ', '.join(f"{str(addr)}: {count}" for addr, count in sorted(seen.items()))
        trace(f"STOP: got {Clocks_seen} CLOCKS, {NoteOns_seen} NOTEONs, "
              f"{NoteOffs_seen} NOTEOFFs")
        show_clock_stats = True
    if show_clock_stats:
        trace("Clock time stats:")
        clock_secs_count = 0
        for err, count in sorted(Err_secs_counts.items()):
            print(f"  {err}: {count}")
            clock_secs_count += count
        trace("Clock pulse stats:")
        clock_pulse_count = 0
        for err, count in sorted(Err_pulse_counts.items()):
            print(f"  {err}: {count}")
            clock_pulse_count += count
        Last_clock = 0
        Last_clock = 0
        First_clock = None
        Err_secs_counts = Counter()
        Err_pulse_counts = Counter()
        trace(f"  counted secs for {clock_secs_count} CLOCK messages")
        trace(f"  counted pulses for {clock_pulse_count} CLOCK messages")
    return False  # drain_output not needed

def connect_from(addr):
    port_info = midi_get_port_info(addr)
    cap = port_info.capability
    if (cap & PortCaps.READ) and (cap & PortCaps.SUBS_READ):
        name = midi_get_address(port_info)
        trace(">>>>>>>>>>> connecting from", name)
        if not midi_connect_from(Port, port_info):
            trace("Got error, not connected")


Port = None

def run():
    global CM_timer_addr, Clock_bpm, Secs_per_clock, Port, Show_clocks, Clock_stat_period

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument('--show-clocks', '-s', action="store_true", default=False)
    #parser.add_argument('--bpm', '-b', type=int, default=None)
    parser.add_argument('--clock_stat_period', '-c', type=int, default=3600)  # 1 hr
    args = parser.parse_args()

    Show_clocks = args.show_clocks
    #Clock_bpm = args.bpm
    #if Clock_bpm:
    #    Secs_per_clock = 60.0 / (Clock_bpm * 24)

    Clock_stat_period = args.clock_stat_period

    try:
        if args.verbose:
            midi_set_verbose(args.verbose)
        client = midi_init("midi-spy")
        Port = midi_create_input_port("notes", connect_from=(SYSTEM_TIMER, SYSTEM_ANNOUNCE))
        CM_timer_addr = str(midi_address("Clock Master:Timer"))
        trace(f"{Show_clocks=}, {Clock_bpm=}, {Clock_stat_period=}, {CM_timer_addr=}")
        for x in midi_list_ports():
            if x.client_id != client.client_id:
                connect_from(x)

        midi_process_fn(process_event)

        while True:
            midi_pause()

    finally:
        midi_close()



if __name__ == "__main__":
    run()
