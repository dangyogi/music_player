# alsa_test.py

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
Use_master = False
Tag = 117

def init(connect_to=None):
    r'''Creates client and output (read) port.
    '''
    midi_init("alsa-timer")
    if Use_master:
        midi_create_input_port("input", connect_from=["Clock Master:Timer"])
        midi_process_fn(midi_process_clock_fn)
        midi_create_output_port("output", clock_master=True, connect_to=connect_to)
        midi_set_tag(Tag)
    else:
        midi_create_output_port("output", connect_to=connect_to)

def create_queue(ppq):
    global Queue, Ppq, Ppc
    Ppq = ppq
    Ppc = ppq // 24
    if Use_master:
        midi_set_ppq(ppq)
    else:
        Queue = midi_create_queue("alsa-timer queue", ppq)

def queue_set_tempo(beats_per_minute):
    global Secs_per_pulse
    trace(f"queue_set_tempo: {beats_per_minute=}")
    if not Use_master:
        print(f"  {Queue.get_tempo()=}")
    midi_set_tempo(beats_per_minute)
    Secs_per_pulse = 60 / (Ppq * beats_per_minute)
    if not Use_master:
        print(f"  {Queue.get_tempo()=}")

def queue_start():
    trace("queue start")
    midi_start()

def clock():
    trace("clock")
    midi_send_event(ClockEvent(tag=17), drain_output=True)  # works

def stop():
    trace("stop")
    midi_send_event(StopEvent(tag=47), drain_output=True)   # works
    #midi_send_event(MidiBytesEvent([0xFC], tag=47), drain_output=True)  # works

def send_continue():
    trace("send_continue")
    midi_send_event(ContinueEvent(), drain_output=True)   # works
    #midi_send_event(MidiBytesEvent([0xFB]), drain_output=True)  # works

def send_spp(song_position):
    trace("send_spp", song_position)
    midi_send_event(SongPositionPointerEvent(15, song_position), drain_output=True)   # works
    #lsb = song_position & 0x7F
    #msb = song_position >> 7
    #midi_send_event(MidiBytesEvent([0xF2, lsb, msb]), drain_output=True)  # works

def control_change():
    trace("control_change")
    event = ControlChangeEvent(15, 1, 2, tag=47)
    print(f"{event.tick=}")
    midi_send_event(event, drain_output=True)  # works

def time_sig():
    trace("time_sig")
    midi_send_event(SystemEvent(0xFD, 42), drain_output=True)  # works
    #midi_send_event(MidiBytesEvent([0xFD, 42]), drain_output=True)  # doesn't work

def clock_test(secs):  # works
    start = tick_time()
    trace("clock_test starting at", start)
    for next in range(start + 10, start + secs * Ppq, Ppc):
        now = tick_time()
        if Secs_per_pulse * (next - now) > 0.005:
            sleep(Secs_per_pulse * (next - now) - 0.005)
        if tick_time() > next:
            trace(f"clock_test: slept too long! {tick_time()=}, {next=}")
        #trace(f"clock_test: sending Clock tick={next}, tag={Tag}")
        midi_send_event(ClockEvent(tick=next, tag=Tag), drain_output=True)

def timer_test(tick):
    trace("timer_test", tick)
    if Use_master:
        tag = Tag
    else:
        tag = 17
    #midi_send_event(ClockEvent(dest=SYSTEM_TIMER, tick=tick, tag=tag), drain_output=True) # doesn't work
    midi_send_event(ClockEvent(tick=tick, tag=tag), drain_output=True)  # works

def send_notes():
    trace("send_notes")
    #sleep(1)

    if not Use_master:
        #event_queue_id = Queue.queue_id
        #event_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
        event_queue_id = None  # no queue used, queue_id changed to 253 by ALSA

        send_queue_id = Queue.queue_id
        #send_queue_id = 14   # Produces ALSAError: Invalid argument with or without tick supplied
        #send_queue_id = None  # no queue used, queue_id changed to 253 by ALSA
        trace("using event_queue_id", event_queue_id, "send_queue_id", send_queue_id)

    start = tick_time()
    for i, note in enumerate(range(60, 65)):
        if False:
            trace("NoteOn", note)
            midi_send_event(
              # note, ch, velocity
              NoteOnEvent(note, 1, 40, queue_id=event_queue_id),
              drain_output=True)
            sleep(0.1)
            trace("NoteOff", note)
            midi_send_event(
              NoteOffEvent(note, 1, 0, queue_id=event_queue_id),
              drain_output=True)
            sleep(0.4)
        else:  # works
            trace("tick_time", tick_time())
            tick = Ppq*i + start + Ppq//2
            trace("NoteOn", note, "tick", tick)
            if Use_master:
                midi_send_event(
                  # note, ch, velocity
                  NoteOnEvent(note, 1, 40, tick=tick, tag=Tag))
                trace("NoteOff", note, "tick", tick+Ppq//2)
                midi_send_event(
                  NoteOffEvent(note, 1, 0, tick=tick+Ppq//2, tag=Tag),
                  drain_output=True)
            else:
                midi_send_event(
                  # note, ch, velocity
                  NoteOnEvent(note, 1, 40, queue_id=event_queue_id, tick=tick, tag=Tag),
                  queue=send_queue_id)
                trace("NoteOff", note, "tick", tick+Ppq//2)
                midi_send_event(
                  NoteOffEvent(note, 1, 0, queue_id=event_queue_id, tick=tick+Ppq//2, tag=Tag),
                  queue=send_queue_id,
                  drain_output=True)
            #sleep(1)

Last_time = 0
def tick_time():
    global Last_time
    ans = midi_tick_time()
    if (ans - Last_time) / Ppq >= 1:   # at 60 bpm -> 1 quarter note/sec
        trace("tick_time now", ans)
    Last_time = ans
    return ans

def sleep(secs):
    if Use_master:
        midi_pause(secs)
    else:
        time.sleep(secs)

def run_test():
    try:
        midi_set_verbose(True)
        init(["Clock Master:Input"] if Use_master else None)
        sleep(1)
        clock()
        send_spp(0x1234)  # 4660
        control_change()
        time_sig()

        create_queue(ppq=960)
        queue_set_tempo(beats_per_minute = 60)
        queue_start()
        if not Use_master:
            trace(f"{tick_time()=}")
        sleep(0.5)
        trace(f"{tick_time()=}")
        clock_test(1)
        trace(f"{tick_time()=}")
        stop()
        sleep(0.5)
        send_continue()
        timer_test(tick_time() + 3000)
        trace(f"{tick_time()=}")
        send_notes()
        trace(f"{tick_time()=}")
        sleep(6)
        trace(f"{tick_time()=}")
    finally:
        midi_close()


def run():
    global Use_master

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--master', '-m', action="store_true", default=False)

    args = parser.parse_args()

    Use_master = args.master

    run_test()



if __name__ == "__main__":
    run()
