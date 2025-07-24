# midi_spy.py

import time
from collections import Counter

from .midi_utils import *

Show_clocks = False
Clock_bpm = None
First_clock = None
Last_clock = 0
Err_counts = Counter()

def process_event(event):
    # w/false, often 0, but there's still an event.
    # w/True, always at least 1, but often more
    global First_clock, Last_clock, Err_counts
    show_clock_stats = False
    show_event = True
    if event.type == EventType.CLOCK:
        if Clock_bpm and event.tag == 0:
            now = time.clock_gettime(time.CLOCK_MONOTONIC)
            if First_clock is None:
                First_clock = now
                Last_clock = now
            elif Last_clock - First_clock < 5:  # report every 5 secs
                # accumulate clock stats
                err = round(now - Last_clock - Secs_per_clock, 4)
                if err < 0.0:
                    #print(f"Got clock period err < 0, {err=}")
                    err = -err
                Err_counts[err] += 1
                Last_clock = now
            else:
                show_clock_stats = True
        if not Show_clocks:
            show_event = False
    if show_clock_stats:
        trace("Clock stats:")
        for err, count in sorted(Err_counts.items()):
            print(f"  {err}: {count}")
        Last_clock = 0
        First_clock = None
        Err_counts = Counter()
    if show_event:
        #input_time = time.time()
        #print("input", input_time - pending_time)
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
    global Clock_bpm, Secs_per_clock, Port, Show_clocks

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action="store_true", default=False)
    parser.add_argument('--show-clocks', '-s', action="store_true", default=False)
    parser.add_argument('--bpm', '-b', type=int, default=None)
    args = parser.parse_args()

    Show_clocks = args.show_clocks
    Clock_bpm = args.bpm
    if Clock_bpm:
        Secs_per_clock = 60.0 / (Clock_bpm * 24)

    print(f"{Show_clocks=}, {Clock_bpm=}")

    try:
        if args.verbose:
            midi_set_verbose(args.verbose)
        client = midi_init("midi-spy")
        Port = midi_create_input_port("notes", connect_from=(SYSTEM_TIMER, SYSTEM_ANNOUNCE))
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
