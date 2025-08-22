# Fpy Tutorial

Fpy is an easy to learn, powerful spacecraft scripting language backed by decades of JPL heritage. It is designed to work with the FPrime flight software framework. The syntax is inspired by Python, and it compiles to an efficient binary format.

This guide is a quick overview of the most important features of Fpy. It should be easy to follow for someone who has used Python and FPrime before.

## Compiling and Running a Sequence

First, make sure `fprime-gds` is installed.

Fpy sequences are suffixed with `.fpy`. Let's make a test sequence that dispatches a no-op:
```
# hash denotes a comment
# in test.fpy

# use the full name of the no-op command:
CdhCore.cmdDisp.CMD_NO_OP() # empty parentheses indicate no arguments
```

You can compile it with `fprime-fpyc test.fpy --dictionary Ref/build-artifacts/Linux/dict/RefTopologyDictionary.json`

Make sure your deployment topology has an instance of the `Svc.FpySequencer` component. You can run the sequence by passing it in as an argument to the `Svc.FpySequencer.RUN` command.

## Variables and Basic Types

Fpy supports statically-typed, mutable local variables. You can change their value, but the type of the variable can't change. 

This is how you declare a variable, and change its value:
```
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

You can make string literals 

## Math

You can do math in Fpy

## Literals

Integer literals are 


