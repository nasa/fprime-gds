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
    command_enum_argument_template,
    command_array_argument_template,
    command_serializable_argument_template,
    command_scalar_argument_template,
    command_argument_template
} from "./argument-templates.js";
import {validate_input} from "../../js/validate.js";

/**
 * Basic setup for each argument Vue component. Each is bound to a property called "argument", which is the data store
 * of the component. Each calls the standard "validate anything" validation function.
 */
let base_argument_component_properties = {
        props:["argument"],
        methods: {
            /**
             * Argument validation function. Will validate the input value and then assign the various error messages
             * and flags to the HTML elements where applicable.
             */
            validate() {
                validate_input(this.argument);
                let input_element = this.$el.getElementsByClassName("fprime-input")[0] || this.$el;
                if (typeof(input_element.setCustomValidity) !== "undefined") {
                    input_element.setCustomValidity(this.argument.error);
                    input_element.reportValidity();
                }
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
            if (this.argument.type.name[0] == 'U') {
                // Supports binary, hex, octal, and digital
                return ["text", "0[bB][01]+|0[oO][0-7]+|0[xX][0-9a-fA-F]+|[1-9]\\d*|0", ""];
            }
            else if (this.argument.type.name[0] == 'I') {
                return ["number", null, "1"];
            }
            else if (this.argument.type.name[0] == 'F') {
                return ["number", null, "any"];
            }
            return ["text", ".*", null];
        }
    }
});
/**
 * Base component for processing arguments specifically. This component uses recursive templating to handle each of the
 * sub-argument types until everything is resolved as a scalar type
 */
Vue.component("command-argument", {
    ...base_argument_component_properties,
    template: command_argument_template,
});
