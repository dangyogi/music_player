# alsa_timer.py

import time

from .midi_utils import *

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


Queue = None
Ppq = None

def init():
    r'''Creates client and output (read) port.
    '''
    midi_init("alsa-timer")
    midi_create_output_port("output")

def create_queue(ppq):
    global Queue, Ppq
    Queue = midi_create_queue("alsa-timer queue", ppq)
    Ppq = ppq

def queue_set_tempo(beats_per_minute):
    print(f"queue_set_tempo: {beats_per_minute=}")
    print(f"  {Queue.get_tempo()=}")
    midi_set_tempo(beats_per_minute)
    print(f"  {Queue.get_tempo()=}")

def queue_start():
    print("queue start")
    midi_start()

def clock():
    print("clock")
    midi_send_event(ClockEvent(tag=17), drain_output=True)  # works

def stop():
    print("stop")
    midi_send_event(StopEvent(tag=47), drain_output=True)   # works
    #midi_send_event(MidiBytesEvent([0xFC], tag=47), drain_output=True)  # works

def send_continue():
    print("send_continue")
    midi_send_event(ContinueEvent(), drain_output=True)   # works
    #midi_send_event(MidiBytesEvent([0xFB]), drain_output=True)  # works

def send_spp(song_position):
    print("send_spp", song_position)
    midi_send_event(SongPositionPointerEvent(15, song_position), drain_output=True)   # works
    #lsb = song_position & 0x7F
    #msb = song_position >> 7
    #midi_send_event(MidiBytesEvent([0xF2, lsb, msb]), drain_output=True)  # works

def control_change():
    print("control_change")
    event = ControlChangeEvent(15, 1, 2, tag=47)
    print(f"{event.tick=}")
    midi_send_event(event, drain_output=True)  # works

def time_sig():
    print("time_sig")
    midi_send_event(SystemEvent(0xFD, 42), drain_output=True)  # works
    #midi_send_event(MidiBytesEvent([0xFD, 42]), drain_output=True)  # doesn't work

def clock_test(secs):  # works
    print("clock_test")
    start = midi_tick_time()
    for next in range(start + 10, start + secs * 1000, 10):
        now = midi_tick_time()
        if next - now > 5:
            time.sleep(0.001 * (next - now - 5))
        if midi_tick_time() > next:
            print(f"clock_test: slept too long! {midi_tick_time()=}, {next=}")
        midi_send_event(ClockEvent(tick=next), drain_output=True)

def timer_test(tick):
    print("timer_test", tick)
    #midi_send_event(ClockEvent(dest=SYSTEM_TIMER, tick=tick, tag=17), drain_output=True) # doesn't work
    midi_send_event(ClockEvent(tick=tick, tag=17), drain_output=True)  # works

def send_notes():
    print("send_notes")
    #time.sleep(1)

    #event_queue_id = Queue.queue_id
    #event_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
    event_queue_id = None  # no queue used, queue_id changed to 253 by ALSA

    send_queue_id = Queue.queue_id
    #send_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
    #send_queue_id = None  # no queue used, queue_id changed to 253 by ALSA
    print("using event_queue_id", event_queue_id, "send_queue_id", send_queue_id)

    start = midi_tick_time()
    for i, note in enumerate(range(60, 65)):
        if False:
            print("NoteOn", note)
            midi_send_event(
              # note, ch, velocity
              NoteOnEvent(note, 1, 40, queue_id=event_queue_id, relative=False),
              drain_output=True)
            time.sleep(0.1)
            print("NoteOff", note)
            midi_send_event(
              NoteOffEvent(note, 1, 0, queue_id=event_queue_id, relative=False),
              drain_output=True)
            time.sleep(0.4)
        else:  # works
            print("tick_time", midi_tick_time())
            tick = Ppq*i + start + Ppq//2
            print("NoteOn", note, "tick", tick)
            midi_send_event(
              # note, ch, velocity
              NoteOnEvent(note, 1, 40, queue_id=event_queue_id, relative=False, tick=tick),
              queue=send_queue_id)
            print("NoteOff", note, "tick", tick+Ppq//2)
            midi_send_event(
              NoteOffEvent(note, 1, 0, queue_id=event_queue_id, relative=False, tick=tick+Ppq//2),
              queue=send_queue_id,
              drain_output=True)
            #time.sleep(1)


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
        create_queue(ppq=1000)
        queue_set_tempo(beats_per_minute = 60)
        queue_start()
        print(f"{midi_tick_time()=}")
        time.sleep(0.5)
        print(f"{midi_tick_time()=}")
        clock_test(1)
        print(f"{midi_tick_time()=}")
        timer_test(midi_tick_time() + 3000)
        print(f"{midi_tick_time()=}")
        send_notes()
        print(f"{midi_tick_time()=}")
        time.sleep(5)
        print(f"{midi_tick_time()=}")
    finally:
        midi_close()



if __name__ == "__main__":
    run()

