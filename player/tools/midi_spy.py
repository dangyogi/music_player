# midi_spy.py

import time
import selectors
from collections import Counter

from alsa_midi import SequencerClient, PortCaps, EventType, SYSTEM_TIMER, SYSTEM_ANNOUNCE, ALSAError

Sel = selectors.DefaultSelector()

Last_clock = 0
Err_counts = Counter()

def get_midi_events():
    # w/false, often 0, but there's still an event.
    # w/True, always at least 1, but often more
    #start_time = time.time()
    global Last_clock, Err_counts

    num_pending = Client.event_input_pending(True)
    #pending_time = time.time()
    #print("pending", pending_time - start_time)
    #print(f"midi_spy.get_midi_events, {num_pending=}")
    for i in range(1, num_pending + 1):
        #print("reading", i)
        event = Client.event_input()
        if event.type == EventType.CLOCK:
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
                # addr
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

def connect_from(addr):
    client_info = Client.get_client_info(addr.client_id)
    port_info = Client.get_port_info(addr)
    name = f"{client_info.name}({addr.client_id}):{port_info.name}({addr.port_id})"
    cap = port_info.capability
    #print(f"connect_from {name}, {cap=}")
    if (cap & PortCaps.READ) and (cap & PortCaps.SUBS_READ):
        print(">>>>>>>>>>> connecting from", name)
        try:
            Port.connect_from(addr)
        except ALSAError as e:
            print("Got error, not connected")

def register_read(file, read_fn):
    Sel.register(file, selectors.EVENT_READ, read_fn)

def wait(time=None):
    for sk, sel_event in Sel.select(time):
        sk.data()

#print(dir(EventType))
#print(help(EventType))

Client = SequencerClient("midi_spy")
print(f"midi_spy client_id={Client.client_id}")
#print(f"{Client.get_client_info()=}")
#print(f"{Client.get_client_pool()=}")

#print(dir(Client))
#
# client_id
# create_queue
# get_client_info
# get_client_pool
# get_named_queue
# get_queue
# get_queue_info
# get_queue_status
# get_sequencer_name
# get_sequencer_type
# get_system_info
# list_ports
# query_named_queue
# set_client_info

register_read(Client._fd, get_midi_events)

Port = None

def run():
    global Port
    try:
        Port = Client.create_port("notes", PortCaps.WRITE | PortCaps.SUBS_WRITE)  # FIX: close?
        connect_from(SYSTEM_ANNOUNCE)
        connect_from(SYSTEM_TIMER)
        for x in Client.list_ports():
            if x.client_id != Client.client_id:
                connect_from(x)

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
        # capability
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

        while True:
            wait()

    finally:
        Sel.close()
        if Port is not None:
            Port.close()
        Client.close()



if __name__ == "__main__":
    run()
