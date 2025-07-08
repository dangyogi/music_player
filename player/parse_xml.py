# parse_xml.py

from zipfile import ZipFile
from xml.etree.ElementTree import Element, parse, fromstring


container = 'META-INF/container.xml'

def as_class(cls, trace=False, show_props=True, dump=True):
    def factory(name, props):
        if trace and show_props:
            print(f"as_class({cls.__name__}): {name=}, {props=}")
        obj = cls(name, props, trace)
        if trace and dump and hasattr(obj, 'dump'):
            obj.dump(2)
        return name, obj
    return factory

class Attrs:
    r'''Converts hyphenated names to underscores.
    '''
    omit = frozenset("name child_num measure_number trace".split())

    def __init__(self, name, props, trace=False):
        self.trace = trace
        self.name = name
        for key, value in props.items():
            setattr(self, key.replace('-', '_'), value)

    def __repr__(self):
        return f"<Attrs({self.name}): {tuple(sorted(n for n in self.__dict__.keys() if n != 'name'))}>"

    def dump(self, indent=0):
        print(f"{' ' * indent}{self.name}:")
        for key, value in sorted(self.__dict__.items()):
            assert key[0] != '_'
            if key not in self.omit:
                print(f"{' ' * indent}  ", end='')
                if isinstance(value, (list, tuple)):
                    if hasattr(value[0], 'dump'):
                        print(f"{key}: [")
                        for x in value:
                            x.dump(indent + 4)
                        print(f"{' ' * indent}  ]")
                        continue
                if hasattr(value, 'dump'):
                    print(f"{key}:")
                    value.dump(indent + 4)
                else:
                    print(f"{key}: {value}")


class Parser:
    def __init__(self, name, package_fn, ignore=(), save=(), children=(),
                 list=False, one_child=False, trace=False):
        self.trace = trace
        self.name = name
        self.list = list
        self.one_child = one_child
        self.package_fn = package_fn  # passed: tag, dict of values
        self.ignore = frozenset(ignore)
        self.save = frozenset(save)
        self.children = {child.name: child for child in children}
        self.lists = frozenset(p.name for p in children if p.list)
        if self.trace:
            print(f"Parser({self.name}):")
            print("  ignore", self.ignore)
            print("  save", self.save)
            print("  children", self.children)
            print("  lists", self.lists)

    def parse(self, e):
        properties = {}
        def save(name, prop_name, value, msg):
            nonlocal properties, child_num
            if self.trace:
                print(f"  save({name}, {prop_name}, {value}, {msg})")
            if prop_name.startswith('attr-'):
                save_name = prop_name[5:]
            else:
                save_name = prop_name
            if name in self.lists:
                if isinstance(value, (Attrs, Measure, Note)):
                    value.child_num = child_num
                if name not in properties:
                    properties[save_name] = [value]
                elif not isinstance(properties[save_name], list):
                    raise RuntimeError(f"Parser({self.name}): {name} has non-list value, "
                                       f"{properties[save_name]} in properties")
                else:
                    properties[save_name].append(value)
            else:
                if name in properties:
                    print(f"Parser({self.name}): multiple values for {name}")
                else:
                    properties[save_name] = value

        if self.trace:
            print(f"Parser({self.name}):")
        child_num = 1
        saw_child = False
        for name, value in self.gen_children(e, 'text' in self.save):
            if self.trace:
                print(f"  got {child_num}: {name}={value}")
            if name in self.ignore:
                if self.trace:
                    print("    ignored")
                continue
            if self.one_child and saw_child:
                print(f"  got multiple children for {self.name}, one_child set")
            if name in self.save:
                save(name, name, self.get_value(value), "save")
            elif name in self.children:
                parse_ans = self.children[name].parse(value)
                if not isinstance(parse_ans, (list, tuple)):
                    print(f"Parser({self.name}): child({name}), got {parse_ans=!r}")
                prop_name, prop_value = parse_ans
                save(name, prop_name, prop_value, "child")
            else:
                if name.startswith('attr-'):
                    print("unknown attr", name[5:], "on", e.tag)
                elif name == 'text':
                    print("unknown text", repr(value), "on", e.tag)
                else:
                    print("unknown child tag", name, "on", e.tag)
            if not name.startswith('attr-') and name != 'text':
                child_num += 1
            saw_child = True
        if self.one_child:
            ans = self.name, properties.popitem()[1]
        else:
            ans = self.package_fn(e.tag, properties)
        if self.trace:
            print("parse returning:", ans)
        return ans

    def gen_children(self, e, force_text=False):
        yield from (('attr-' + name, value) for name, value in e.items())
        yield from ((child.tag, child) for child in e)
        if e.text and (e.text.strip() or force_text):
            yield 'text', e.text.strip()

    def get_value(self, x):
        if isinstance(x, Element):
            self.assert_empty(x)
            x = x.text
        try:
            return int(x)
        except ValueError:
            try:
                return float(x)
            except ValueError:
                return x

    def assert_empty(self, e):
        for name in e.keys():
            print("unknown attr", name, "on", e.tag)
        for child in e:
            print("unknown child tag", child.tag, "on", e.tag)


Score_instrument = Parser("score-instrument", as_class(Attrs),
                          save="attr-id instrument-name".split())

Midi_device = Parser("midi-device", as_class(Attrs),
                     save="attr-id attr-port".split())

Midi_instrument = Parser("midi-instrument", as_class(Attrs),
                         save="attr-id midi-channel midi-program volume pan".split())

Score_part = Parser("score-part", as_class(Attrs),
                    save="attr-id part-name part-abbreviation".split(),
                    children=(Score_instrument, Midi_device, Midi_instrument), 
                    list=True)

# Returns a dict of part_id: score_part
Part_list = Parser("part-list", lambda name, prop: (name, {sp.id: sp for sp in prop['score-part']}),
                   children=(Score_part,))

Key = Parser("key", as_class(Attrs),
             save="fifths mode".split())

Time = Parser("time", as_class(Attrs),
              save="beats beat-type".split())

Attributes = Parser("attributes", as_class(Attrs),
                    ignore="clef".split(),
                    save="divisions staves".split(),
                    children=(Key, Time),
                    list=True)

def as_prop(trace=False):
    def factory(name, prop):
        value = one_item(name, prop)[1]
        if trace:
            print(f"as_prop: {name=}, {prop=}, {value=}")
        return name, value
    return factory

Words = Parser("words", as_class(Attrs),
               ignore="attr-default-x attr-default-y attr-relative-x attr-relative-y "
                      "attr-font-weight attr-font-family attr-font-style attr-font-size".split(),
               save="text".split())

F = Parser("f", lambda name, prop: ('value', "f"))
MF = Parser("mf", lambda name, prop: ('value', "mf"))
FF = Parser("ff", lambda name, prop: ('value', "ff"))
FFF = Parser("fff", lambda name, prop: ('value', "fff"))
P = Parser("p", lambda name, prop: ('value', "p"))
MP = Parser("mp", lambda name, prop: ('value', "mp"))
PP = Parser("pp", lambda name, prop: ('value', "pp"))
PPP = Parser("ppp", lambda name, prop: ('value', "ppp"))

def one_item(name, prop):
    if len(prop) != 1:
        print(f"{name}: expected 1 prop, got", tuple(prop.keys()))
    return prop.popitem()

# value: p, mp, f, ...
Dynamics = Parser("dynamics", as_class(Attrs),
                  ignore="attr-default-x attr-default-y attr-relative-x attr-relative-y".split(),
                  children=(F, MF, FF, FFF, P, MP, PP, PPP))

# type: e.g., crescendo, diminuendo, stop; number: 1
Wedge = Parser("wedge", as_class(Attrs),
               save="attr-type attr-number".split(),
               ignore="attr-default-x attr-default-y attr-relative-x attr-relative-y".split())

# beat-unit: e.g., eighth; per-minute
Metronome = Parser("metronome", as_class(Attrs),
                   ignore="attr-parentheses attr-relative-x attr-relative-y "
                          "attr-default-x attr-default-y".split(),
                   save="beat-unit per-minute".split())

# type: e.g., down (raise size interval), stop (end of shift), up (lower size interval);
# size: e.g., 8 (one octave), 15 (two octaves)
# number: e.g., 1, 2, 3, 4 (don't know what this does???)
Octave_shift = Parser("octave-shift", as_class(Attrs),
                      ignore="attr-relative-x attr-relative-y attr-default-x attr-default-y".split(),
                      save="attr-type attr-size attr-number".split())

# type: e.g., start, stop; line: e.g., yes
Pedal = Parser("pedal", as_class(Attrs),
               ignore="attr-relative-x attr-relative-y attr-default-x attr-default-y".split(),
               save="attr-type attr-line".split())

# type: e.g., start, stop; number: e.g., 1; line-end: e.g., none; line-type: e.g., solid
# I don't see this showing up on the sheet music.  Not sure what it does??
Bracket = Parser("bracket", as_class(Attrs),
                 ignore="attr-relative-x attr-relative-y attr-default-x attr-default-y".split(),
                 save="attr-type attr-number attr-line-end attr-line-type".split())

# These only have one child each, so the children are directly gathered into the list.
Direction_type = Parser("direction-type", None,
                        children=(Words, Dynamics, Wedge, Metronome, Octave_shift, Pedal, Bracket),
                        list=True,
                        one_child=True)

def sound(name, prop):
    key, value = one_item(name, prop)
    if key == 'dynamics':
        return 'volume', value
    return key, value

# tempo: value or volume: value, you'll never see 'sound'!
Sound = Parser("sound", sound,
               save="attr-tempo attr-dynamics".split())

Direction = Parser("direction", as_class(Attrs),
                   save="attr-placement staff offset".split(),
                   children=(Direction_type, Sound),
                   list=True)

Notes = {
    'C': 0,  # first note of each octave
    'D': 2,
    'E': 4,
    'F': 5,
    'G': 7,
    'A': 9,
    'B': 11, # last not of each octave
}

def make_pitch(name, props):
    ans = Attrs(name, props)
    if not hasattr(ans, 'alter'):
        ans.alter = 0
    # alter is 1 for sharp.  Not sure what it is for flat.
    if ans.alter not in (-1, 0, 1, 2):
        print("make_pitch got unknown alter", ans.alter)
    ans.midi_note = Notes[ans.step] + 12*(ans.octave + 1) + ans.alter
    return name, ans

# Adds default alter=0, and midi_note
Pitch = Parser("pitch", make_pitch,
               save="step alter octave".split())

Chord = Parser("chord", lambda name, prop: (name, True))
Rest = Parser("rest", lambda name, prop: (name, True),
              ignore="display-step display-octave".split())

Dot = Parser("dot", lambda name, prop: (name, True))
Cue = Parser("cue", lambda name, prop: (name, True))

Tie = Parser("tie", lambda name, prop: (name, prop['type']),
             save="attr-type".split(),
             list=True)

Tied = Parser("tied", lambda name, prop: (name, prop['type']),
              save="attr-type".split(),
              list=True)

Slur = Parser("slur", as_class(Attrs),
              ignore="attr-placement".split(),
              save="attr-type attr-number".split())

Strong_accent = Parser("strong-accent", lambda name, prop: (name, prop['type']),
                       save="attr-type".split())

Staccato = Parser("staccato", lambda name, prop: (name, True))
Accent = Parser("accent", lambda name, prop: (name, True))
Detached_legato = Parser("detached-legato", lambda name, prop: (name, True))
Staccatissimo = Parser("staccatissimo", lambda name, prop: (name, True))
Tenuto = Parser("tenuto", lambda name, prop: (name, True))

Articulations = Parser("articulations", as_class(Attrs),
                       children=(Strong_accent, Accent, Staccato, Detached_legato, Staccatissimo,
                                 Tenuto))

Arpeggiate = Parser("arpeggiate", lambda name, prop: (name, True),
                    ignore="attr-default-x attr-default-y attr-relative-x attr-relative-y".split())

Fermata = Parser("fermata", lambda name, prop: (name, prop['type']),
                 save="attr-type".split())

Trill_mark = Parser("trill-mark", lambda name, prop: (name, True))

Ornaments = Parser("ornaments", as_class(Attrs),
                   children=(Trill_mark,))

Tuplet = Parser("tuplet", as_class(Attrs),
                save="attr-type attr-bracket attr-show-number".split())

Notations = Parser("notations", as_class(Attrs),
                   children=(Tied, Slur, Articulations, Arpeggiate, Fermata, Ornaments, Tuplet))

# (e.g., quarter, eighth, 16th)
Type = Parser("type", as_prop(),
              ignore="attr-size".split(),
              save="text".split())

Grace = Parser("grace", as_class(Attrs),
               save="attr-slash".split())

Time_modification = Parser("time-modification", as_class(Attrs),
                           save="actual-notes normal-notes".split())

class Note:
    note = None
    pitch = None
    chord = False
    rest = False
    dot = False
    cue = False
    tie = ()
    grace = None
    time_modification = None
    notations = None
    ignore = False

    # dynamics: volume e.g., 58.89
    # print-object: e.g., no (ignore these!)
    # duration: in quarter-note/divisions
    # voice: voice-number
    # staff: staff-number
    # pitch: step (note, e.g., C), octave, alter (added semitones), midi_note
    # type: duration, e.g., quarter, eighth, 16th
    # chord: True
    # rest: True
    # tie: e.g., start, stop; this is a list, so can have both
    # dot: True
    # cue: True
    # grace: slash (yes, or missing)
    #   grace notes don't have a duration and don't add to the rhythmic value of the measure
    #   a slash is played quickly before the main note
    #   otherwise, held longer, often on the beat, and may emphazied more strongly than the main note
    # time_modification: actual-notes (e.g., 3), normal-notes (e.g, 2) (see tuplet)
    # notations:
    #   tied: e.g., start, stop
    #   slur: type (e.g., start, stop), number (e.g, 1)
    #     slurs are only between two notes.  First note played slightly louder and smoothly (legato)
    #     into the second note, which is played slightly softer and shortened slightly.
    #   articulations:
    #     strong_accent: e.g., up, down
    #     accent, staccato, detached-legato, staccatissimo, tenuto (all True)
    #       detached-legato means middle ground between legato and staccato
    #       staccatissimo means shorter than normal staccato.
    #         indicated by an appostrophe above the note
    #       tenuto means play the note a bit early, a bit louder, and bit longer
    #         indicated by a short bar over the note
    #   arpeggiate: True (wavy line next to notes)
    #   fermata (hold): e.g., upright, inverted (below the note)
    #   ornaments: trill-mark (True)
    #   tuplet: type (e.g., start, stop), bracket (e.g., yes, no), show-number (e.g., none)
    #           the number of notes in the tuplet are played in the same amount of time as the
    #           length of the tuplet.
    #
    #           This is given in a time-modification showing the actual number
    #           of notes in the tuplet (actual_notes) vs the normal number of those size notes
    #           (normal_notes) in the same same time span.  This gives a precise adjustment to the
    #           note's duration.  The time-modification is duplicated in each note of the tuplet.
    #
    #           The duration of each note in the tuplet has this modification factored into it
    #           (normal duration * normal_notes/actual_notes), but the result is constrained to
    #           fit in an integer (not sure if it's rounded or truncated).

    def __init__(self, name, properties, trace=False):
        self.trace = trace
        self.name = name
        for key, value in properties.items():
            if key == 'pitch':
                if value.alter == 0:
                    self.note = f"{value.step}{value.octave}"
                elif value.alter > 0:
                    self.note = f"{value.step}{value.octave}+{value.alter}"
                elif value.alter < 0:
                    self.note = f"{value.step}{value.octave}{value.alter}"
                else:
                    print("note got unknown alter", value.alter)
                    self.note = f"{value.step}{value.octave}+?"
                self.midi_note = value.midi_note
            else:
                #if key == 'tie' and len(value) > 1:
                #    print(f"Note: got more than one tie: {value}")
                setattr(self, key.replace('-', '_'), value)
        if hasattr(self, 'type') and hasattr(self.type, 'size'):
            if self.type.size != 'cue':
                print(f"Note got type.size != cue, got {self.type.size} instead")
            if not self.cue:
                print(f"Note got type.size == cue, but no <cue/> element")

    def __repr__(self):
        if self.rest:
            return f"<Note({self.voice}) rest {self.duration}>"
        elif self.chord:
            return f"<Note({self.voice}) chord {self.note}({self.midi_note}) {self.duration}>"
        elif self.grace is not None:
            return f"<Note({self.voice}) {self.note}({self.midi_note}){self.get_grace_repr()}>"
        else:
            return f"<Note({self.voice}) {self.note}({self.midi_note}) {self.duration}>"

    def get_grace_repr(self):
        if self.grace is not None:
            if hasattr(self.grace, 'slash'):
                if self.grace.slash != "yes":
                    print(f"Note: has grace with slash, but not 'yes', instead got {self.grace.slash}")
                return " grace/"
            return " grace"
        return ""

    def dump(self, indent=0):
        print(f"{' ' * indent}Note(voice={self.voice}):", end='')
        if self.rest:
            print(f" rest {self.duration}", end='')
        if self.note is not None:
            print(f" {self.note}", end='')
        if self.grace is not None:
            print(self.get_grace_repr(), end='')
        else:
            print(f" {self.duration}", end='')
        if self.chord:
            print(" chord", end='')
        if self.tie:
            print(f" {self.tie=}", end='')
        print()

Notexml = Parser("note", as_class(Note),
              ignore="attr-default-x attr-default-y accidental stem beam".split(),
              save="attr-dynamics attr-print-object duration voice staff".split(),
              children=(Pitch, Type, Chord, Rest, Tie, Dot, Cue, Grace, Time_modification, Notations),
              list=True)

Backup = Parser("backup", as_class(Attrs),
                save="duration".split(),
                list=True)

Forward = Parser("forward", as_class(Attrs),
                 save="duration".split(),
                 list=True)

Repeat = Parser("repeat", lambda name, prop: (name, prop['direction']),
                save="attr-direction".split())

Ending = Parser("ending", as_class(Attrs),
                ignore="attr-default-x attr-default-y attr-relative-x attr-relative-y".split(),
                save="attr-number attr-type".split(),
               )

Barline = Parser("barline", as_class(Attrs),
                 save="attr-location bar-style".split(),
                 children=(Repeat, Ending),
                 list=True)

class Measure:
    repeat_forward = False
    repeat_backward = False
    ending_start = None  # ending number
    ending_stop = None   # ending number

    # number: measure number, starting at 1
    # attributes: divisions (per quarter note), staves
    #   key: fifths (positive for #sharps, negative for #flats),
    #        mode (e.g., major, minor, dorian, phrygian; default major for fifths >= 0, else minor)
    #   time: beats (e.g., 2), beat-type (e.g., 4)
    # direction: placement (e.g., above, below), staff, offset (in divisions), tempo, dynamics
    #   direction-type:
    # backup: duration (in divisions)
    # forward: duration (in divisions)
    # note: <see class Note>
    # barline: location (e.g., right, left)
    #   bar-style: light-light, light-heavy, heavy-light
    #     heavy-light on left
    #     light-light, light-heavy on right
    #   repeat: forward, backward
    #     forward: heavy-light bar-style
    #     backward: only in stop ending
    #   ending: number (e.g., 1, 2), type: start, stop
    #     start/stop brackets the ending, same number:
    #       start on left, no bar-style
    #       stop on right, stop also has light-light or light-heavy (w/repeat backward) bar-style
    #   light-light)

    def __init__(self, name, properties, trace=False):
        self.trace = trace
        self.name = name
        self.number = properties['number']
        children = []
        for type in "attributes direction backup forward note barline".split():
            if type in properties:
                for child in properties[type]:
                    child.measure_number = self.number
                    #if type == 'note' and hasattr(child, 'print_object') and child.print_object == 'no':
                    #    if trace:
                    #        print(f"Measure({self.number}): dropping {child}, has print-object == 'no'")
                    #    pass  # drop notes with print-object == 'no'
                    #else:
                    #    children.append(child)
                    children.append(child)
                    if type == 'barline':
                        if child.location == 'left':
                            if trace:
                                print(f"Measure({self.number}): got barline left")
                            if hasattr(child, "bar_style") and child.bar_style.startswith('light-'):
                                print(f"Measure({self.number}) got {child.bar_style} barline on left")
                            if hasattr(child, "repeat"):
                                if child.repeat == 'forward':
                                    if trace:
                                        print(f"Measure({self.number}): repeat_forward set")
                                    self.repeat_forward = True
                                elif child.repeat == 'backward':
                                    print(f"Measure({self.number}) got repeat backward barline on left")
                                else:
                                    print(f"Measure({self.number}) got unknown repeat {child.repeat} "
                                           "barline on left")
                            if hasattr(child, "ending"):
                                if child.ending.type == 'start':
                                    self.ending_start = child.ending.number
                                    if trace:
                                        print(f"Measure({self.number}): "
                                              f"ending_start = {self.ending_start}")
                                elif child.ending.type == 'stop':
                                    print(f"Measure({self.number}) got stop ending barline on left")
                                else:
                                    print(f"Measure({self.number}) got unknown ending type "
                                          f"{child.ending.type} barline on left")
                        elif child.location == 'right':
                            if trace:
                                print(f"Measure({self.number}): got barline right")
                            if hasattr(child, "bar_style") and child.bar_style == 'heavy-light':
                                print(f"Measure({self.number}) got heavy-light barline on right")
                            if hasattr(child, "repeat"):
                                if child.repeat == 'backward':
                                    if trace:
                                        print(f"Measure({self.number}): repeat_backward set")
                                    self.repeat_backward = True
                                elif child.repeat == 'forward':
                                    print(f"Measure({self.number}) got repeat forward barline on right")
                                else:
                                    print(f"Measure({self.number}) got unknown repeat {child.repeat} "
                                           "barline on right")
                            if hasattr(child, "ending"):
                                if child.ending.type == 'stop':
                                    self.ending_stop = child.ending.number
                                    if trace:
                                        print(f"Measure({self.number}): "
                                              f"ending_stop = {self.ending_stop}")
                                elif child.ending.type == 'start':
                                    print(f"Measure({self.number}) got start ending barline on right")
                                else:
                                    print(f"Measure({self.number}) got unknown ending type "
                                          f"{child.ending.type} barline on right")
                        else:
                            print(f"Measure({self.number}) got barline with "
                                  f"location {child.location}, expected left or right")
        self.children = sorted(children, key=lambda child: child.child_num)

    def dump(self, indent=0):
        print(f"{' ' * indent}Measure({self.number}):")
        for child in self.children:
            if isinstance(child, (tuple, list)):
                print(f"{' ' * indent}  Measure({self.number}): got list child: {type(child[0])=}")
            else:
                child.dump(indent + 2)

Measurexml = Parser("measure", as_class(Measure),
                    ignore="attr-width print".split(),
                    save="attr-number".split(),
                    children=(Attributes, Direction, Backup, Forward, Notexml, Barline),
                    list=True)

Part = Parser("part", as_class(Attrs),
              save="attr-id".split(),
              children=(Measurexml,),
              list=True)

def score_partwise(name, props):
    part_list = props['part-list']
    parts = props['part']
    for part in parts:
        part.score_part = part_list[part.id]
    return name, parts
        
# Returns a list of parts.  You won't see score-partwise!
Score_partwise = Parser("score-partwise", score_partwise,
                   ignore="attr-version work identification defaults credit".split(),
                   children=(Part_list, Part),
                  #trace=True
                   )


def parse(filename):
    r'''Returns a list of Parts.
    '''
    with ZipFile(filename) as xml_zip:
        #print(xml_zip.namelist())
        container_xml = xml_zip.read(container)
        #print(container_xml)
        root = fromstring(container_xml)
        #print('root', root.tag)
        #print('root children', [e.tag for e in root])
        rootfiles = root.find('rootfiles')
        files = [x.get('full-path') for x in rootfiles.findall('rootfile')]
        assert len(files) == 1, f"expected one file in musicxml zip file, got {len(files)}"
        musicxml = files[0]
        #print("rootfile", musicxml)

        root = fromstring(xml_zip.read(musicxml))
    assert root.tag == "score-partwise", f"Expected root tag of 'score-partwise', got {root.tag}"
    parts = Score_partwise.parse(root)[1]
    return parts



if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", "-q", action="store_true", default=False)
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    parts = parse(args.musicxml_file)
    if not args.quiet:
        for part in parts:
            part.dump()
            print()
