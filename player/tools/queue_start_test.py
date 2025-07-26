# queue_start_test.py

# Results:
#
#   stop: does not clear the queue of undelivered events or change the tick value.  The queue no longer
#         increments tick, and so does not deliver events on the queue until continued.
#   start: clears the queue of any undelivered events and sets tick to 0.
#   continue: resumes the tick counter, now delivering events that were queued prior to stop.

import time

from midi_utils import *


def init():
    midi_init("queue_start_test")
    midi_create_output_port("output")
    midi_create_queue("q", 12)
    midi_set_tempo(60)

def test(start=False):
    trace("midi_start")
    midi_start()
    trace("midi_queue_status", midi_queue_status())
    trace("queuing 2 notes (4 events)")
    midi_send_event(NoteOnEvent(60, 1, 40, tick=6))
    midi_send_event(NoteOffEvent(60, 1, 0, tick=12))
    midi_send_event(NoteOnEvent(61, 1, 40, tick=18))
    midi_send_event(NoteOffEvent(61, 1, 0, tick=24), drain_output=True)
    trace("midi_queue_status", midi_queue_status())
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())
    trace("midi_stop")
    midi_stop()
    trace("midi_queue_status", midi_queue_status())
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())
    if start:
        trace("midi_start")
        midi_start()
    else:
        trace("midi_continue")
        midi_continue()
    trace("midi_queue_status", midi_queue_status())
    trace("sleep(1.1)")
    time.sleep(1.1)
    trace("midi_queue_status", midi_queue_status())

def run():
    try:
        init()
        test(True)
    finally:
        midi_close()



if __name__ == "__main__":
    run()
