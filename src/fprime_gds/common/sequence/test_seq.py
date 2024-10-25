from dictionary_ac import *

# make sure that it's obvious that the sleep function is not a top level function
seq.sleep(1, 100)

fswExec.SET_MODE(2)
fswExec.SET_MODE(3)

seq.sleep_until("10:10:10.5000")

rcsController.FIRE_THRUSTERS()