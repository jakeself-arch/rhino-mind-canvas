import uuid
class Guid(object):
    Empty = None
    def __init__(self, s=None): self.s = str(s or uuid.uuid4())
    def __str__(self): return self.s
    def __eq__(self, o): return str(self) == str(o)
    def __hash__(self): return hash(self.s)
class Array(object):
    def __class_getitem__(cls, t): return list
