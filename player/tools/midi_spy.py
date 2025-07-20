# midi_spy.py

import time
from collections import Counter

from .midi_utils import *

Last_clock = 0
Err_counts = Counter()

def process_event(event):
    # w/false, often 0, but there's still an event.
    # w/True, always at least 1, but often more
    global Last_clock, Err_counts
    if event.type == EventType.CLOCK and event.tag == 0:
        now = time.clock_gettime(time.CLOCK_MONOTONIC)
        if Last_clock:
            err = round(now - Last_clock - 0.01, 4)
            if err < 0.0:
                #print(f"Got clock period err < 0, {err=}")
                err = -err
            Err_counts[err] += 1
        Last_clock = now
    else:
        if Last_clock:
            for err, count in sorted(Err_counts.items()):
                print(f"  {err}: {count}")
            Last_clock = 0
            Err_counts = Counter()
        #input_time = time.time()
        #print("input", input_time - pending_time)
        print("source", event.source, event,
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
        print(">>>>>>>>>>> connecting from", name)
        if not midi_connect_from(Port, port_info):
            print("Got error, not connected")


Port = None

def run():
    global Port
    try:
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
