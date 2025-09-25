# Directives

## WAIT_REL
sleeps for a relative duration from the current time
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| useconds  | U32      | stack  | Wait time in microseconds (must be less than a second) |
| seconds  | U32      | stack  | Wait time in seconds |

## WAIT_ABS
sleeps until an absolute time
| Arg Name      | Arg Type | Source | Description |
|---------------|----------|--------|-------------|
| useconds     | U32      | stack  | Microseconds |
| seconds      | U32      | stack  | Seconds |
| time_context | FwTimeContextStoreType       | stack  | Time context (user defined value, unused by Fpy) |
| time_base    | U16      | stack  | Time base |

## GOTO
sets the index of the next directive to execute
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| dir_idx  | U32      | hardcoded | The statement index to execute next |

## IF
| Arg Name             | Arg Type | Source     | Description |
|---------------------|----------|------------|-------------|
| false_goto_dir_index| U32      | hardcoded | Directive index to jump to if false |
| condition          | bool     | stack     | Condition to evaluate |

## NO_OP
does nothing
No arguments

## STORE_TLM_VAL
stores a tlm buffer in the lvar array
| Arg Name     | Arg Type | Source     | Description |
|--------------|----------|------------|-------------|
| chan_id      | U32      | hardcoded | the tlm channel id to get the time of |
| lvar_offset  | U32      | hardcoded | the offset in the lvar array to store the tlm in |

## STORE_PRM
stores a prm buffer in the lvar array
| Arg Name     | Arg Type | Source     | Description |
|--------------|----------|------------|-------------|
| prm_id       | U32      | hardcoded | the param id to get the value of |
| lvar_offset  | U32      | hardcoded | the offset in the lvar array to store the prm in |

## CONST_CMD
Runs a command with a constant opcode and a constant byte array of arguments.
| Arg Name   | Arg Type | Source     | Description |
|------------|----------|------------|-------------|
| cmd_opcode | U32      | hardcoded | Command opcode |
| args       | bytes    | hardcoded | Command arguments |

| Stack Result Type | Description |
| ------------------|-------------|
| Fw.CmdResponse | The CmdResponse that the command returned |


## OR
Performs an `or` between two booleans, pushes result to stack.
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | bool     | stack  | Right operand |
| lhs      | bool     | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |

## AND
Performs an `and` between two booleans, pushes result to stack.

| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | bool     | stack  | Right operand |
| lhs      | bool     | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## IEQ
Compares two integers for equality, pushes result to stack. Doesn't differentiate between signed and unsigned.
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## INE
Compares two integers for inequality, pushes result to stack. Doesn't differentiate between signed and unsigned.

| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## ULT
Performs an unsigned less than comparison on two unsigned integers, pushes result to stack
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## ULE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## UGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## UGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## SLT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## SLE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## SGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## SGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FEQ
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FNE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FLT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FLE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## NOT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | bool     | stack  | Value to negate |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## FPTOSI
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Float to convert |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## FPTOUI
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Float to convert |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## SITOFP
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Integer to convert |
| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## UITOFP
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U64      | stack  | Integer to convert |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## ISUB
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## IMUL
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## UDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## SDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## UMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## SMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## FSUB
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## FMUL
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## FDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |

## FLOAT_FLOOR_DIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |

## FPOW
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| exp      | F64      | stack  | Exponent value |
| base     | F64      | stack  | Base value |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## FLOG
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Value for logarithm |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## FMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

| Stack Result Type | Description |
| ------------------|-------------|
| F64 | The result |
## FPTRUNC
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Value to truncate |

| Stack Result Type | Description |
| ------------------|-------------|
| F32 | The result |

## SIEXT_8_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I8       | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |

## SIEXT_16_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I16      | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## SIEXT_32_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I32      | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| I64 | The result |
## ZIEXT_8_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U8       | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## ZIEXT_16_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U16      | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## ZIEXT_32_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U32      | stack  | Value to extend |

| Stack Result Type | Description |
| ------------------|-------------|
| U64 | The result |
## ITRUNC_64_8
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

| Stack Result Type | Description |
| ------------------|-------------|
| U8 | The result |
## ITRUNC_64_16
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

| Stack Result Type | Description |
| ------------------|-------------|
| I16 | The result |
## ITRUNC_64_32
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

| Stack Result Type | Description |
| ------------------|-------------|
| I32 | The result |
## EXIT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| success    | bool      | stack  | True if should exit without error, false otherwise |


## ALLOCATE
pushes some empty bytes to the stack
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to allocate |

| Stack Result Type | Description |
| ------------------|-------------|
| bytes | A series of 0 bytes of length `size` |
## STORE
pops some bytes off the stack and puts them in lvar array
| Arg Name    | Arg Type | Source     | Description |
|-------------|----------|------------|-------------|
| lvar_offset | U32      | hardcoded  | Local variable offset |
| size        | U32      | hardcoded  | Number of bytes |
| value       | bytes    | stack      | Value to store |


## LOAD
gets bytes from lvar array and pushes them to stack
| Arg Name    | Arg Type | Source     | Description |
|-------------|----------|------------|-------------|
| lvar_offset | U32      | hardcoded  | Local variable offset |
| size        | U32      | hardcoded  | Number of bytes |

| Stack Result Type | Description |
| ------------------|-------------|
| bytes | The bytes from the lvar array |
## PUSH_VAL
pushes a const byte array onto stack
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| val      | bytes    | hardcoded  | the byte array to push |

| Stack Result Type | Description |
| ------------------|-------------|
| bytes | The byte array from the arg |
## DISCARD
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to discard |


## MEMCMP
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to compare |

| Stack Result Type | Description |
| ------------------|-------------|
| bool | The result |
## STACK_CMD
| Arg Name  | Arg Type | Source     | Description |
|-----------|----------|------------|-------------|
| args_size | U32      | hardcoded  | Size of command arguments |

| Stack Result Type | Description |
| ------------------|-------------|
| Fw.CmdResponse | The CmdResponse that the command returned |
