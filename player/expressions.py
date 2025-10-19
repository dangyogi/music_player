# expressions.py

r'''All note control parameters are received on channel 2 (midi 1).

Channel 1 is reserved for global player parameters and standard MIDI controls.
'''

import math
from collections import defaultdict


Exp_CC_commands = {  # {(ch, CC_param): set_fn}  set_fn
}

def id(x):
    return x

def linear(m, min):
    # m*x + min
    def scale(x):
        return m*x + min
    return scale

def exponential(m, min):
    # min * m**x
    def scale(x):
        return min*math.pow(m, x)
    return scale


Expressions = defaultdict(dict)     # {param_name: {modifier: adjust_fn}}
Modifier_order = defaultdict(dict)  # {param_name: {modifier: order}}

# fermata
# trill

# tuplet (not used)

def modify(note, channel, velocity):
    r'''Returns (channel, note_on (clocks), note_off (clocks), velocity) or None.

    For normal notes (with a non-zero duration) the modified duration is added to the original
    note_on time to get note_off.

    For grace notes (with a zero duration) the duration is added to the modified note_on time.
    '''
    if "trill" in note.modifiers:
        return trill(note, channel, velocity)
    if "fermata" in note.modifiers:
        return fermata(note, channel, velocity)
    new_values = []
    for param_name, param_value \
     in zip(('channel', 'note_on', 'duration', 'velocity'),
            (channel, note.start, getattr(note, "duration_clocks", 0), velocity)):
        modifiers = Expressions[param_name]
        order = Modifier_order[param_name]
        for modifier in sorted(note.modifiers.intersection(modifiers.keys()), key=order.__getitem__):
            new_value = modifiers[modifier](param_value)
            if new_value is not None:
                print(f"modify {param_name}: {modifier=}, {new_value=}")
                break
        else:
            new_value = param_value
        if param_name == 'duration':
            if param_value: # normal note
                new_values.append(note.start + new_value)     # applied to original start
            else:           # grace note
                new_values.append(new_values[1] + new_value)  # applied to new start
        else:
            new_values.append(new_value)
    print(f"modify({note.note}, {channel=}, {note.start=}, "
          f"note.duration_clocks={getattr(note, 'duration_clocks', 0)}, {velocity=}) -> {new_values}")
    return new_values

def trill(note, channel, velocity):
    # FIX
    return (channel, note.start, note.start + note.duration_clocks, velocity)

def fermata(note, channel, velocity):
    # FIX
    return (channel, note.start, note.start + note.duration_clocks, velocity)

class param_type:
    r'''E.g., "channel", "note_on", "duration", "velocity"
    '''
    def __init__(self, name, param_index, scale_fn=id, null_value=0, starting_value=0):
        self.name = name
        self.param_index = param_index
        self.scale_fn = scale_fn
        self.null_value = null_value
        self.starting_value = starting_value

    def for_modifier(self, modifier, modifier_order, param_offset, channel=2):
        r'''The order of calls to for_modifier also establishes the modifier order for this param_name.

        Early calls are tried before later calls, so that earlier modifiers override later ones.

        The modifier order may be different for different param_names.
        '''
        self.instance(self, modifier, modifier_order, channel, param_offset + self.param_index)

class param_instance:
    r'''A param_type for one specific modifier.
    '''
    def __init__(self, param_type, modifier, modifier_order, channel, cc_param):
        self.param_type = param_type
        self.modifier = modifier
        self.channel = channel
        self.cc_param = cc_param
        self.set(self.param_type.starting_value)

        assert self.modifier not in Expressions[self.param_type.name], \
               f"{self.__class__.__name__}.__init__({modifier=}): " \
               f"param_name={self.param_type.name} already registered"
        Expressions[self.param_type.name][self.modifier] = self.adjust
        Modifier_order[self.param_type.name][self.modifier] = modifier_order

        cc_key = self.channel, self.cc_param
        assert cc_key not in Exp_CC_commands, \
               f"{self.__class__.__name__}.__init__(param_name={self.param_type.name}, " \
               f"{modifier=}): {cc_key=} already registered"
        Exp_CC_commands[cc_key] = self.set

    def set(self, value):
        if value == self.param_type.null_value:
            self.value = None
        else:
            self.value = self.param_type.scale_fn(value)

class adjust_replace(param_instance):
    def adjust(self, orig_value):
        if self.value is None:
            return None
        assert round(self.value, 2), \
               f"modifier={self.modifier}, {self.param_type.name}, {self.value=}"
        return self.value

class adjust_percent(param_instance):
    def adjust(self, orig_value):
        if self.value is None:
            return None
        assert round(self.value, 2), \
               f"modifier={self.modifier}, {self.param_type.name}, {self.value=}"
        return orig_value * (1 + self.value)

class channel(param_type):
    # operates on human channel number (starting at 1)
    instance=adjust_replace
    def __init__(self, starting_value=0):
        super().__init__("channel", 0, id, 0, starting_value)

Channel = channel()

class note_on(param_type):
    instance=adjust_percent
    def __init__(self, starting_value=63):
        super().__init__("note_on", 1, linear(0.011969, -0.75), 63, starting_value)

Note_on = note_on()

class duration(param_type):
    # operates on duration
    instance=adjust_percent
    def __init__(self, starting_value=63):
        super().__init__("duration", 2, linear(0.011969, -0.75), 63, starting_value)

Duration = duration()

class grace_duration(param_type):
    # operates on duration
    instance=adjust_replace
    def __init__(self, starting_value=13):
        super().__init__("duration", 2, linear(1.1575, 3), None, starting_value)

Grace_duration = grace_duration()

class velocity(param_type):
    instance=adjust_percent
    def __init__(self, starting_value=42):
        super().__init__("velocity", 3, linear(0.011811, -0.50), 42, starting_value)

Velocity = velocity()

Assignments = [       # Channel, Note_on, Duration, Grace_duration, Velocity, offset, channel

    ("strong_accent",      1,      3,      1,         None,            1,        0,      2),
    ("accent",             1,      3,      1,         None,            1,        4,      2),
    ("tenuto",             1,      3,      1,         None,            1,        8,      2),
    ("staccato",           1,      3,      1,         None,            1,       12,      2),
    ("detached_legato",    1,      3,      1,         None,            1,       16,      2),
    ("staccatissimo",      1,      3,      1,         None,            1,       20,      2),  # 6

    ("arpeggiate_1",       2,      1,      3,         None,            3,       24,      2),
    ("arpeggiate_2",       2,      1,      3,         None,            3,       28,      2),
    ("arpeggiate_3",       2,      1,      3,         None,            3,       32,      2),
    ("arpeggiate_4",       2,      1,      3,         None,            3,       36,      2),
    ("arpeggiate_5",       2,      1,      3,         None,            3,       40,      2),
    ("arpeggiate_6",       2,      1,      3,         None,            3,       44,      2),
    ("arpeggiate_7",       2,      1,      3,         None,            3,       48,      2),
    ("chord_1",            2,      1,      3,         None,            3,       52,      2),
    ("chord_2",            2,      1,      3,         None,            3,       56,      2),
    ("chord_3",            2,      1,      3,         None,            3,       60,      2),
    ("chord_4",            2,      1,      3,         None,            3,       64,      2),
    ("chord_5",            2,      1,      3,         None,            3,       68,      2),
    ("chord_6",            2,      1,      3,         None,            3,       72,      2),
    ("chord_7",            2,      1,      3,         None,            3,       76,      2),  # 20

    ("grace",              2,      1,   None,            1,            1,       80,      2),
    ("grace_slash",        2,      1,   None,            1,            1,       84,      2),  # 22
    ("voice_1",            3,      4,      4,         None,            4,       88,      2),
    ("voice_2",            3,      4,      4,         None,            4,       92,      2),
    ("voice_3",            3,      4,      4,         None,            4,       96,      2),
    ("voice_4",            3,      4,      4,         None,            4,      100,      2),
    ("voice_5",            3,      4,      4,         None,            4,      104,      2),
    ("voice_6",            3,      4,      4,         None,            4,      108,      2),
    ("voice_7",            3,      4,      4,         None,            4,      112,      2),
    ("voice_8",            3,      4,      4,         None,            4,      116,      2),
    ("staff_1",            4,      5,      5,         None,            5,      120,      2),
    ("staff_2",            4,      5,      5,         None,            5,      124,      2),  # 32

    ("slur_start",         5,      2,      2,         None,            2,        0,      3),
    ("slur_middle",        5,      2,      2,         None,            2,        4,      3),
    ("slur_stop",          5,      2,      2,         None,            2,        8,      3),  # 35
]

for modifier, ch_order, on_order, dur_order, gr_dur_order, vel_order, offset, channel in Assignments:
    Channel.for_modifier(modifier, ch_order, offset, channel)
    Note_on.for_modifier(modifier, on_order, offset, channel)
    if dur_order is not None:
        Duration.for_modifier(modifier, dur_order, offset, channel)
    if gr_dur_order is not None:
        Grace_duration.for_modifier(modifier, gr_dur_order, offset, channel)
    Velocity.for_modifier(modifier, vel_order, offset, channel)

