# states.py

r'''State machine for song_select, song_position_pointer, start, stop, continue events.
'''

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


class BackToTopException(WakeUpException):
    def __init__(self, drain_output, spp):
        super().__init__(drain_output)
        self.spp = spp


class BaseState:
    def enter(self):
        return False

    def name(self):
        return self.__class__.__name__

    def switch(self, new_state, report=True):
        global State
        State = new_state
        if report:
            trace(f"{self.name()}.switch({State.name()})")
        return State.enter()

    def backup_switch(self, new_state, spp):
        trace(f"{self.name()}.backup_switch({new_state.name()})")
        raise BackToTopException(self.switch(new_state, report=False), spp)

    def song_select(self, event):
        trace(f"{self.name()}.song_select: ignored")
        return False

    def song_position_pointer(self, event):
        trace(f"{self.name()}.song_position_pointer: ignored")
        return False

    # These last three arrive here from the exp console.  These will call midi_start/stop/continue,
    # but the events echoed back from the Clock_master do not come here.

    def start(self, event):
        trace(f"{self.name()}.start: ignored")
        return False

    def stop(self, event):
        trace(f"{self.name()}.stop: ignored")
        return False

    def continue_(self, event):
        trace(f"{self.name()}.continue_: ignored")
        return False


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
        midi_set_time_signature(*first_measure.time)
        # FIX: send key signature?
        return self.switch(New_song_state)

class SPP(No_song):
    def song_position_pointer(self, event):
        global Continue_spp
        spp = spp.create(event.value)
        if spp is None:
            trace(f"{self.name()}.song_position_pointer, {event.value} not found -- ignored")
            return False
        Continue_spp = spp
        trace(f"{self.name()}.song_position_pointer: set to {Continue_spp}, forwarding to Clock Master")
        event.dest = None
        midi_send_event(event, port=midi_utils.Clock_master_port)
        self.switch(Ready_state)
        return True

class New_song(SPP):
    r'''Parts is not None but Continue_spp is None.
    '''
    def start(self, event):
        trace(self.name(), "START")
        midi_start()
        self.backup_switch(Running_state, Start_spp)

class Ready(SPP):
    r'''Parts is not None and Continue_spp is not None.
    '''
    def continue_(self, event):
        trace(self.name(), "CONTINUE")
        midi_continue()
        self.backup_switch(Running_state, Continue_spp)

    def start(self, event):
        trace(self.name(), "START")
        midi_start()
        self.backup_switch(Running_state, Start_spp)

class Paused(SPP):
    r'''Parts is not None but Continue_spp is None.
    '''
    def continue_(self, event):
        trace(self.name(), "CONTINUE")
        midi_continue()
        # no BackToTopException, continues where stop left off.
        return self.switch(Running_state)

    def start(self, event):
        trace(self.name(), "START")
        midi_start()
        self.backup_switch(Running_state, Start_spp)

class Running(BaseState):
    r'''Parts is not None but Continue_spp is None.
    '''
    def enter(self):
        global Continue_spp
        Continue_spp = None
        self.run = True
        while self.run:
            # FIX: run here!
            pass
        return False

    def stop(self, event):
        trace(self.name(), "STOP")
        midi_stop()
        return self.switch(Paused_state)


No_song_state = No_song()
New_song_state = New_song()
Ready_state = Ready()
Paused_state = Paused()
Running_state = Running()


State = No_song_state

def process_ch1_event(event):
    # Playback settings: Start, Stop, Continue, SPP, End/Loop at, Song Select
    if event.type == EventType.CONTROLLER:
        if event.param not in Ch1_CC_commands:
            trace(f"process_ch1_event({event=}): unknown ch1 event.param, {event.param=:#X}, ignored")
            return False
        method = Ch1_CC_commands[event.param]
        param = event.value
    else:
        if event.type not in Ch1_commands:
            print(f"process_ch1_event({event=}): unknown ch1 event.type, {event.type=}, ignored")
            return False
        method = Ch1_commands[event.type]
        param = event
    if Verbose:
        trace(f"states.process_ch1_event calling {method=} on {State.name()} with {param=}")
    return getattr(State, method)(param)

