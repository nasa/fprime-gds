Nothing type is a type whose set of values is an empty set
Unit type is a type whose set of values is a set with one element
BIG question: what if we made an arbitrary precision int type? and float tpye?

# Types

The following types are built into Fpy:
* Numeric types: `U8, U16, U32, U64, I8, I16, I32, I64, F32, F64`
* Boolean type: `bool`
* Time type: `Fw.Time`

In addition, any displayable type defined in FPP is accessible in Fpy via its fully-qualified name. This includes user-defined structs, arrays and enums.

## Structs
You can instantiate a new struct at runtime by calling its constructor. For example, a struct defined as
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

You can then access members of the struct
## Struct constructors
All 


# Functions

conversion
* coercion (implicit)
* casting (explicit)

no more interpretation
int has Integer type


# Type conversion

The compiler implicitly attempts type conversion when an expression's type isn't what it needs to be. Functions, operators and variable assignments all require their input values be of a specific type. 

If the input expression's type doesn't match, the compiler will first attempt interpreting the expression differently, and then attempt to have the type converted at runtime. If neither are possible, a compiler error is raised.

## Interpretation
Some expressions do not have a well-defined type when considered in isolation. Numeric literals are a good example. The literal `1` is an integer of unspecified bitwidth and signedness. When it's on the right-hand side of an assignment to a `U32` variable, the compiler can safely interpret the literal as a `U32`.

1. Integer literals can be interpreted as any signed or unsigned integer or float type.
2. Float literals can be interpreted as any float type.
3. String literals can be interpreted as any string type.

## Conversion

Even if an expression cannot be interpreted as a different type, it can often be converted at runtime.

1. Integer expressions can be converted to any signed or unsigned integer or float type.
2. Float expressions can be converted to any float type.

There is currently no support for converting string expressions to other string expressions.

if a rule no mqatcvh, then no coerce

# Operators

Fpy supports the following operators:
* Basic arithmetic: `+, -, *, /`
* Modulo: `%`
* Exponentiation: `**`
* Floor division: `//`
* Boolean: `and, or, not`
* Comparison: `<, >, <=, >=, ==, !=`

Each time an operator is used, an intermediate type must be picked and both args must be converted to that type.

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