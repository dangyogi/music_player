# alsa_timer.py

import time

from alsa_midi import SequencerClient, PortCaps, PortType, NoteOnEvent, NoteOffEvent, EventType


# Works with queue specified here, but not in event.  Queue_id set in event by ALSA.
# Also works with queue specified in event, but not here.  Seems to be interchangable...
#
# Invalid queue_id in either location raises ALSAError: Invalid argument
#
def send(event, queue=None):
    client.event_output(event, queue=queue, port=port)

def drain_output():
    client.drain_output()


client = SequencerClient("alsa_timer tool")
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
# get_port_info
# get_queue
# get_queue_info
# get_queue_status
# get_sequencer_name
# get_sequencer_type
# get_system_info
# list_ports
# query_named_queue
# set_client_info
#help(client.get_port_info)

port = None
queue = None

try:
    beats_per_minute = 60
    ticks_per_quarter_note = 12
    print(f"{beats_per_minute=}, {ticks_per_quarter_note=}")

    queue = client.create_queue("alsa_timer queue")
    #help(client.create_queue)
    #
    # name
    # info: QueueInfo: queue, name, owner, locked, flags

    print(f"{queue.queue_id=}")
    #print(f"{queue.control=}")
    #print(f"{queue.get_info()=}")
    #print(f"{queue.get_status()=}")
    #print(f"{queue.get_tempo()=}")
    #print(f"{queue.get_timer()=}")
    #print(f"{queue.get_usage()=}")

    #print(dir(queue))
    # 
    # control(EventType, value=0)  # sends queue control event
    # get_info
    # get_status
    # get_tempo
    # get_timer
    # get_usage
    # queue_id
    # set_info
    # set_tempo
    # set_timer
    # set_usage
    # start
    # stop

    # print(f"{dir(queue.get_info())=}")
    #
    # flags
    # locked
    # name
    # owner
    # queue_id

    queue.set_tempo(int(60.0 * 1000000 / beats_per_minute), ticks_per_quarter_note)


    port = client.create_port("notes", PortCaps.READ | PortCaps.SUBS_READ
                            # This isn't necessary.  Not sure what it does...
                            # , timestamping=True, timestamp_real=False, timestamp_queue=queue
                             )
    #help(client.create_port)
    # type: PortType
    # timestamping: bool
    # timestamp_real: bool
    # timestamp_queue: queue

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

    print("queue start")
    queue.start()
    #queue.control(EventType.START)
    drain_output()  # necessary to start immediately with either approach!!

    #time.sleep(1)

    #event_queue_id = queue.queue_id
    #event_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
    event_queue_id = None  # no queue used, queue_id changed to 253 by ALSA

    send_queue_id = queue.queue_id
    #send_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
    #send_queue_id = None  # no queue used, queue_id changed to 253 by ALSA
    print("using event_queue_id", event_queue_id, "send_queue_id", send_queue_id)

    for i, note in enumerate(range(60, 65)):
        if False:
            print("NoteOn", note)
            send(NoteOnEvent(note, 1, 40, queue_id=event_queue_id, relative=False))  # note, ch, velocity
            # tick, relative, queue_id

            drain_output()
            time.sleep(0.1)
            print("NoteOff", note)
            send(NoteOffEvent(note, 1, 0, queue_id=event_queue_id, relative=False))
            drain_output()
            time.sleep(0.4)
        else:
            print("tick_time", queue.get_status().tick_time)
            tick = 12*i + 6
            print("NoteOn", note, "tick", tick)
            send(NoteOnEvent(note, 1, 40,  # note, ch, velocity
                             queue_id=event_queue_id, relative=False, tick=tick)
                 , send_queue_id
                )
            # tick, relative, queue_id

            #drain_output()
            #time.sleep(0.1)
            print("NoteOff", note, "tick", tick+6)
            send(NoteOffEvent(note, 1, 0,
                              queue_id=event_queue_id, relative=False, tick=tick+6)
                 , send_queue_id
                )
            drain_output()
            time.sleep(1)

    print(f"{queue.get_status()=}")

finally:
    if port is not None:
        port.close()
    if queue is not None:
        queue.close()
    client.close()
