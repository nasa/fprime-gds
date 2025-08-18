Nothing type is a type whose set of values is an empty set
Unit type is a type whose set of values is a set with one element
BIG question: what if we made an arbitrary precision int type? and float tpye?





# Type coercion

The compiler implicitly attempts type coercion when an expression's type isn't what it needs to be. Functions, operators and variable assignments all require their input values be of a specific type. If the input expression's type doesn't match, the compiler will first attempt interpreting the expression differently, and then attempt converting the type at runtime. If neither are possible, a compiler error is raised.

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




# Operators

Fpy supports the following operators:
* Basic arithmetic: `+, -, *, /`
* Modulo: `%`
* Exponentiation: `**`
* Floor division: `//`
* Boolean: `and, or, not`
* Comparison: `<, >, <=, >=, ==, !=`

## Intermediate types



Under the hood, all numeric operators only work with 64 bit types. When you add a `U8` and a `U16`, the compiler uses the 

You are able to add two integers with different bitwidths in Fpy. But the `FpySequencer` does 
The `FpySequencer` does not know how to add