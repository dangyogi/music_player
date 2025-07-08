# unroll_repeats.py

from copy import deepcopy


class measure_list:
    r'''Takes xml measures and unrolls the repeats
    '''
    def __init__(self):
        self.body = []
        self.repeat = None

    def next_measure(self, measure):
        r'''Returns True if done.
        '''
        #print(f"measure_list got {measure.number=}, {len(self.body)=}")
        if self.repeat:
            if self.repeat.next_measure(measure):
                self.body.append(self.repeat)
                self.repeat = None
        elif measure.repeat_forward:
            self.repeat = repeat(measure)
        else:
            if measure.ending_start or measure.ending_stop or measure.repeat_backward:
                print(f"measure_list: ending outside of repeat in measure {measure.number}")
            self.body.append(measure)
        return False

    def __iter__(self):
        if self.repeat:
            print("measure_list: repeat not ended properly at end of part")
        #print(f"measure_list: {len(self.body)=}")
        for measure in self.body:
            if isinstance(measure, repeat):
                yield from measure.unroll()
            else:
                yield measure

class repeat:
    def __init__(self, first_measure):
        self.body = [first_measure]
        self.endings = []
        self.repeat = None

    def next_measure(self, measure):
        r'''Returns True if repeat is done.
        '''
        if self.repeat:
            if self.repeat.next_measure(measure):
                self.body.append(self.repeat)
                self.repeat = None
        elif measure.ending_start:
            self.endings.append([measure])
            self.ending_done = measure.ending_stop
            if self.ending_done and not measure.repeat_backward:
                #self.report_size()
                return True
        elif measure.ending_stop:
            if not self.endings:
                print(f"repeat: extranious ending_stop, measure {measure.number}")
            if self.ending_done:
                print(f"repeat: ending_stop missing ending_start, measure {measure.number}")
            self.endings[-1].append(measure)
            self.ending_done = True
            if not measure.repeat_backward:
                #self.report_size()
                return True  # all done!
        elif self.endings:
            self.endings[-1].append(measure)
        else:
            if measure.repeat_forward:
                self.repeat = repeat(measure)
            else:
                self.body.append(measure)
        return False

    def report_size(self):
        print(f"repeat({self.body[0].number}) got {len(self.body)=} "
              f"endings={tuple(len(ending) for ending in self.endings)}")

    def unroll(self, prefix=''):
        for num, ending in enumerate(self.endings, 1):
            for measure in self.body:
                if isinstance(measure, repeat):
                    yield from measure.unroll(f"{prefix}.{num}")
                else:
                    measure_copy = deepcopy(measure)
                    measure_copy.number = f"{measure_copy.number}{prefix}.{num}"
                    yield measure_copy
            for measure in ending:
                measure_copy = deepcopy(measure)
                measure_copy.number = f"{measure_copy.number}{prefix}.{num}"
                yield measure_copy


def unroll_repeats(measures):
    r'''Reassigns measure.number for repeated measures using dots: e.g., 3.1, 3.2

    Does deepcopy on repeated measures so that later changes to one copy don't affect the others.
    '''

    # measures:
    #
    # input:
    #
    #   m1
    #   m2: repeat_forward
    #   m3
    #   m4: repeat_forward
    #   m5
    #   m6: ending 1 start/stop, repeat_backward
    #   m7: ending 2 start/stop
    #   m8
    #   m9: ending 1 start/stop, repeat_backward
    #   m10: ending 2 start/stop
    #   m11
    #
    # output:
    #
    #   m1
    #   m2.1: repeat_forward
    #   m3.1
    #   m4.1.1: repeat_forward
    #   m5.1.1
    #   m6.1.1: ending 1 start/stop, repeat_backward
    #   m4.1.2: repeat_forward
    #   m5.1.2:
    #   m7.1.2: ending 2 start/stop
    #   m8.1
    #   m9.1: ending 1 start/stop, repeat_backward
    #   m2.2: repeat_forward
    #   m3.2
    #   m4.2.1: repeat_forward
    #   m5.2.1
    #   m6.2.1: ending 1 start/stop, repeat_backward
    #   m4.2.2: repeat_forward
    #   m5.2.2:
    #   m7.2.2: ending 2 start/stop
    #   m8.2
    #   m10.2: ending 2 start/stop
    #   m11
    #
    ml = measure_list()
    for measure in measures:
        ml.next_measure(measure)
    return list(ml)


def unroll_parts(parts, trace=False):
    new_parts = []
    for part in parts:
        measures_unrolled = unroll_repeats(part.measure)
        if trace:
            print(f"part({part.id}): {len(part.measure)=}, {len(measures_unrolled)=}")
        new_parts.append((part.score_part, measures_unrolled))
    return new_parts



if __name__ == "__main__":
    import argparse
    from parse_xml import parse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", "-c", action="store_true", default=False)
    parser.add_argument("--list", "-l", action="store_true", default=False)
    parser.add_argument("musicxml_file")

    args = parser.parse_args()

    parts = parse(args.musicxml_file)
    new_parts = unroll_parts(parts, args.counts)

    if args.list:
        for info, measures in new_parts:
            print("part", info.id)
            for measure in measures:
                print(measure.number)
            print()
