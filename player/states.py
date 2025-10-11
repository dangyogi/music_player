# states.py

r'''State machine for song_select, song_position_pointer, start, stop, continue events.
'''

import time
from pathlib import Path
from bisect import bisect_left

from .parse_xml import parse
from .unroll_repeats import unroll_parts
from .assign_starts import assign_parts

from .tools.midi_utils import *
from .tools import midi_utils

Verbose = False

Parts = None
Continue_spp = None
Channel = 0

class BackToTopException(WakeUpException):
    pass

class StartPlayingException(WakeUpException):
    def __init__(self, spp):
        super().__init__()
        self.spp = spp
        if Verbose:
            trace(f"StartPlayingException.__init__({spp=})")

class spp:
    r'''Finds the first note who's start is >= spp.

    This points to the first note to be played when Continue is done. 

    To do this, it has:
      - part_no     # index into Parts
      - measure_no  # index into measures
      - note_no     # index into measure.sorted_notes
    '''
    def __init__(self, spp_16ths):
        self.spp_16ths = spp_16ths         # spp in 16ths
        self.spp_clocks = spp_16ths * 6    # spp in clocks

    def __repr__(self):
        return f"<spp: {self.spp_16ths}>"

    @classmethod
    def create(cls, spp_16ths):
        spp = cls(spp_16ths)
        for part_no, (info, measures) in enumerate(Parts):
            spp.part_no = part_no
            if spp.spp_clocks < info.part_duration_clocks:
                first_measure = measures[0]
                i = spp.spp_clocks // first_measure.clocks_per_measure
                while i >= 0 and i < len(measures):
                    measure = measures[i]
                    if measure.start > spp.spp_clocks: 
                        # measure after spp
                        i -= 1
                    elif spp.spp_clocks >= measure.start + measure.duration_clocks:
                        # measure before spp
                        i += 1
                    else: # measure.start <= spp.spp_clocks < measure.start + measure.duration_clocks
                        spp.measure_no = i
                        if measure.start == spp.spp_clocks: 
                            spp.note_no = 0
                        else:
                            spp.note_no = bisect_left([note.start for note in measure.sorted_notes],
                                                      spp.spp_clocks)
                        if Verbose:
                            trace(f"spp.create({spp_16ths=}): part_no={spp.part_no}, "
                                  f"measure_no={spp.measure_no}, note_no={spp.note_no}")
                        return spp
        trace(f"{spp=} not found in song, largest spp is {Parts[0][1][-1].sorted_notes[-1].start}")
        return None


Song_dir = Path("/home/bruce/Documents/MuseScore4/Scores/")

Songs = [
    Song_dir.joinpath("Gladiolus_Rag_by_Scott_Joplin_1907.mxl"),
    Song_dir.joinpath("La_Campanella-fix.mxl"),
    Song_dir.joinpath("Weeping_Willow_-_Scott_Joplin_-_1903.mxl"),
] 


# Ch1_commands and Ch1_CC_commands map to State method names.

Ch1_commands = {      # Passed event
    EventType.START: "start",
    EventType.STOP: "stop",
    EventType.CONTINUE: "continue_",
    EventType.SONGPOS: "song_position_pointer",
    EventType.SONGSEL: "song_select",
}

Ch1_CC_commands = {   # Passed event.value
}


class BaseState:
    r'''These don't return anything.  Caller must eventually call midi_drain_output.
    '''
    def enter(self):
        pass

    def name(self):
        return self.__class__.__name__

    def switch(self, new_state, report=True):
        global State
        State = new_state
        if report:
            trace(f"{self.name()}.switch({State.name()})")
        State.enter()

    def back_to_top_switch(self, new_state):
        trace(f"{self.name()}.back_to_top_switch({new_state.name()})")
        self.switch(new_state, report=False)
        raise BackToTopException()

    def start_playing_switch(self, new_state, spp):
        trace(f"{self.name()}.start_playing_switch({new_state.name()})")
        self.switch(new_state, report=False)
        raise StartPlayingException(spp)

    def song_select(self, event):
        trace(f"{self.name()}.song_select: ignored")

    def song_position_pointer(self, event):
        trace(f"{self.name()}.song_position_pointer: ignored")

    # These last three arrive here from the exp console.  These will call midi_start/stop/continue,
    # but the events echoed back from the Clock_master do not come here.

    def start(self, event):
        trace(f"{self.name()}.start: ignored")

    def stop(self, event):
        trace(f"{self.name()}.stop: ignored")

    def continue_(self, event):
        trace(f"{self.name()}.continue_: ignored")

    def end_song(self, final_clock):
        trace(f"{self.name()}.end_song: ignored")


class No_song(BaseState):
    r'''Parts is None and Continue_spp is None.

    Note: enter() is never called on this state!
    '''
    def song_select(self, event):
        # event.value has song number
        global Parts, Start_spp, Continue_spp
        if event.value >= len(Songs):
            trace(f"No_song.song_select: unknown song number, {event.value=}")
            return False
        if Verbose:
            trace(f"Got song_select {event.value=} for {Songs[event.value]}")
        parts = parse(Songs[event.value])
        new_parts = unroll_parts(parts)
        assign_parts(new_parts)
        Parts = new_parts
        Start_spp = spp.create(0)
        Continue_spp = None
        first_measure = Parts[0][1][0]
        if Verbose:
            trace(f"song_select: sending time sig={first_measure.time}")
        midi_set_time_signature(*first_measure.time, port=Control_port)  # sends to Exp Console
        # FIX: send key signature?
        self.switch(New_song_state)

class SPP(No_song):
    def song_position_pointer(self, event):
        global Continue_spp
        event_spp = spp.create(event.value)
        if event_spp is None:
            trace(f"{self.name()}.song_position_pointer, {event.value} not found -- ignored")
            return False
        Continue_spp = event_spp
        trace(f"{self.name()}.song_position_pointer: set to {Continue_spp}")
        midi_spp(event.value)
        self.switch(Ready_state)

class New_song(SPP):
    r'''Parts is not None but Continue_spp is None.
    '''
    def start(self, event):
        trace(self.name(), "START")
        midi_start()      # needs midi_drain_output
        self.start_playing_switch(Running_state, Start_spp)

class Ready(SPP):
    r'''Parts is not None and Continue_spp is not None.
    '''
    def continue_(self, event):
        trace(self.name(), "CONTINUE")
        midi_continue()   # needs midi_drain_output
        self.start_playing_switch(Running_state, Continue_spp)

    def start(self, event):
        trace(self.name(), "START")
        midi_start()      # needs midi_drain_output
        self.start_playing_switch(Running_state, Start_spp)

class Paused(SPP):
    r'''Parts is not None but Continue_spp is None.
    '''
    def continue_(self, event):
        trace(self.name(), "CONTINUE")
        midi_continue()      # needs midi_drain_output
        # no StartPlayingException, continues where stop left off.
        self.switch(Running_state)

    def start(self, event):
        trace(self.name(), "START")
        midi_start()      # needs midi_drain_output
        self.start_playing_switch(Running_state, Start_spp)

class Running(BaseState):
    r'''Parts is not None but Continue_spp is None.
    '''
    def enter(self):
        global Continue_spp
        Continue_spp = None

    def stop(self, event):
        clocks_sent = midi_stop()      # needs midi_drain_output
        trace(self.name(), "STOP: clocks_sent", clocks_sent)
        #time.sleep(0.01)
        midi_send_event(ControlChangeEvent(Channel, 0x7B, 0)) # All Notes OFF (ignored w/sleep 0.01)
        #midi_send_event(ControlChangeEvent(Channel, 0x78, 0))  # Sound Off
        self.switch(Paused_state)

    def end_song(self, final_clock):
        trace(self.name(), "end_song: final_clock", final_clock)
        if final_clock:
            if Verbose:
                print(f"  calling midi_pause(to_clock={final_clock + 2})")
            midi_pause(to_clock=final_clock + 2)  # give queue a chance to drain before stopping it
            if Verbose:
                print(f"  midi_pause done: {midi_queue_time()=}")
        clocks_sent = midi_stop()
        print("  final_clock", final_clock)
        self.back_to_top_switch(New_song_state)


No_song_state = No_song()
New_song_state = New_song()
Ready_state = Ready()
Paused_state = Paused()
Running_state = Running()


State = No_song_state

def process_ch1_event(event):
    r'''Doesn't return anything.  Caller must eventually call midi_drain_output.
    '''
    # Playback settings: Start, Stop, Continue, SPP, End/Loop at, Song Select
    if event.type == EventType.CONTROLLER:
        if event.param not in Ch1_CC_commands:
            trace(f"process_ch1_event({event=}): unknown ch1 event.param, {event.param=:#X}, ignored")
            return
        method = Ch1_CC_commands[event.param]
        param = event.value
    else:
        if event.type not in Ch1_commands:
            trace(f"process_ch1_event({event=}): unknown ch1 event.type, {event.type=}, ignored")
            return
        method = Ch1_commands[event.type]
        param = event
    if Verbose:
        trace(f"states.process_ch1_event calling {method=} on {State.name()} with {param=}")
    getattr(State, method)(param)

