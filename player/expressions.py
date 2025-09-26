# expressions.py

r'''All note control parameters are received on channel 2 (midi 1).

Channel 1 is reserved for global player parameters and standard MIDI controls.
'''

import math


Ch2_CC_commands = {
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


class expression:
    def __init__(self, control_param_base,
                 scale1=id,                             # channel    [0-15]
                 scale2=linear(0.0119, -0.75),          # note_on  + [-0.75:0.76] * duration
                 scale3=linear(0.0119, -0.75),          # note_off + [-0.75:0.76] * duration
                 scale4=linear(0.635, -40)):            # velocity + [-40:41]
        self.control_param_base = control_param_base
        self.values = [1] * 4
        self.scale_fns = [scale1, scale2, scale3, scale4]

    def set(self, offset, value):
        self.values[offset] = self.scale_fns[offset](value)

    def adjust(self, channel, note_on, note_off, velocity, duration):
        return (self.adj_channel(channel),
                self.adj_note_on(note_on, duration),
                self.adj_note_off(note_off, duration),
                self.adj_velocity(velocity))

    def adj_channel(self, channel):
        return self.values[0]

    def adj_note_on(self, note_on, duration):
        return note_on + self.values[1] * duration

    def adj_note_off(self, note_off, duration):
        return note_off + self.values[2] * duration

    def adj_velocity(self, velocity):
        return min(127, max(0, velocity + self.values[3]))

class trill(expression):
    # FIX: how to do this?
    pass

class fermata(expression):
    r'''The pause eyeball.
    '''
    def adj_note_off(self, note_off, duration):
        return self.values[2]
