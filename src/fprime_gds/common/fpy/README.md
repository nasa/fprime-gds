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
* Logarithm: `log(x)` (see [Log Macro](#log-macro))

The behavior of these operators is designed to mimic Python. In particular, **division always returns a float**. This may be confusing coming from C++, but it is consistent with Python's implementation. This means that `5 / 2 == 2.5`, not `2`

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

A significant limitation of this is that it will only return the value most recently saved to the parameter database. This means you must command `_PRM_SAVE` before the value will update in the sequence.

## Getting Struct Members and Array Items

You can access members of structs by name, or array elements by index:
```py
# access struct members with "." syntax
signal_pair_time: F32 = Ref.SG1.PairOutput.time

# access array elements with "[]" syntax
com_queue_depth_0: U32 = ComCcsds.comQueue.comQueueDepth[0]
```

## Relative and Absolute Sleep

## Exit Macro

## Log Macro

## Math

You can do math in Fpy

## Literals

Integer literals are 


