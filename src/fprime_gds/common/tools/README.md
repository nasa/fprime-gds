# FPrime GDS tools
## fprime-prm-write
### JSON file reference
JSON files for the `fprime-prm-write` tool should take the following form:
```json
{
    "componentInstanceOne": {
        "parameterNameOne": "parameter value",
        "parameterNameTwo": ["a", "b", "c"],
        "parameterNameThree": {
            "complexValue": [123, 456]
        }
    },
    "componentInstanceTwo": {
        "parameterNameFour": true
    }
}
```
The JSON should consist of a key-value map of component instance names to an inner key-value map. The inner key-value map should consist of parameter name-to-value map entries. The parameter values support complex FPrime types, such as nested structs, arrays or enum constants. Structs are instantiated with key-value maps, where the keys are the field names and the values are the field values. Arrays are just JSON arrays, and enum constants are represented as strings.

### How to Initialize a ParamDB .dat File

The `fprime-prm-write` tool can be used to create a `.dat` file compatible with the `PrmDb` component from a json file. To use, create a compatible JSON file as defined in the JSON File Reference above, and pass it in to the tool using the `dat` subcommand, like so:
```
fprime-prm-write dat <json file> --dictionary <path to compiled FPrime dict>
```
You should then have a `.dat` file which can be passed in to the `PrmDb`. Note, this `.dat` file will only have entries for the parameters specified in the JSON file. If you want it to instead have a value for all parameters which have a default value, you can add the `--defaults` option. Then, the generated `.dat` file will essentially reset all parameters back to default, except for those specified in the JSON file.

### How to Create a .seq File From a Parameter JSON File
Sometimes, you may want to update parameters while the FPrime application is running. This can be accomplished with a sequence of `_PRM_SET` commands, which the `fprime-prm-write` tool can automatically create for you. To use, create a compatible JSON file as defined in the JSON File Reference above, and pass it in to the tool using the `seq` subcommand, like so:
```
fprime-prm-write seq <json file> --dictionary <path to compiled FPrime dict>
```
You should then have a `.seq` file which can be compiled and executed by the `CmdSequencer`.