# FPy Advanced Sequencing Language Version 0.1
The FPy advanced sequencing language is a combination of a high-level scripting language and a low-level bytecode language for running complex command sequences on spacecraft flight software.
## FPy Syntax
### Modules, components, channels, commands and types
You can imagine the FPy syntax as Python with the following mappings:
1. FPrime modules become Python namespaces
2. FPrime components become Python classes
3. FPrime types (structs, arrays and enums) become Python classes
4. FPrime component instances become Python object instances
5. FPrime commands become member functions of Python object instances
6. FPrime telemetry channels become member properties of Python object instances

FPrime declaration:
```
module Ref {
    passive component ExampleComponent {
        telemetry testChannel: U8
        sync command TEST_COMMAND(arg: string size 40)
    }

    instance exampleInstance: ExampleComponent base id 0x01
}
```
FPy usage:
```py
# reference a telemetry channel
Ref.exampleInstance.testChannel
# call a command
Ref.exampleInstance.TEST_COMMAND("arg value")
```


FPrime declaration:
```
struct ExampleStruct {
    member: F32
}

enum TestEnum {
    ONE
    TWO
    THREE
}

array TestArray = [3] U8
```

FPy usage:
```py
# construct a struct
ExampleStruct(0.0)
# reference an enum const
TestEnum.THREE
# construct an array
TestArray(1, 2, 3)
```

### Sequence directives
FPy also has sequence directives, which are like commands that control the running sequence itself.

The most common sequence directives are absolute and relative sleep:
```py
sleep_abs(Time(time_base, time_context, seconds, useconds))
sleep_rel(Time(time_base, time_context, seconds, useconds))
```

Due to the nature of the FPrime `CmdSequencer`, you can only have zero or one `sleep` directives before each command.

## FPy Usage
```
fprime-seq <sequence.fpy> -d <TopologyDictionary.json> [-o <output.bin>]

A compiler for the FPrime advanced sequencing language

positional arguments:
  input                 The path of the input sequence to compile

options:
  -h, --help            show this help message and exit
  -d DICTIONARY, --dictionary DICTIONARY
                        The JSON topology dictionary to compile against
  -o OUTPUT, --output OUTPUT
                        The output .bin file path. Defaults to the input file path
```

The result is a sequence binary file that works with the FPrime `CmdSequencer`.