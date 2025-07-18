# clock_master.py

r'''This is a Midi Beat Clock Master, that accepts a CC command to change tempo.

It can also act as a pass-through to create queues for remote ALSA computers that can set the 'tick'
parameter on events to get them queued on the dest computer by this app.

It has an inout "Timer" port that is forwarded to 0:0.  It can receive Start, Stop, Continue and SPP
messages, which it forwards to 0:0 along with it's Clock events.  It can also receive a CC
command to change tempo.

    grok says mainstream music ranges from 60-180 bpm, slowest and fastest seen are 16-1015
       La_Campanella max tempo is 156 (quarter notes/min)
    grok says just noticable difference in bpm is 1-2%, stated at 1.5%.
    1.015^127 would give 30-200

It automatically creates a port for each 'Net Client' (aseqnet) and connects to it.  A CC command from
that client can set the ppq for the queue (default 480, data byte * 24 is ppq).  This port is inout,
receiving remote events and forwarding them from the queue.

Need:
    
    - alsa_midi layer
    - queue/clock/pause
    - received CC processing
    - CC recording/replay (based on midi beat time) (midi file?)
    - note output


Beat clock master:
    - uses queues for all output
      - queue at 24 ppq for clock events
      - output port for clock events
    - System Common to change tempo
      - changes beat clock queue and all pass-through queues
    - queues all messages received
      - different queue for each source
        - queue matches tempo to master beat clock
      - client name for aseqnet (both server and client) is 'Net Client'
      - args or CC to set up
        - source port (client:port) (on the local computer -- source on remote is not available)
          - default all ports
        - ppq
        - dest port name
          - default "pass-through"
      - events must have 'tick' set in remote host app
'''

import math
import time

from .tools.midi_utils import (
    midi_init, midi_close,
    midi_create_queue, midi_create_output_port, midi_create_input_port, midi_create_port,
    midi_process_fn, midi_send_event, midi_drain_output, midi_pause,

    EventType, PortCaps,

    Tempo_status, Time_sig_status, Clock_master_channel, Clock_master_ppq_param,
    data_to_ppq, data_to_bpm, midi_queue_time,
)

# Midi beat clock commands:
#
#   tempo must be set before "start" given.
#
#   System Real Time have high order bit of channel set.  These have no data bytes.
#   0xF8 - Clock; std 24 pulses (clock messages) per quarter note
#   0xFA - Start; slave starts at next Clock message, always at SPP 0; ignore if already running
#   0xFB - Continue; preserve SPP; ignore if already running
#   0xFC - Stop; ignore if already stopped
#   <there are two undefined System Real Time messages: 0xF9 and 0xFD>
#
#   System Common have high order bit of channel cleared.  These generally have data bytes.
#   0xF2 - SPP + 2 bytes as 14-bit value LSB first == midi beats (beat == 6 clocks, or a 16th note) 
#                since the start of song.  Should not be sent while devices are in play.  Use Continue
#                to start playing (Start resets SPP to 0).
#   <there are two undefined System Common messages: 0xF4 and 0xF5, both allow data bytes>
#   0xF4: Tempo
#   0xF5: Time_sig


Queues = {}
Queue_running = False
Clock_queue = None
Timer_port = None        # write
Output_port = None       # write
Immediate_port = None    # RW, no subs
Bpm = None
Pulses_per_clock = 20
Clock_ppq = 24 * Pulses_per_clock
Latency = 0.005          # keep enough Clocks queued to cover this time
Latency_in_ticks = None
Secs_per_tick = None     # Secs_per_clock is 0.0125 at 200 bpm, 0.0833 at 30 bpm
Min_stop_period = 0.02   # min period (secs) that queue can stopped before start/continue to give time
                         # for the Clock queue to drain.
Last_clock_tick_sent = None

def init():
    r'''Initializes midi, creates "Clock" queue and "Input", "Timer" and "Output" ports.
    '''
    global Timer_port, Output_port

    midi_init("Clock Master")
    Clock_queue = midi_create_queue("Clock", Clock_ppq, default=False)
    Queues["Clock"] = Clock_queue
    midi_create_input_port("Input", connect_from="Net Client")
    Immediate_port = midi_create_port("Immediate", caps=PortCaps.READ | PortCaps.WRITE, default=False)
    Timer_port = midi_create_output_port("Timer", default=False)
    Output_port = midi_create_output_port("Output", default=False)
    midi_process_fn(process_event)

def process_event(event):
    drain_output = False
    if event.type in Event_fns:
        if Event_fns[event.type](event):
            drain_output = True
    else:
        send_event(event)
        drain_output = True
    return drain_output

def send_event(event, port=None, drain_output=False):
    r'''Send event out of clock-master.  Port defaults to Output_port.

    drain_output needs to be done after the call if the drain_output param is False.

    Returns nothing.
    '''
    if port is None:
        port = Output_port
    if event.tag and event.tick:
        # send through queue
        if event.tag in Queues:
            midi_send_event(event, queue=Queues[event.tag], port=port, drain_output=drain_output)
            return
        print(f"process_event: {event.tag=} not in Queues -- forwarding direct")
    midi_send_event(event, port=port, drain_output=drain_output)

def queue(event):
    r'''Returns True if queued.  Will show up again later on Immediate_port.

    drain_output needs to be called if True returned.
    '''
    if event.dest != Immediate_port.port_id and event.tag and event.tick:
        # send through queue
        if event.tag in Queues:
            midi_send_event(event, queue=Queues[event.tag], port=Immediate_port, dest=Immediate_port)
            return True
        print(f"process_event: {event.tag=} not in Queues -- forwarding direct")
    return False

def process_start(event):
    r'''No queuing.
    '''
    global Last_clock_tick_sent
    for queue in Queues.values():
        queue.start()
    Last_clock_tick_sent = None
    midi_send_event(event, port=Timer_port)
    return True

def process_continue(event):
    r'''No queuing.
    '''
    for queue in Queues.values():
        queue.continue_()
    midi_send_event(event, port=Timer_port)
    return True

def process_stop(event):
    r'''May be queued.
    '''
    #global Last_clock_tick_sent
    if not queue(event):
        for queue in Queues.values():
            queue.stop()
        midi_send_event(event, port=Timer_port, drain_output=True)
        #now = midi_queue_time(Clock_queue)
        #if Last_clock_tick_sent > now:
        #    Last_clock_tick_sent = now
    return False

def process_songpos(event):
    if not queue(event):
        midi_send_event(event, port=Timer_port)
    return True

def process_system(event):
    r'''Tempo (0xF4) and Time_sig (0xF5)

    May be queued.
    '''
    global Bpm

    if not queue(event):
        if event.event == Tempo_status:
            Bpm = bpm = data_to_bpm(event.result)
            recalc_clock()
            for queue in Queues.values():
                queue.set_tempo(bpm=bpm, ppq=queue.ppq_setting)
        #elif event.event == Time_sig_status:
        midi_send_event(event, port=Timer_port)
    return True

def process_control_change(event):
    r'''Set ppq for tag

    No queuing done on ppq.
    '''
    if event.channel == Clock_master_channel:
        if event.param == Clock_master_ppq_param:
            # No queuing done on this.
            queue = midi_create_queue(f"Q-{event.tag}", data_to_ppq(event.value), default=False)
            Queues[event.tag] = queue
            return False
    send_event(event)  # this is for somebody else...
    return True

Event_fns = {
    EventType.START: process_start,
    EventType.CONTINUE: process_continue,
    EventType.STOP: process_stop,
    EventType.SONGPOS: process_songpos,
    EventType.SYSTEM: process_system,
    EventType.CONTROLLER: process_control_change,
}

def recalc_clock():
    global Secs_per_tick, Latency_in_ticks
    Secs_per_tick = 60 / (Bpm * Clock_ppq)
    Latency_in_ticks = int(math.ceil(Latency / Secs_per_tick))


def send_clocks():
    global Last_clock_tick_sent

    while True:
        if Queue_running:
            current_tick = midi_queue_time(Clock_queue)
            if Last_clock_tick_sent is None:
                start = 0
            else:
                start = Last_clock_tick_sent + Pulses_per_clock
            ticks_remaining = start - current_tick
            if ticks_remaining < 0:
                print(f"send_clocks: behind by {-ticks_remaining} ticks")
            drain_needed = False
            for tick in range(start, current_tick + Latency_in_ticks + 1, Pulses_per_clock):
                Last_clock_tick_sent = tick
                midi_send_event(ClockEvent(relative=False, tick=tick),
                                queue=Clock_queue, port=Timer_port)
                drain_needed = True
            if drain_needed:
                midi_drain_output()
            # min next tick is:
            #   Last_clock_tick_sent + Pulses_per_clock == current_tick + Latency_in_ticks + 1
            wakeup_tick = Last_clock_tick_sent + Pulses_per_clock - Latency_in_ticks
            # so tick_pause is >= 1
            tick_pause = wakeup_tick - current_tick
            if tick_pause <= 0:
                print(f"send_clocks got {tick_pause=} <= 0")
            else:
                midi_pause(tick_pause * Secs_per_tick)
        else:
            midi_pause()

def run():
    try:
        init()
        time.sleep(1)
        send_clocks()
    finally:
        midi_close()



if __name__ == "__main__":
    run()

