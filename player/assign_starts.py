# assign_starts.py

from fractions import Fraction


# measures have:
#
#   attributes, direction, backup, forward, note, barline
#
#   This module doesn't care about direction or barline.
#
#   attributes have divisions, staves, key and time (beats, beat_type)
#   backup/forward have duration
#
# notes have (of interest here):
#
#   rest, cue, grace (no duration), chord, duration, voice, time_modification
#
#   chord is not set on first note of the chord.  So don't count duration on chord notes.
#
#   time_modification: actual-notes (e.g., 3), normal-notes (e.g, 2)

# attributes.divisions

Quarter_note = Fraction(1, 4)

Note_fraction = {  # the ratio of each note type to a quarter note
   'whole': 4,
   'half': 2,
   'quarter': 1,
   'eighth': Fraction(1, 2),
   '16th': Fraction(1, 4),
   '32nd': Fraction(1, 8),
   '64th': Fraction(1, 16),
   '128th': Fraction(1, 32),
   '256th': Fraction(1, 64),
}

Measure_start = 0

class assign_measure:
    r'''Acts like a function, but provides a bucket for measure-level variables.

    All methods are only used by __init__.

    Assigns the following to measure:
        index - 0 relative index into measures
        key - attributes.key
        tempo - direction.tempo
        volume - direction.volume
        dynamics - direction.direction_type.dynamics
        sorted_notes - notes sorted by ascending start, decending midi_note
        divisions - brought out in the measure declaring attributes.divisions
        divisions_per_16th - brought out in the measure declaring attributes.divisions
        time - brought out in the measure declaring attributes.time as (beats, beat_type)
        divisions_per_measure - brought out in the measure declaring both divisions and time
        start - start of measure in divisions from the start of the part.
        start_spp - start of measure in song position pointer (16th notes)
        duration - duration of measure (greatest note stop time)

    Also assigns the following to notes (that are not ignored):
        start - start of note in divisions from the start of the measure.
    '''
    def __init__(self, measure, index, time_modifications=False, trace=None, trace_no_print=False):
        self.trace = trace
        self.measure = measure
        self.number = str(measure.number)
        self.measure.index = index
        self.time_modifications = time_modifications
        self.trace_no_print = trace_no_print
        if self.number == self.trace:
            print("measure", self.number)
        self.process_children()

    def process_children(self):
        global Measure_start
        self.start = 0
        self.last_start = 0
        self.longest = 0
        self.backup_num = 0
        self.forward_num = 0
        for child in self.measure.children:
            if child.name == 'attributes':
                if hasattr(child, 'divisions'):
                    self.assign_divisions(child.divisions)
                if hasattr(child, 'time'):
                    self.assign_time(child.time)
                if hasattr(child, 'key'):
                    self.measure.key = child.key
            elif child.name == 'direction':
                if hasattr(child, 'tempo'):
                    self.measure.tempo = child.tempo
                if hasattr(child, 'volume'):
                    self.measure.volume = child.volume
                if hasattr(child, 'direction_type'):
                    for direction_type in child.direction_type:
                        if direction_type.name == 'dynamics':
                            self.measure.dynamics = direction_type.value
            elif child.name == 'backup':
                self.backup_num += 1
                amount = child.duration
                if self.number == self.trace:
                    print(f"backup {self.backup_num} duration={amount}")
                if amount > self.start:
                    print(f"backup num {self.backup_num}, {amount}, in measure {self.number} "
                          f"> start, {self.start=}")
                    self.start = 0
                else:
                    self.start -= amount
                self.last_start = self.start
            elif child.name == 'forward':
                self.forward_num += 1
                amount = child.duration
                if self.number == self.trace:
                    print(f"forward {self.forward_num} duration={amount}")
                if self.start + amount > Divisions_per_measure:
                    print(f"forward num {self.forward_num}, {amount}, in measure {self.number} "
                          f"> Divisions_per_measure, {self.start=}")
                self.inc_start(amount)
            elif child.name == 'note':
                self.assign_start(child)
        if self.longest != Divisions_per_measure:
            print(f"Measure {self.number} has incorrect length.  "
                  f"Got {self.longest}, expected {Divisions_per_measure}")
        self.measure.start = Measure_start
        self.measure.start_spp = Measure_start // Divisions_per_16th
        self.measure.duration = self.longest
        Measure_start += self.measure.duration
        sorted_notes = [child for child in self.measure.children
                               if child.name == 'note' and not child.ignore]
        # ascending start, descending midi_note, descending duration
        sorted_notes.sort(key=lambda note: (note.start, -note.midi_note,
                                            -10000 if note.grace is not None
                                                   else -note.duration))
        start_len = len(sorted_notes)
        if self.number == self.trace:
            print(f"measure({self.number}) sorted_notes before de-dup:")
            for note in sorted_notes:
                print(f"  note {note.note}, midi_note={note.midi_note}, voice={note.voice}, "
                      f"start={note.start}, duration={note.duration}, tie={note.tie}")
        i = 0
        while i + 1 < len(sorted_notes):
            assert sorted_notes[i].start <= sorted_notes[i + 1].start, \
                   f"sorted_notes sort failed, measure={self.number}, note={sorted_notes[i].note}" \
                   f"first start={sorted_notes[i].start}, second start={sorted_notes[i + 1].start}"
            if sorted_notes[i].start == sorted_notes[i + 1].start:
                assert sorted_notes[i].midi_note >= sorted_notes[i + 1].midi_note, \
                       f"sorted_notes sort failed, measure={self.number}, note={sorted_notes[i].note}" \
                       f"first midi_note={sorted_notes[i].midi_note}, " \
                       f"second start={sorted_notes[i + 1].midi_note}"
                if sorted_notes[i].midi_note == sorted_notes[i + 1].midi_note:
                    assert sorted_notes[i].duration >= sorted_notes[i + 1].duration, \
                           f"sorted_notes sort failed, measure={self.number}, " \
                           f"note={sorted_notes[i].note}" \
                           f"first duration={sorted_notes[i].duration}, " \
                           f"second duration={sorted_notes[i + 1].duration}"
                    if sorted_notes[i].duration == sorted_notes[i + 1].duration:
                        print(f"process_children(measure={self.number}): "
                              f"two {sorted_notes[i].note} notes "
                              f"with same start={sorted_notes[i].start} "
                              f"and duration={sorted_notes[i].duration}")
                    del sorted_notes[i + 1]
                    continue
            i += 1
        end_len = len(sorted_notes)
        if start_len != end_len:
            print(f"process_children(measure={self.number}): deleted {start_len - end_len} dup notes")
        self.measure.sorted_notes = sorted_notes
        if self.number == self.trace:
            print(f"measure({self.number}) sorted_notes after de-dup:")
            for note in sorted_notes:
                print(f"  note {note.note}, midi_note={note.midi_note}, voice={note.voice}, "
                      f"start={note.start}, duration={note.duration}, tie={note.tie}")
        return 

    def assign_divisions(self, divisions):
        global Divisions, Divisions_per_16th
        if Divisions is not None and self.trace:
            print(f"Divisions reassigned in measure {self.number} "
                  f"from {Divisions} to {divisions}")
        Divisions = divisions
        self.measure.divisions = Divisions      # divisions per quarter note
        if divisions % 4 != 0:
            raise AssertionError(f"divisions, {divisions}, not multiple of 4 for SPP "
                                 f"in measure {self.number}")
        Divisions_per_16th = Divisions // 4
        self.measure.divisions_per_16th = Divisions_per_16th
        if self.trace:
            print("Got Divisions", Divisions, "in measure", self.number)
        if Time is not None:
            self.assign_divisions_per_measure()

    def assign_time(self, time):
        global Time
        new_time = (time.beats, time.beat_type)
        if Time is not None and self.trace:
            print(f"Time reassigned in measure {self.number} from {Time} to {new_time}")
        Time = new_time
        self.measure.time = Time
        if self.trace:
            print(f"assign_time got time {time.beats}/{time.beat_type}, set {Time=}, "
                  f"in measure {self.number}")
        if Divisions is not None:
            self.assign_divisions_per_measure()

    def assign_divisions_per_measure(self):
        global Divisions_per_measure
        Divisions_per_measure = Divisions * (Fraction(*Time) / Quarter_note)
        self.measure.divisions_per_measure = Divisions_per_measure
        if self.trace:
            print("Divisions_per_measure set to", Divisions_per_measure)

    def assign_start(self, note):
        if hasattr(note, "start"):
            print("Note", note.note, "already has start in measure", self.number)
        print_object = ""
        if hasattr(note, "print_object"):
            if note.print_object != 'no':
                print("got note with print-object != 'no'", note.print_object, "in measure", self.number)
            if self.trace_no_print:
                if note.rest:
                    print("got rest note with print-object", note.print_object, 
                          "in measure", self.number)
                elif note.cue:
                    print("got cue note with print-object", note.print_object,
                          "in measure", self.number)
                elif note.grace:
                    print("got grace note with print-object", note.print_object,
                          "in measure", self.number)
                else:
                    print("got note", note.note, "with print-object", note.print_object,
                          "in measure", self.number)
            print_object = f" print_object={note.print_object}"
            if note.print_object == 'no':
                note.ignore = True
        if note.rest:
            if self.number == self.trace:
                print(f"rest voice={note.voice}, start={self.start}, "
                      f"duration={note.duration}{print_object}")
            self.inc_start(note.duration)
            note.ignore = True
            return
        if note.cue:
            if self.number == self.trace:
                print(f"Got cue note {note.note}, voice={note.voice} "
                      f"in measure {self.number}{print_object}")
            note.ignore = True
            return
        note.start = self.start
        if note.chord:
            note.start = self.last_start
            if self.number == self.trace:
                print(f"note {note.note} chord, voice={note.voice}, start={note.start}, "
                      f"duration={note.duration} doesn't count{print_object}")
        elif note.grace:
            if self.number == self.trace:
                print(f"note {note.note} grace, voice={note.voice}, start={note.start}, "
                      f"no duration{print_object}")
        else:
            duration = note.duration
            if note.time_modification is None:
                if self.number == self.trace:
                    print(f"note {note.note}, voice={note.voice}, start={note.start}, "
                          f"duration={duration}{print_object}")
            else:
                actual_notes = note.time_modification.actual_notes
                normal_notes = note.time_modification.normal_notes
                normal_duration = Note_fraction[note.type] * Divisions
                modification = Fraction(normal_notes, actual_notes)
                actual_duration = normal_duration * modification
                if actual_duration.denominator == 1:
                    actual_duration = actual_duration.numerator
                if self.time_modifications and self.number == self.trace:
                    print(f"got time_modification({actual_notes=}, {normal_notes=}) "
                          f"in measure {self.number}, {duration=}, {actual_duration=}")
                duration = actual_duration
                if self.number == self.trace:
                    print(f"note {note.note} {note.type}, voice={note.voice}, "
                          f"tuplet({normal_notes}/{actual_notes}) "
                          f"start={self.start}, duration={duration}{print_object}")
            self.inc_start(duration)

    def inc_start(self, amount):
        self.last_start = self.start
        self.start += amount
        if self.start.denominator == 1:  # ints have a numerator and denominator too!
            self.start = self.start.numerator
        if self.start > self.longest:
            self.longest = self.start


def assign_parts(parts, time_modification=False, trace=None, trace_no_print=False):
    global Divisions, Divisions_per_16th, Time, Divisions_per_measure, Measure_start
    for info, measures in parts:
        Divisions = Divisions_per_16th = Time = Divisions_per_measure = None
        Measure_start = 0
        for i, measure in enumerate(measures):
            assign_measure(measure, i, time_modification, trace, trace_no_print)
        part_duration = Measure_start / Divisions  # in beats (quarter notes)
        expected_duration = (i + 1) * Divisions_per_measure / Divisions
        print(f"Part {info.id}, {i + 1} measures, duration {part_duration} beats (quarter notes) -- "
              f"expected {expected_duration}")



if __name__ == "__main__":
    import argparse
    from parse_xml import parse
    from unroll_repeats import unroll_parts
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", "-m", metavar="MEASURE", default=None)
    parser.add_argument("--trace-no-print", "-n", action="store_true", default=False)
    parser.add_argument("--time-modifications", "-t", action="store_true", default=False)
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    parts = parse(args.musicxml_file)
    new_parts = unroll_parts(parts)
    assign_parts(new_parts, args.time_modifications, args.trace, args.trace_no_print)

