# queue_start_test.py

# Results:
#
#   stop: does not clear the queue of undelivered events or change the tick value.  The queue no longer
#         increments tick, and so does not deliver future events on the queue until continued, but will
#         still immediately deliver events with tick <= current tick while stopped.
#   start: clears the queue of any undelivered events and sets tick to 0.
#   continue: resumes the tick counter, now delivering future events that were queued prior to, or
#         during, stop.

import time

from midi_utils import *


def init():
    midi_init("queue_start_test")
    midi_create_output_port("output")
    midi_create_queue("q", 12)
    midi_set_tempo(60)

def test(start=False):
    trace("midi_queue_status", midi_queue_status())
    trace("midi_tick_time", midi_tick_time())
    trace("midi_start")
    midi_start()
    trace("midi_queue_status", midi_queue_status())    # tick 0
    trace("midi_tick_time", midi_tick_time())
    trace("queuing 2 notes (4 events, ticks=6,12,18,24)")
    midi_send_event(NoteOnEvent(60, 1, 40, tick=6))
    midi_send_event(NoteOffEvent(60, 1, 0, tick=12))
    midi_send_event(NoteOnEvent(61, 1, 40, tick=18))                     # never shows up w/start
    midi_send_event(NoteOffEvent(61, 1, 0, tick=24), drain_output=True)  # never shows up w/start
    trace("midi_queue_status", midi_queue_status())    # tick 0
    trace("midi_tick_time", midi_tick_time())
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())    # tick 13
    trace("midi_tick_time", midi_tick_time())
    trace("midi_stop")
    midi_stop()
    trace("midi_queue_status", midi_queue_status())    # tick 13
    trace("midi_tick_time", midi_tick_time())
    trace("queuing 2 notes (4 events, ticks=0,1,13,14)")
    midi_send_event(NoteOnEvent(62, 1, 40, tick=0))    # shows up immediately
    midi_send_event(NoteOffEvent(62, 1, 0, tick=1))    # shows up immediately
    midi_send_event(NoteOnEvent(63, 1, 40, tick=13))   # shows up immediately
    midi_send_event(NoteOffEvent(63, 1, 0, tick=14), drain_output=True)  # never shows up w/start
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())    # tick 13
    trace("midi_tick_time", midi_tick_time())
    if start:
        trace("midi_start")
        midi_start()
    else:
        trace("midi_continue")
        midi_continue()
    trace("midi_queue_status", midi_queue_status())    # tick start: 0, continue: 13
    trace("midi_tick_time", midi_tick_time())
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())    # tick start: 13, continue: 26
    trace("midi_tick_time", midi_tick_time())

def run(start):
    try:
        init()
        test(start)
    finally:
        midi_close()



if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', '-s', action="store_true", default=False)
    args = parser.parse_args()
    run(args.start)
