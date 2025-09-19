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
| Arg Name   | Arg Type | Source     | Description |
|------------|----------|------------|-------------|
| cmd_opcode | U32      | hardcoded | Command opcode |
| args       | bytes    | hardcoded | Command arguments |

## OR
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | bool     | stack  | Right operand |
| lhs      | bool     | stack  | Left operand |

## AND
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | bool     | stack  | Right operand |
| lhs      | bool     | stack  | Left operand |

## IEQ
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## INE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## ULT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## ULE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## UGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## UGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## SLT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## SLE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## SGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## SGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |
## FEQ
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FNE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FLT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FLE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FGT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FGE
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## NOT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | bool     | stack  | Value to negate |

## FPTOSI
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Float to convert |

## FPTOUI
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Float to convert |

## SITOFP
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Integer to convert |

## UITOFP
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U64      | stack  | Integer to convert |

## ISUB
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## IMUL
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## UDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## SDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## UMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | U64      | stack  | Right operand |
| lhs      | U64      | stack  | Left operand |

## SMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | I64      | stack  | Right operand |
| lhs      | I64      | stack  | Left operand |

## FSUB
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FMUL
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FDIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FLOAT_FLOOR_DIV
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FPOW
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| exp      | F64      | stack  | Exponent value |
| base     | F64      | stack  | Base value |

## FLOG
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Value for logarithm |

## FMOD
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| rhs      | F64      | stack  | Right operand |
| lhs      | F64      | stack  | Left operand |

## FPTRUNC
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | F64      | stack  | Value to truncate |
## SIEXT_8_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I8       | stack  | Value to extend |

## SIEXT_16_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I16      | stack  | Value to extend |

## SIEXT_32_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I32      | stack  | Value to extend |

## ZIEXT_8_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U8       | stack  | Value to extend |

## ZIEXT_16_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U16      | stack  | Value to extend |

## ZIEXT_32_64
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | U32      | stack  | Value to extend |

## ITRUNC_64_8
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

## ITRUNC_64_16
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

## ITRUNC_64_32
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| value    | I64      | stack  | Value to truncate |

## EXIT
| Arg Name | Arg Type | Source | Description |
|----------|----------|--------|-------------|
| success    | bool      | stack  | True if should exit without error, false otherwise |

## ALLOCATE
pushes some empty bytes to the stack
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to allocate |

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

## PUSH_VAL
pushes a const byte array onto stack
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| val      | bytes    | hardcoded  | the byte array to push |

## DISCARD
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to discard |

## MEMCMP
| Arg Name | Arg Type | Source     | Description |
|----------|----------|------------|-------------|
| size     | U32      | hardcoded  | Bytes to compare |

## STACK_CMD
| Arg Name  | Arg Type | Source     | Description |
|-----------|----------|------------|-------------|
| args_size | U32      | hardcoded  | Size of command arguments |

