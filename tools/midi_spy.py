# midi_spy.py

import selectors

from alsa_midi import SequencerClient, PortCaps, EventType, SYSTEM_TIMER, SYSTEM_ANNOUNCE, ALSAError

Sel = selectors.DefaultSelector()

def get_midi_events():
    # w/false, often 0, but there's still an event.
    # w/True, always at least 1, but often more
    #start_time = time.time()
    num_pending = client.event_input_pending(True)
    #pending_time = time.time()
    #print("pending", pending_time - start_time)
    #print(f"midi_spy.get_midi_events, {num_pending=}")
    for i in range(1, num_pending + 1):
        #print("reading", i)
        event = client.event_input()
        #input_time = time.time()
        #print("input", input_time - pending_time)
        print("source", event.source, event,
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
            print(f"{event.addr=}, {event.flags=}")
            connect_from(event.addr)

def connect_from(addr):
    print(">>>>>>>>>>> connect_from", addr)
    try:
        port.connect_from(addr)
    except ALSAError as e:
        print("Got error, not connected")

def register_read(file, read_fn):
    Sel.register(file, selectors.EVENT_READ, read_fn)

def wait(time=None):
    for sk, sel_event in Sel.select(time):
        sk.data()

#print(dir(EventType))
#print(help(EventType))

client = SequencerClient("midi_spy")
print(f"{client.client_id=}")
#print(f"{client.get_client_info()=}")
#print(f"{client.get_client_pool()=}")

#print(dir(client))
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

register_read(client._fd, get_midi_events)

port = None
queue = None

try:
    port = client.create_port("notes", PortCaps.WRITE | PortCaps.SUBS_WRITE)  # FIX: close?
    connect_from(SYSTEM_ANNOUNCE)
    connect_from(SYSTEM_TIMER)
    for x in client.list_ports():
        if x.client_id != client.client_id:
            connect_from(x)

    # print(dir(port))
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

    # print(f"{dir(port.get_info())=}")
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
    if port is not None:
        port.close()
    if queue is not None:
        queue.close()
    client.close()
