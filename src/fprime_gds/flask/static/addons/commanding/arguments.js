/**
 * commanding/arguments.js:
 *
 * Vue JS components for handling argument input given the complex nature of arguments in fprime. These components
 * support Arrays, Serializables, and scalars along with validation and the associated HTML templates.
 *
 * @author mstarch
 */
import "../../third-party/js/vue-select.js"
import {
    command_bool_argument_template,
    command_enum_argument_template,
    command_array_argument_template,
    command_serializable_argument_template,
    command_scalar_argument_template,
    command_argument_template,
} from "./argument-templates.js";
import {validate_input} from "../../js/validate.js";

export let FILL_NEEDED = "<FILL-VALUE>";

/**
 * Gets a list of fields that the argument supports. For arrays, that is 0...n, for serializables it is named fields.
 * Both can be used for iteration
 * @param argument: argument to detect fields. Must define MEMBER_LIST or LENGTH.
 * @returns list of fields
 */
function get_argument_fields(argument) {
    let expected_field_tokens = [];
    if (argument.type.MEMBER_LIST) {
        expected_field_tokens = argument.type.MEMBER_LIST.map((item) => item[0]);
    } else if (argument.type.LENGTH) {
        expected_field_tokens = Array(argument.type.LENGTH).fill().map((_, i) => i);
    } else {
        console.assert(false, "Non-array/serializable supplied to array/serializable assignment method");
        return [];
    }
    return expected_field_tokens;
}

/**
 * Assign values to arguments of the type array or serializable. This happens by inspecting the internal array of items
 * (repeated elements for arrays, field list for serializable) and assigns each of those arrays individually.
 * @param argument: argument of type array or serializable assign to
 * @param squashed_argument_value: squash-ified command arguments (JSON format with no "value" field)
 */
function command_argument_array_serializable_assignment_helper(argument, squashed_argument_value) {
    let expected_field_tokens = get_argument_fields(argument);
    let errors = [];
    // Loop through all the field names
    for (let i = 0; i < expected_field_tokens.length; i++) {
        let field_name = expected_field_tokens[i];
        if (field_name in squashed_argument_value) {
            command_argument_assignment_helper(argument.value[field_name], squashed_argument_value[field_name]);
        } else {
            errors.push(`Missing expected field: ${field_name}.`);
        }
    }
    if (errors.length > 0) {
        argument.error = errors.join(" ");
    } else {
        argument.error = "";
    }
}

/**
 * Assign command argument from the given value. This function handles scalars, arrays, and serializables.
 * @param argument: argument to assign
 * @param squashed_argument_value: squash-ified command arguments (JSON format with no "value" field)
 */
export function command_argument_assignment_helper(argument, squashed_argument_value) {
    // Argument is expected to be a serializable type
    if (argument.type.MEMBER_LIST || argument.type.LENGTH) {
        command_argument_array_serializable_assignment_helper(argument, squashed_argument_value);
    } else {
        let is_not_string = typeof(argument.type.MAX_LENGTH) === "undefined";
        argument.value = (is_not_string && (squashed_argument_value === FILL_NEEDED)) ? null : squashed_argument_value.toString();
    }
}

/**
 * Clear arguments recursively by setting each argument (or sub-argument) to null. This protects the structure while
 * clearing each of the scalar atoms of the arguments.  Enums are reset to the first value in the list.
 * @param argument: argument to recursively clear.
 */
export function clear_argument(argument) {
    argument.error = "";
    if (argument.type.MAX_LENGTH) {
        argument.value = "";
    }
    else if (argument.type.ENUM_DICT) {
        argument.value = Object.keys(argument.type.ENUM_DICT)[0];
    }
    else if (argument.type.MEMBER_LIST || argument.type.LENGTH) {
        let expected_field_tokens = get_argument_fields(argument);
        for (let i = 0; i < expected_field_tokens.length; i++) {
            clear_argument(argument.value[expected_field_tokens[i]]);
        }
    }
    else {
        argument.value = null;
    }
}

/**
 * Squashes an argument to a simple JSON-compatible argument.
 * @param argument: argument to be squashed
 * @returns: squashed value
 */
export function squashify_argument(argument) {
    // Base assignment of the value
    let value = argument.value;

    if (argument.type.LENGTH) {
        value = argument.value.map((argument) => squashify_argument(argument));
    } else if (argument.type.MEMBER_LIST) {
        value = {};
        for (let i = 0; i < argument.type.MEMBER_LIST.length; i++) {
            let field = argument.type.MEMBER_LIST[i][0];
            value[field] = squashify_argument(argument.value[field]);
        }
    } else if (["U64Type"].indexOf(argument.type.name) !== -1) {
        if (argument.value.startsWith("0x")) {
            // Hexadecimal
            value = BigInt(argument.value, 16);
        } else if (argument.value.startsWith("0b")) {
            // Binary
            value = BigInt(argument.value.slice(2), 2);
        } else if (argument.value.startsWith("0o")) {
            // Octal
            value = BigInt(argument.value.slice(2), 8);
        } else {
            // Decimal
            value = BigInt(argument.value, 10);
        }
    } else if (["U32Type", "U16Type", "U8Type"].indexOf(argument.type.name) !== -1) {
        if (argument.value.startsWith("0x")) {
            // Hexadecimal
            value = parseInt(argument.value, 16);
        } else if (argument.value.startsWith("0b")) {
            // Binary
            value = parseInt(argument.value.slice(2), 2);
        } else if (argument.value.startsWith("0o")) {
            // Octal
            value = parseInt(argument.value.slice(2), 8);
        } else {
            // Decimal
            value = parseInt(argument.value, 10);
        }
    }
    else if (["I64Type"].indexOf(argument.type.name) !== -1) {
        value = BigInt(argument.value, 10);
    }
    else if (["I32Type", "I16Type", "I8Type"].indexOf(argument.type.name) !== -1) {
        value = parseInt(argument.value, 10);
    }
    else if (["F64Type", "F32Type"].indexOf(argument.type.name) !== -1) {
        value = parseFloat(argument.value);
    }
    else if (argument.type.name == "BoolType") {
        if ((typeof(value) === "string") && (["true", "yes"].indexOf(value.toLowerCase()) !== -1)) {
            value = true;
        } else if ((typeof(value) === "string") && (["false", "no"].indexOf(value.toLowerCase()) !== -1)) {
            value = false;
        } else {
            console.assert(typeof(value) !== "boolean", "Cannot process boolean, invalid input type")
        }
    }
    return value;
}

/**
 * Convert an argument into a display string. This is used for the string input box and additionally the command
 * history table. Replaces null (unset) argument values with "" for strings, the first enum member for enums, and an
 * empty string for string types. Recursively handles complex types.
 * @param argument: argument to display
 * @returns: string to display
 */
export function argument_display_string(argument) {
    let string = FILL_NEEDED;
    try {
        // Check for array
        if (argument.type.LENGTH) {
            string = `[${argument.value.map((argument) => argument_display_string(argument)).join(", ")}]`;
        }
        // Serializable
        else if (argument.type.MEMBER_LIST) {
            let fields = [];
            for (let i = 0; i < argument.type.MEMBER_LIST.length; i++) {
                let field = argument.type.MEMBER_LIST[i][0];
                fields.push(`${field}: ${argument_display_string(argument.value[field])}`);
            }
            string = `{${fields.join(", ")}}`
        }
        // String type
        else if (argument.type.MAX_LENGTH) {
            let value = (argument.value == null) ? "" : argument.value;
            value = value.replace(/"/g, '\\\"');
            string = `"${value}"`
        }
        // Unassigned values
        else if (argument.value == null || argument.value === "") {
            string = FILL_NEEDED;
        } else {
            string = squashify_argument(argument);
        }
    } catch (e) {
        string = FILL_NEEDED;
    }
    return string;
}

/**
 * Basic setup for each argument Vue component. Each is bound to a property called "argument", which is the data store
 * of the component. Each calls the standard "validate anything" validation function.
 */
let base_argument_component_properties = {
        props:["argument", "compact"],
        methods: {
            /**
             * Trigger on argument input. Should not recurse down, but flow up.
             */
            validateTrigger() {
                this.validateArgument(false);
            },
            /**
             * Argument validation function. Will validate the input value and then assign the various error messages
             * and flags to the HTML elements where applicable. Can recurse down through children, or up through parents
             * but not both at the same time. When not explicitly stated, the validation is assumed to be upward through
             * parents
             *
             * @param recurse_down: recursively validate children moving downward
             */
            validateArgument(recurse_down) {
                recurse_down = !!(recurse_down); // Force recurse_down to be defined as a boolean
                let valid = validate_input(this.argument);
                // Each scalar argument needs to set custom validity on the HTML input that it owns. However, non-scalar
                // inputs skip this step less the first scalar child's input box be poisoned with incorrect validity due
                // to the unbounded recursive nature of getElementsByClassName used to find a fprime-input children.
                let is_scalar = [...document.getElementsByClassName("fprime-scalar-argument")]
                    .filter((scalar) => scalar === this.$el || scalar.contains(this.$el)).length > 0;

                // Now grab the singular the nearest input and report validity if and only if this is a scalar. Non-
                // scalar values are compositions of scalar children and thus validity will be set when the scalar
                // itself is validated.
                let input_element = this.$el.getElementsByClassName("fprime-input")[0] || this.$el;
                if (is_scalar && input_element.setCustomValidity && input_element.reportValidity) {
                    input_element.setCustomValidity(this.argument.error);
                    input_element.reportValidity();
                }
                // Validation can happen recursively down through the children, or up through the parent in order to
                // laterally validate complex arguments when a single input scalar filed is adjusted.
                let recursive_listing = (recurse_down) ? this.$children.slice().reverse() : [this.$parent];
                let valid_recursion = (recursive_listing || []).reduce(
                    (accumulator, next_element) => {
                        if (next_element.validateArgument) {
                            accumulator = next_element.validateArgument(recurse_down) && accumulator;
                        }
                        return accumulator;
                    }, true);
                // Only downward recursion inherits validity
                if (recurse_down) {
                    valid = valid && valid_recursion;
                }
                return valid;
            }
        }
}

// Needed to build enum selection
Vue.component('v-select', VueSelect.VueSelect);

/**
 * Structure argument component.
 */
Vue.component("command-serializable-argument", {
    ...base_argument_component_properties,
    template: command_serializable_argument_template,
});

/**
 * Array argument component.
 */
Vue.component("command-array-argument", {
    ...base_argument_component_properties,
    template: command_array_argument_template,
});

/**
 * Special enumeration processing component to render as a drop-down.
 */
Vue.component("command-enum-argument", {
    ...base_argument_component_properties,
    template: command_enum_argument_template,
});

/**
 * Special boolean processing component to render as a drop-down.
 */
Vue.component("command-bool-argument", {
    ...base_argument_component_properties,
    template: command_bool_argument_template,
});

/**
 * Scalar argument processing. Sets up the input type such that numbers can be input with the correct formatting.
 */
Vue.component("command-scalar-argument", {
    ...base_argument_component_properties,
    template: command_scalar_argument_template,
    computed: {
        /**
         * Allows for validation of commands using the HTML-based validation using regex and numbers. Note: numbers here
         * are treated as text, because we can allow for hex, and octal bases.
         * @return [HTML input type, validation regex, step (used for numbers only), and validation error message]
         */
        inputType() {
            // Unsigned integer
            if (["U64Type", "U32Type", "U16Type", "U8Type"].indexOf(this.argument.type.name) != -1) {
                // Supports binary, hex, octal, and digital
                return ["text", "0[bB][01]+|0[oO][0-7]+|0[xX][0-9a-fA-F]+|[1-9]\\d*|0", ""];
            }
            else if (["I64Type", "I32Type", "I16Type", "I8Type"].indexOf(this.argument.type.name) != -1) {
                return ["text", "-?[1-9]\\d*|0", ""];
            }
            else if (["F64Type", "F32Type"].indexOf(this.argument.type.name) != -1) {
                return ["number", null, "any"];
            }
            return ["text", ".*", null];
        }
    }
});
/**
 * Base component for processing arguments specifically. This component uses recursive templating to handle each of the
 * sub-argument types until everything is resolved as a scalar type.
 */
Vue.component("command-argument", {
    ...base_argument_component_properties,
    template: command_argument_template,
});
