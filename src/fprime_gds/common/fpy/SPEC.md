Nothing type is a type whose set of values is an empty set
Unit type is a type whose set of values is a set with one element

# `if` statement

## Syntactical and semantic checks

`"if" condition ":" INDENT stmt* DEDENT ("elif" condition ":" INDENT stmt* DEDENT)* ["else" ":" INDENT stmt* DEDENT]`

1. where `condition` is an expression which evaluates to a boolean
2. where `stmt` is a statement

## Code generation

1. `if` generates `IF`, followed by the generated code for the first body, followed by `GOTO` to the end of the if statement
2. `elif` generates `IF`, followed by the generated code for its body, followed by `GOTO` to the end of the if statement
3. `else` generates the code for its body

# `not` boolean operator

## Syntactical and semantic checks

`"not" value` evaluates to a boolean at runtime

1. where `value` is an expression which evaluates to a boolean

## Code generation

1. `not` generates `NOT`

# `and` and `or` boolean operators

## Syntactical and semantic checks

`value (op value)+` evaluates to a boolean at runtime

1. where `op: "and"|"or"`
2. where `value` is an expression which evaluates to a boolean

## Code generation

1. Each `and` or `or` between two `value`s generates an `AND` or `OR`, respectively

# Infix comparisons

## Syntactical and semantic checks

`lhs op rhs` evaluates to a boolean at runtime

1. where `op: ">" | "<" | "<=" | ">=" | "==" | "!="`
2. and `lhs`, `rhs` are expressions which evaluate to a number

If either `lhs` or `rhs` evaluate to a float:
3. both `lhs` and `rhs` must evaluate to floats of the same bit width

Otherwise, `lhs` and `rhs` evaluate to integer values. All comparisons between integer values are valid.

## Code generation

### Equality comparisons

1. `==` or `!=` between two floats generates `FEQ` or `FNE`, respectively
2. `==` or `!=` between two ints generates `IEQ` or `INE`, respectively

### Inequality comparisons

1. `>`, `<`, `<=`, or `>=` between two floats generates `FGT`, `FLT`, `FLE` or `FGE`, respectively
2. `>`, `<`, `<=`, or `>=` between two unsigned ints generates `UGT`, `ULT`, `ULE` or `UGE`, respectively
2. `>`, `<`, `<=`, or `>=` between two ints, where at least one is signed, generates `SGT`, `SLT`, `SLE` or `SGE`, respectively