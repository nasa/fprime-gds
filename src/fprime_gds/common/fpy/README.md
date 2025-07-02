# Fpy Advanced Sequencing Language Version 0.1
The Fpy advanced sequencing language is a combination of a high-level scripting language and a low-level bytecode language for running complex command sequences on spacecraft flight software.
## Fpy Syntax
### Modules, components, channels, commands and types
You can imagine the Fpy syntax as Python with the following mappings:
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
Fpy usage:
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

Fpy usage:
```py
# construct a struct
ExampleStruct(0.0)
# reference an enum const
TestEnum.THREE
# construct an array
TestArray(1, 2, 3)
```