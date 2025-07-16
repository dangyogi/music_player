# alsa_timer.py

import time

from alsa_midi import (
   SequencerClient, PortCaps, PortType, alsa,

   EventType, Address,
   NoteOnEvent, NoteOffEvent, SetQueueTempoEvent, SongPositionPointerEvent,
   ControlChangeEvent, SystemEvent,
   TimeSignatureEvent, StartEvent, ContinueEvent, StopEvent, ClockEvent,
   MidiBytesEvent
)

# Midi beat clock commands:
#
#   tempo defaults to 120 bpm, here "beat" in bpm means quarter note
#
#   0xF8 - Clock; std 24 pulses (clock messages) per quarter note
#   0xFA - Start; slave starts at next Clock message, always at SPP 0; ignore if already running
#   0xFB - Continue; preserve SPP; ignore if already running
#   0xFC - Stop; ignore if already stopped
#
#   0xF2 - SPP + 2 bytes as 14-bit value LSB first == midi beats (beat == 6 clocks, or a 16th note) 
#                since the start of song.  Should not be sent while devices are in play.  Use Continue
#                to start playing (Start resets SPP to 0).

System_timer = Address(0, 0)


# Works with queue specified here, but not in event.  Queue_id set in event by ALSA.
# Also works with queue specified in event, but not here.  Seems to be interchangable...
#
# Invalid queue_id in either location raises ALSAError: Invalid argument
#
def send(event, queue=None, port=None):
    if port is None:
        port = Port
    Client.event_output(event, queue=Queue, port=port)

def drain_output():
    Client.drain_output()


Client = None
Port = None
Queue = None

def init():
    r'''Creates Client, (read) Port, (output) Timer_port.
    '''
    global Client, Port, Timer_port

    Client = SequencerClient("alsa_timer tool")
    print(f"{Client.client_id=}")
    #print(f"{Client.get_client_info()=}")
    #print(f"{Client.get_client_pool()=}")

    #print(dir(Client))
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
    #help(Client.get_port_info)

    Port = Client.create_port("notes", PortCaps.READ | PortCaps.SUBS_READ
                            # This isn't necessary.  Not sure what it does...
                            # , timestamping=True, timestamp_real=False, timestamp_queue=Queue
                             )
    print(f"{Port.port_id=}")
    #help(Client.create_port)
    # type: PortType
    # timestamping: bool
    # timestamp_real: bool
    # timestamp_queue: queue

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
    #Timer_port = Client.create_port("Timer", PortCaps.READ | PortCaps.SUBS_READ)
    #print(f"{Timer_port.port_id=}")
    #Timer_port.connect_to(System_timer)

def create_queue():
    global Queue

    Queue = Client.create_queue("alsa_timer queue")
    print(f"{Queue.queue_id=}")
    #help(Client.create_queue)
    #
    # name
    # info: QueueInfo: queue, name, owner, locked, flags

    #print(f"{Queue.control=}")
    #print(f"{Queue.get_info()=}")
    #print(f"{Queue.get_status()=}")
    #print(f"{Queue.get_tempo()=}")
    #print(f"{Queue.get_timer()=}")
    #print(f"{Queue.get_usage()=}")

    #print(dir(Queue))
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

    # print(f"{dir(Queue.get_info())=}")
    #
    # flags
    # locked
    # name
    # owner
    # queue_id

def queue_set_tempo(beats_per_minute = 60, ticks_per_quarter_note = 12):
    print(f"queue_set_tempo: {beats_per_minute=}, {ticks_per_quarter_note=}")
    tempo = Queue.get_tempo()
    print(f"{tempo=}")
    Queue.set_tempo(int(60.0 * 1e6 / beats_per_minute), ticks_per_quarter_note)
    tempo = Queue.get_tempo()
    print(f"{tempo=}")

def queue_start(my_queue=False):
    print("queue start")
    if my_queue:
        Queue.start()
    else:
        #send(StartEvent(queue_id=alsa.SND_SEQ_QUEUE_DIRECT, dest=System_timer))
        Client.event_output(StartEvent(7, queue_id=alsa.SND_SEQ_QUEUE_DIRECT), port=Port)
        #send(MidiBytesEvent([0xFA], dest=System_timer))
        #Queue.control(EventType.START)
    drain_output()  # necessary to start immediately with either approach!!

def clock():
    print("clock")
    #send(ClockEvent(queue_id=alsa.SND_SEQ_QUEUE_DIRECT, dest=System_timer))
    #Client.event_output(ClockEvent(dest=System_timer), port=Port)
    #Client.event_output(ClockEvent(), port=Port)
    Client.event_output(MidiBytesEvent([0xF8]), port=Port)
    #Queue.control(EventType.CLOCK)
    drain_output()  # necessary to start immediately with either approach!!

def stop():
    print("stop")
    #send(StopEvent(queue_id=alsa.SND_SEQ_QUEUE_DIRECT, dest=System_timer))
    #Client.event_output(StopEvent(dest=System_timer), port=Port)
    #Client.event_output(StopEvent(), port=Port)
    Client.event_output(MidiBytesEvent([0xFC], tag=47), port=Port)
    #Queue.control(EventType.STOP)
    drain_output()  # necessary to start immediately with either approach!!

def send_continue():
    print("send_continue")
    #send(ContinueEvent(queue_id=alsa.SND_SEQ_QUEUE_DIRECT, dest=System_timer))
    #Client.event_output(ContinueEvent(dest=System_timer), port=Port)
    #Client.event_output(ContinueEvent(), port=Port)
    Client.event_output(MidiBytesEvent([0xFB]), port=Port)
    #Queue.control(EventType.CONTINUE)
    drain_output()  # necessary to start immediately with either approach!!

def send_spp(song_position):
    print("send_spp", song_position)
    #send(SongPositionPointerEvent(song_position, queue_id=alsa.SND_SEQ_QUEUE_DIRECT))
    #Client.event_output(SongPositionPointerEvent(15, song_position), port=Port)
    lsb = song_position & 0x7F
    msb = song_position >> 7
    Client.event_output(MidiBytesEvent([0xF2, lsb, msb]), port=Port)
    #Queue.control(EventType.SONGPOS)
    drain_output()  # necessary to start immediately with either approach!!

def control_change():
    print("control_change")
    #send(SongPositionPointerEvent(song_position, queue_id=alsa.SND_SEQ_QUEUE_DIRECT))
    event = ControlChangeEvent(15, 1, 2, tag=47)
    print(f"{event.tick=}")
    Client.event_output(event, port=Port)
    #Client.event_output(MidiBytesEvent([0xF2, lsb, msb]), port=Port)
    #Queue.control(EventType.SONGPOS)
    drain_output()  # necessary to start immediately with either approach!!

def time_sig():
    print("time_sig")
    Client.event_output(SystemEvent(0xFD, 42), port=Port)       # did work
    #Client.event_output(MidiBytesEvent([0xFD, 42]), port=Port)  # didn't work
    drain_output()  # necessary to start immediately with either approach!!

def clock_test(secs):
    print("clock_test")
    start = Queue.get_status().tick_time
    for next in range(start + 10, start + secs * 1000, 10):
        now = Queue.get_status().tick_time
        if next - now > 5:
            time.sleep(0.001 * (next - now - 5))
        Client.event_output(ClockEvent(queue_id=Queue.queue_id, tick=next), port=Port)
        drain_output()

def timer_test(tick):
    print("************************************ timer_test")
    timer_port = "0:0"
    #send(ClockEvent(), port=timer_port)
    #send(ClockEvent(0))
    send(ClockEvent(dest=System_timer, tick=tick))
    drain_output()

def send_notes():
    print("************************************ send_notes")
    #time.sleep(1)

    #event_queue_id = Queue.queue_id
    #event_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
    event_queue_id = None  # no queue used, queue_id changed to 253 by ALSA

    send_queue_id = Queue.queue_id
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
            print("tick_time", Queue.get_status().tick_time)
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


def close():
    if Port is not None:
        Port.close()
    if Queue is not None:
        Queue.close()
    if Client is not None:
        Client.close()

def run():
    try:
        init()
        time.sleep(1)
        clock()
        stop()
        send_continue()
        send_spp(0x1234)  # 4660
        control_change()
        time_sig()
        create_queue()
        queue_set_tempo(beats_per_minute = 60, ticks_per_quarter_note = 1000)
        queue_start(True)
        print(f"{Queue.get_status()=}")
        time.sleep(0.5)
        print(f"{Queue.get_status()=}")
        clock_test(1)
        print(f"{Queue.get_status()=}")
        timer_test(40)
        print(f"{Queue.get_status()=}")
        send_notes()
        print(f"{Queue.get_status()=}")
    finally:
        close()



if __name__ == "__main__":
    run()

