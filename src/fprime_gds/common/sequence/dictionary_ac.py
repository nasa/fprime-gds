from builtin_ac import *

def id(id):
    def add_id(fn):
        fn.id = id
        return fn
    return add_id

class Component:
    def __init__(self, name, id) -> None:
        self.id = id
        self.name = name

class FSWExecutive(Component):

    def __init__(self, name, id) -> None:
        self.id = id
        self.name = name

    @property
    def current_mode(self):
        pass

    @id(1)
    def SET_MODE(self, mode: int):
        pass

class RCSController(Component):

    def __init__(self, name, id) -> None:
        self.id = id
        self.name = name

    @id(0)
    def FIRE_THRUSTERS(self):
        pass

fswExec = FSWExecutive("fswExec", 1)

rcsController = RCSController("rcsController", 2)

instances: list[Component] = [fswExec, rcsController]