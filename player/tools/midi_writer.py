# midi_writer.py

import time
from collections import namedtuple, defaultdict

from midi_utils import *

class SkipError(Exception):
    pass

class Choices(namedtuple('choices_tuple',
                         "flags, tag, event_queue, ticks, "
                         "event_source, event_dest, event_relative, "
                         "send_queue, send_port, send_dest")):
    # Total 16 bits, 32K combinations:

    # writer sends 49152 events, reader receives different amounts, so some are randomly lost!

    # 11 bits, 1024 combinations
    Flags = (0, EventFlags.TIME_STAMP_REAL.value, EventFlags.TIME_MODE_REL.value,
             EventFlags.TIME_STAMP_REAL.value | EventFlags.TIME_MODE_REL.value)
    Tags = (0, 17)
    Event_queues = (None, 0)   # Event translates None to SND_SEQ_QUEUE_DIRECT
    Ticks = (None, 44)
    Event_sources = (0, 1, 2, None)
    Event_dests = (0, 1, 2, None)
    Event_relative = (None, False, True)

    # 5 bits, 32 combinations
    Send_queues = (None, 1)
    Send_ports = Event_sources
    Send_dests = Event_dests

    @classmethod
    def fix(cls):
        cls.Event_sources = get_addrs('midi-writer', cls.Event_sources)
        cls.Event_dests = cls.Send_dests = get_addrs('midi-reader', cls.Event_dests)

    @classmethod
    def get_choices(cls, field):
        cls_field = field.capitalize()
        try:
            return getattr(cls, cls_field)
        except AttributeError:
            return getattr(cls, cls_field + 's')

    @classmethod
    def bit_len(cls, field):
        choices = cls.get_choices(field)
        return (len(choices) - 1).bit_length()

    @classmethod
    def total_bit_len(cls):
        ans = 0
        for field in cls._fields:
            ans += cls.bit_len(field)
        return ans

    def bit_encode(self):
        r'''encodes choices as a sequence of bits in a single number.
        '''
        bits = 0
        for name in self._fields:
            value = getattr(self, name)
            bits <<= self.bit_len(name)
            bits |= value
        return bits

    def encode(self):
        r'''encodes choices as: note, ch, velocity

        bits == 0bnnnnnccccvvvvvvv   

        Returns note, ch, velocity
        '''
        bits = self.bit_encode()
        velocity = bits & 0x7F
        bits >>= 7
        ch = bits & 0x0F
        bits >>= 4
        assert bits <= 0x7F, f"Choices.encode: {bits.bit_length() - 7} too many bits!"
        note = bits & 0x7F
        return (note, ch, velocity)

    @classmethod
    def decode(cls, note, ch, velocity):
        r'''bits 0x1234 == 0xnncv
        '''
        bits = note
        bits <<= 4
        bits |= ch
        bits <<= 7
        bits |= velocity
        return cls.decode_bits(bits)

    @classmethod
    def decode_bits(cls, bits):
        values = {}
        for name in reversed(cls._fields):
            field_len = cls.bit_len(name)
            value = bits & ((1 << field_len) - 1)
            values[name] = value
            bits >>= field_len
        return cls(**values)

    def get(self, field):
        choices = self.get_choices(field)
        try:
            return choices[getattr(self, field)]
        except IndexError:
            raise SkipError

    def event(self, value_count_dict=None):
        note, ch, velocity = self.encode()
        fields = dict(
            flags=self.get('flags'),
            tag=self.get('tag'),
            queue_id=self.get('event_queue'),
            tick=self.get('ticks'),
            source=self.get('event_source'),
            dest=self.get('event_dest'),
            relative=self.get('event_relative'),
        )
        event = NoteOnEvent(note, ch, velocity, **fields)
        for name, value in fields.items():
            event_value = getattr(event, name)
            if value_count_dict is not None:
                value_count_dict[name].add(event_value)
            if event_value != value:
                print(f"Choices.event: {name=} doesn't match, set to {value}, got {event_value}")
        return event

    def send(self, event):
        port_id = self.get('send_port')
        midi_send_event(event,
                        queue=self.get('send_queue'),
                        port=Ports[port_id] if port_id is not None else None, 
                        dest=self.get('send_dest'),
                        no_defaults=True,
                        drain_output=True)

    @classmethod
    def print_header(cls):
        for field in cls._fields:
            if field.endswith('source'):
                field = field[:-6] + 'src'
            elif field.endswith('relative'):
                field = field[:-8] + 'rel'
            if field.startswith('event'):
                field = 'e_' + field[6:]
            elif field.startswith('send'):
                field = 's_' + field[5:]
            print(field, '\t', sep='', end='')
        print()

    def print_line(self):
        for field in self._fields:
            value = self.get(field)
            if isinstance(value, Port):
                value = value.port_id
            print(value, '\t', sep='', end='')
        print()


print(f"{Choices.total_bit_len()=}")
#for field in Choices._fields:
#    print(f"{field=}, {Choices.get_choices(field)=}, {Choices.bit_len(field)=}")


def get_addrs(client, ports):
    ans = []
    for port in ports:
        if port is None:
            ans.append(None)
        else:
            addr = midi_address(f"{client}:{port}")
            assert addr is not None, f"get_source for {port=} got None from midi_address"
            ans.append(addr)
    return ans


Ports = []

def init():
    midi_init("midi-writer")
    Ports.append(midi_create_output_port("no-sub", caps=PortCaps.READ))                     # 0
    Ports.append(midi_create_output_port("sub-not-used"))                                   # 1
    Ports.append(midi_create_output_port("sub-used", connect_to=["midi-reader:sub-used"]))  # 2
    assert midi_create_queue("Q0", 24, default=False).queue_id == 0
    assert midi_create_queue("Q1", 24, default=False).queue_id == 1
    midi_set_tempo(60)  # for all queues
    midi_start()        # start all queues

def run():
    value_count_dict = defaultdict(set)
    try:
        init()
        Choices.fix()
        print(f"{Choices.Flags=}")
        Choices.print_header()
        num_sent = 0
        for i in range(2**Choices.total_bit_len()):
            choices = Choices.decode_bits(i)
            try:
                choices.send(choices.event(value_count_dict))
                num_sent += 1
            except SkipError:
                pass
            except ALSAError as e:
                #print(e, e.errnum)
                choices.print_line()
            #time.sleep(0.004)
            time.sleep(0.002)
        print(f"{num_sent=}")
    finally:
        midi_close()
        for field, values in value_count_dict.items():
            print(f"{field}: {values}")


def test():
    for bits in range(2**Choices.total_bit_len()):
        choices = Choices.decode_bits(bits)
        bits2 = choices.bit_encode()
        if bits2 != bits:
            print(f"bits test failed for {hex(bits)}, got {hex(bits2)}")
        else:
            note, ch, velocity = choices.encode()
            choices2 = Choices.decode(note, ch, velocity)
            if choices2 != choices:
                print(f"note, ch, velocity test failed for ({hex(note)}, {hex(ch)}, {hex(velocity)}) "
                      f"from bits {hex(bits)}")


if __name__ == "__main__":
    #test()
    run()
