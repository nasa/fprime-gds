# Fpy Tutorial

Fpy is an easy to learn, powerful spacecraft scripting language backed by decades of JPL heritage. It is designed to work with the FPrime flight software framework. The syntax is inspired by Python, and it compiles to an efficient binary format.

This guide is a quick overview of the most important features of Fpy. It should be easy to follow for someone who has used Python and FPrime before.

## Compiling and Running a Sequence

First, make sure `fprime-gds` is installed.

Fpy sequences are suffixed with `.fpy`. Let's make a test sequence that dispatches a no-op:
```py
# hash denotes a comment
# assume this file is named "test.fpy"

# use the full name of the no-op command:
CdhCore.cmdDisp.CMD_NO_OP() # empty parentheses indicate no arguments
```

You can compile it with `fprime-fpyc test.fpy --dictionary Ref/build-artifacts/Linux/dict/RefTopologyDictionary.json`

Make sure your deployment topology has an instance of the `Svc.FpySequencer` component. You can run the sequence by passing it in as an argument to the `Svc.FpySequencer.RUN` command.

## Variables and Basic Types

Fpy supports statically-typed, mutable local variables. You can change their value, but the type of the variable can't change. 

This is how you declare a variable, and change its value:
```py
unsigned_var: U8 = 0
# this is a variable named unsigned_var with a type of unsigned 8-bit integer and a value of 0

unsigned_var = 123
# now it has a value of 123
```

For types, Fpy has most of the same basic ones that FPP does:
* Signed integers: `I8, I16, I32, I64`
* Unsigned integers: `U8, U16, U32, U64`
* Floats: `F32, F64`
* Boolean: `bool`

Float literals are denoted with a decimal point (`5.0`, `0.123`) and Boolean literals have a capitalized first letter: `True`, `False`. There is no way to differentiate between signed and unsigned integer literals, so the compiler looks at where the literal is used to determine the signedness.

## Dictionary Types

Fpy also has access to all structs, arrays and enums in the FPrime dictionary:
```py
# you can access enum constants by name:
enum_var: Fw.Success = Fw.Success.SUCCESS

# you can construct arrays:
array_var: Ref.DpDemo.U32Array = Ref.DpDemo.U32Array(0, 1, 2, 3, 4)

# you can construct structs:
struct_var: Ref.SignalPair = Ref.SignalPair(0.0, 1.0)
```

In general, the syntax for instantiating a struct or array type is `Full.Type.Name(arg, ..., arg)`.

## Math
You can do basic math and store the result in variables in Fpy:
```py
pemdas: F32 = 1 - 2 + 3 * 4 + 10 / 5 * 2 # == 15.0
```

Fpy supports the following math operations:
* Basic arithmetic: `+, -, *, /`
* Modulo: `%`
* Exponentiation: `**`
* Floor division: `//`
* Natural logarithm: `log(x)`

The behavior of these operators is designed to mimic Python. Note that **division always returns a float**. This means that `5 / 2 == 2.5`, not `2`. This may be confusing coming from C++, but it is consistent with Python.

## Variable Arguments to Commands

Where this really gets interesting is when you pass variables or expressions into commands:
```py
# this is a command that takes an F32
Ref.recvBuffComp.PARAMETER4_PRM_SET(1 - 2 + 3 * 4 + 10 / 5 * 2)
# alternatively:
param4: F32 = 15.0
Ref.recvBuffComp.PARAMETER4_PRM_SET(param4)
```

The same syntax works with the [sleep](#relative-and-absolute-sleep), [exit](#exit-macro), and [log](#log-macro) macros.

## Getting Telemetry Channels

Fpy supports getting the value of telemetry channels:
```py
cmds_dispatched: U32 = CdhCore.cmdDisp.CommandsDispatched

signal_pair: Ref.SignalPair = Ref.SG1.PairOutput
```

It's important to note that if your component hasn't written telemetry to the telemetry database (`TlmPacketizer` or `TlmChan`) in a while, the value the sequence sees may be old. Make sure to regularly write your telemetry!

## Getting Parameters

Fpy supports getting the value of parameters:
```py
prm_3: U8 = Ref.sendBuffComp.parameter3
```

A significant limitation of this is that it will only return the value most recently saved to the parameter database. This means you must command `_PRM_SAVE` before the sequence will see the new value.

## Conditionals
Fpy supports comparison operators:
```py
value: bool = 1 > 2 and (3 + 4) != 5
```
* Inequalities: `>, <, >=, <=`
* Equalities: `==, !=`
* Boolean functions: `and, or, not`


The inequality operators can compare two numbers of any type together. The equality operators, in addition to comparing numbers, can check for equality between two of the same complex type:
```py
record1: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
record2: Svc.DpRecord = Svc.DpRecord(0, 1, 2, 3, 4, 5, Fw.DpState.UNTRANSMITTED)
records_equal: bool = record1 == record2 # == True
```
## If/elif/else

This is particularly useful for checking telemetry channel values:

```py
cmds_dispatched: U32 = CdhCore.cmdDisp.CommandsDispatched
many_cmds_dispatched: bool = cmds_dispatched >= 123
```
## Getting Struct Members and Array Items

You can access members of structs by name, or array elements by index:
```py
# access struct members with "." syntax
signal_pair_time: F32 = Ref.SG1.PairOutput.time

# access array elements with "[]" syntax
com_queue_depth_0: U32 = ComCcsds.comQueue.comQueueDepth[0]
```

You cannot reassign struct members or array elements however:
```py
signal_pair: Ref.SignalPair = Ref.SG1.PairOutput
# compiler error:
signal_pair.time = 0.2

com_queue_depth: Svc.ComQueueDepth = ComCcsds.comQueue.comQueueDepth
# compiler error:
com_queue_depth[0] = 1
```

## Relative and Absolute Sleep
You can pause the execution of a sequence for a relative duration, or until an absolute time:
```py
CdhCore.cmdDisp.CMD_NO_OP_STRING("second 0")
# sleep for 1 second and 0 microseconds
sleep(1, 0)
CdhCore.cmdDisp.CMD_NO_OP_STRING("second 1")


CdhCore.cmdDisp.CMD_NO_OP_STRING("today")
# sleep until 12345678900 seconds and 0 microseconds after the epoch
sleep_until(0, 0, 12345678900, 0)
CdhCore.cmdDisp.CMD_NO_OP_STRING("much later")
```

Make sure that the `Svc.FpySequencer.checkTimers` port is connected to a rate group. The sequencer only checks if a sleep is done when the port is called, so the more frequently you call it, the more accurate the wakeup time.

## Exit Macro
You can end the execution of the sequence early by calling the `exit` macro:
```py
# exit takes a boolean argument
# True means "end the sequence without an error"
exit(True)
# False means "end the sequence and raise an error"
exit(False)
```