/**
 * commanding/command-string.js:
 *
 * Vue JS components for handling the command string input box.
 *
 * @author lestarch
 */
import {
    COMMAND_FORMAT_SPEC,
    command_string_template
} from "./command-string-template.js";
import {argument_display_string, FILL_NEEDED} from "./arguments.js"
import {SaferParser} from "../../js/json.js";
SaferParser.register();

let STRING_PREPROCESSOR = new RegExp(`(?:"((?:[^\"]|\\\")*)")|([a-zA-Z_][a-zA-Z_0-9.]*)|(${FILL_NEEDED})`, "g");

/**
 * Gets the display string for the given command.
 * @param command_obj: command object to turn into a string
 * @returns: string form of the command
 */
export function command_display_string(command_obj) {
    let rendered_arguments = (command_obj.args || []).map(argument_display_string);
    return [command_obj.full_name].concat(rendered_arguments).join(", ");
}

/**
 * Component to show the command text and allow textual input. Keeps the component synchronized with the command input
 * fields.
 */
Vue.component("command-text", {
    props: ["selected"],
    data() { return {"error": ""}},
    template: command_string_template,
    methods: {
        validate() {
            this.error = "";
            let input_element = this.$el.getElementsByClassName("fprime-input")[0] || this.$el;
            if (typeof(input_element.setCustomValidity) !== "undefined") {
                input_element.setCustomValidity(this.error);
                input_element.reportValidity();
            }
        }
    },
    computed: {
        text: {
            // Get the expected text from the command and inject it into the box
            get: function () {
                this.error = "";
                return command_display_string(this.selected);
            },
            // Pull the box and send it into the command setup
            set: function (inputValue) {
                this.error = "";
                try {
                    let corrected_json_string = `[${inputValue.replace(STRING_PREPROCESSOR, "\"$1$2$3\"")}]`;
                    let tokens = JSON.parse(corrected_json_string);
                    let command_name = tokens[0];
                    let command_arguments = tokens.splice(1);
                    this.error = "";
                    this.$parent.selectCmd(command_name, command_arguments);
                } catch (e) {
                    // JSON parsing exceptions
                    if (e instanceof SyntaxError) {
                        this.error = `Expected command string of the form: ${COMMAND_FORMAT_SPEC}.`;
                    } else {
                        throw e;
                    }
                }
            }
        }
    }
});