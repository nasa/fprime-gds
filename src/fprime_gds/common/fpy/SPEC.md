Nothing type is a type whose set of values is an empty set
Unit type is a type whose set of values is a set with one element
BIG question: what if we made an arbitrary precision int type? and float tpye?





# Type coercion

The compiler implicitly attempts type coercion when an expression's type isn't what it needs to be. Functions, operators and variable assignments all require their input values be of a specific type. If the input expression's type doesn't match, the compiler will first attempt interpreting the expression differently, and then attempt to have the type converted at runtime. If neither are possible, a compiler error is raised.

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

Each operator is defined for one or more intermediate types. The intermediate type for an operator is decided as follows:

Special rules:
1. Boolean operators always take `bool`.
2. `/` and `**` always take `F64`.
3. `%` takes `U64` if either argument is unsigned, otherwise `I64`.
4. `==` and `!=` may take any type, so long as the left and right hand sides are the same type.

For all other operators:
1. If either argument is a float, take `F64`.
2. If either argument is an unsigned integer, take `U64`.
3. Otherwise, take `I64`.

If the expressions given to the operator are not of the intermediate type, type coercion rules are applied.

## Result type

The result type is the type of the value produced by the operator.
1. For numeric operators, the result type is the intermediate type.
2. For boolean and comparison operators, the result type is `bool`.

Normal type coercion rules apply to the result, of course. Once the operator has produced a value, it may be coerced into some other type depending on context.