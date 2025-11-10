# The SPEC is currently work-in-progress

# Types

The following types are built into Fpy, and the developer can directly refer to them by name:
* Numeric types: `U8, U16, U32, U64, I8, I16, I32, I64, F32, F64`
* Boolean type: `bool`
* Time type: `Fw.Time`

In addition, the developer can directly refer to any displayable type defined in FPP via its fully-qualified name. This includes user-defined structs, arrays and enums.

There are some types which exist in Fpy but cannot be directly referenced by name by the developer. These are the *LiteralInt*, and *LiteralString* types. See [literals](#literals).

## Structs
You can instantiate a new struct at runtime by calling its constructor. A struct's constructor is a function with the same name as the type, with arguments corresponding to the type and position of the struct's members. For example, a struct defined as:
```
module Fw {
    struct Example {
        intValue: U8
        boolValue: bool
    }
}
```
can be constructed in Fpy like:
```
Fw.Example(0, True)
```


## Fields
Fields are either members (of structs) or elements (of arrays)
# Literals
The following literals are supported by Fpy:
* Integer literals: `123`, `-456_879`
* Float literals: `0.123`, `1e-5`
* String literals: `"hello world"`, `'example string'`
* Boolean literals: `True` and `False`

## Integer literals
Integer literals are strings matching:
```
DEC_NUMBER:   "1".."9" ("_"?  "0".."9" )*
          |   "0"      ("_"?  "0"      )* /(?![1-9])/
```

The first rule of this syntax allows for integers without leading zeroes, separated by underscores. So this is okay:
```
123_456
```
but this is not:
```
0123_456
```

The second rule allows you to write any number of zeroes, separated by underscores:
```
00_000_0
```

Integer literals have type *LiteralInt*, which is not directly referenceable by the user. The *LiteralInt* type supports integers of arbitrary size.

## Float literals
Float literals are strings matching:
```
FLOAT_NUMBER: _SPECIAL_DEC _EXP | DECIMAL _EXP?
```
where `_SPECIAL_DEC`, `_EXP` and `DECIMAL` are defined as:

```
_SPECIAL_DEC: "0".."9" ("_"?  "0".."9")*
_EXP: ("e"|"E") ["+" | "-"] _SPECIAL_DEC
DECIMAL: "." _SPECIAL_DEC | _SPECIAL_DEC "." _SPECIAL_DEC
```

A `FLOAT_NUMBER` can be any string of digits suffixed with an exponent, like these:
```
1e-5
100_200e10
```

or it can be a `DECIMAL` optionally suffixed by an exponent, like these:
```
2.123
100.5e+10
```

Float literals have type `F64`.

## String literals
String literals are strings matching:
```
STRING: /("(?!"").*?(?<!\\)(\\\\)*?"|'(?!'').*?(?<!\\)(\\\\)*?')/i
```

They have type *LiteralString*, which is not directly referenceable by the user. The *LiteralString* type supports strings of arbitrary length.

# Functions
Functions have a `function_name`, argument types and a `return_type`. A function call is an expression of type `return_type` which looks like:
```
function_name(arg_0, arg_1, ..., arg_x)
```

where `arg_x` are the argument expressions at index `x`. Argument expressions will be evaluated once, in order from lowest index to highest index. 

There are several types of functions: commands, macros, casts and constructors.
## Commands
Any command in a component instance defined in FPP is callable in Fpy. The `function_name` of a command is its fully-qualified name, and the argument types are the same as those defined in FPP. The `return_type` of every command is `Fw.CmdResponse`.

When a command is called, its opcode and arguments are immediately sent to the command dispatcher, and the sequence pauses execution until the command returns a response. That response becomes the value of the command call expression.

# Type conversion

Type conversion is the process of converting an expression from one type to another. It can either be implicit, in which case it is called coercion, or explicit, in which case it is called casting.

## Coercion
Coercion happens when an expression of type *A* is used in a syntactic element which requires an expression of type *B*. For example, functions, operators and variable assignments all require specific input types, so type coercion happens in each of these.

When type coercion happens, the following type conversion rules are applied:

1. Expressions of any integer type can be converted to any signed or unsigned integer or float type.
2. Expressions of any float type can be converted to any float type.
3. Expressions of type *LiteralString* can be converted to any string type.

TODO try out with forcing type casting--see what the FF's think
TODO require explicit narrowing casts? or have a compiler warning?
TODO consider float to int conversion?
TODO consider adding constants

If no rule matches, then the compiler raises an error.

There is currently no support for converting non-literal string expressions to other string expressions.

# Operators

Fpy supports the following operators:
* Basic arithmetic: `+, -, *, /`
* Modulo: `%`
* Exponentiation: `**`
* Floor division: `//`
* Boolean: `and, or, not`
* Comparison: `<, >, <=, >=, ==, !=`

Each time an operator is used, an intermediate type must be picked and both args must be converted to that type.

## Behavior of operators

### Addition (`+`)
### Subtraction (`-`)
### Multiplication (`*`)
### Division (`/`)
### Modulo (`%`)
### Exponentiation (`**`)
### Floor division (`//`)
### And (`and`)
### Or (`or`)
### Not (`not`)


## Intermediate types

Intermediate types are picked via the following rules:

1. The intermediate type of Boolean operators is always `bool`.
2. The intermediate type of `==` and `!=` may be any type, so long as the left and right hand sides are the same type. If both are numeric then continue.
3. If either argument is non-numeric, raise an error.
4. If the operator is `/` or `**`, the intermediate type is always `F64`.
5. If either argument is a float, the intermediate type is `F64`.
6. If either argument is an unsigned integer, the intermediate type is `U64`.
7. Otherwise, the intermediate type is `I64`.

If the expressions given to the operator are not of the intermediate type, type coercion rules are applied.

## Result type

The result type is the type of the value produced by the operator.
1. For numeric operators, the result type is the intermediate type.
2. For boolean and comparison operators, the result type is `bool`.

Normal type coercion rules apply to the result, of course. Once the operator has produced a value, it may be coerced into some other type depending on context.

# Loops

## For loops

```
for_stmt: "for" var "in" _expr ":" body
```
* 

# Macros

## exit
## log
## sleep
## sleep_until