/**
 * commanding/command-input.js:
 *
 * Vue JS components for handling the command input form.
 *
 * @author lestarch
 */
import {_datastore} from "../../js/datastore.js";
import {_loader} from "../../js/loader.js";
import {find_case_insensitive, validate_input} from "../../js/validate.js"
import {
    clear_argument,
    command_argument_assignment_helper,
    squashify_argument
} from "../../addons/commanding/arguments.js";
import {_settings} from "../../js/settings.js";
import {command_input_template} from "./command-input-template.js";
import { SaferParser } from "../../js/json.js";
SaferParser.register();

/**
 * This helper will help assign command and values in a safe manner by searching the command store, finding a reference,
 * and then setting the arguments as supplied.
 */
function command_assignment_helper(desired_command_name, desired_command_args, partial_command) {
    desired_command_args = (typeof(desired_command_args) == "undefined") ? [] : desired_command_args;

    // Keys should be exact matches
    let command_name = find_case_insensitive(desired_command_name, Object.keys(_datastore.commands));
    if (command_name == null && typeof(partial_command) != "undefined") {
        // Finally, commands that "start with" after the component name "."
        let keys = Object.keys(_datastore.commands).filter(command_name => {
            let tokens = command_name.split(".");
            return tokens[tokens.length - 1].startsWith(partial_command);
        });
        command_name = (keys.length > 0) ? keys[0] : null;
    }
    // Command not found, return null
    if (command_name == null) {
        return null;
    }
    let selected = _datastore.commands[command_name];

    // Set arguments here
    for (let i = 0; i < selected.args.length; i++) {
        let assign_value = (desired_command_args.length > i)? desired_command_args[i] : null;
        command_argument_assignment_helper(selected.args[i], assign_value);
    }
    return selected;
}

/**
 * Serialize an argument for transmission via the PUT request. First we squash the argument and then convert to JSON if
 * it is a complex type.
 * @param argument: argument to serialize.
 * @returns: squashed argument
 */
function serialize_arg(argument) {
    let squashed = squashify_argument(argument);

    // Serializables and arrays must be put into a JSON string
    if (argument.type.MEMBER_LIST || argument.type.LENGTH) {
        squashed = JSON.stringify(squashed);
    }
    return squashed;
}

/**
 * command-input:
 *
 * Input command form Vue object. This allows for sending commands from the GDS.
 */
Vue.component("command-input", {
    props: {
        builder: {
            type: Boolean,
            default: false
        },
        compact: {
            type: Boolean,
            default: false
        }
    },
    created: function() {
        // Make command-input component accessible from other components
        this.$root.$refs.command_input = this;
    },
    data: function() {
        // Select CMD_NO_OP by default if it exists, otherwise select the first command
        let selected = command_assignment_helper("cmdDisp.CMD_NO_OP", [], "CMD_NO_OP");
        selected = (selected != null)? selected : Object.values(_datastore.commands)[0];
        return {
            "commands": _datastore.commands,
            "loader": _loader,
            "selected": selected,
            "active": false,
            "error": "",
        }
    },
    template: command_input_template,
    methods: {
        /**
         * Clear the arguments to the command.
         */
        clearArguments() {
            // Clear arguments
            for (let i = 0; i < this.selected.args.length; i++) {
                clear_argument(this.selected.args[i]);
            }
        },
        /**
         * Trigger to start validation on the selection.
         */
        validateTrigger() {
            this.$nextTick(() => {
                this.validate();
            });
        },
        /**
         * Validate the form inputs using the browser validation method. Additionally, validates the command input and
         * argument select dialogs to ensure that dropdown values are within the allowed list
         */
        validate() {
            // Find form and check validity
            let form = this.$el.getElementsByClassName("command-input-form")[0];
            form.classList.add('was-validated');
            let valid = true;

            // Validate command exists in command dropdown
            let valid_name = find_case_insensitive(this.selected.full_name, Object.keys(_datastore.commands));
            if (valid_name == null) {
                this.error = this.selected.full_name + " is not a command.";
                valid = false;
            } else {
                this.selected = _datastore.commands[valid_name];
                this.error = "";
            }
            // Validate enumeration types
            let valid_children = (this.$children || []).slice().reverse().reduce((accumulator, child) => {
                if (child.validateArgument) {
                    accumulator = child.validateArgument(true) && accumulator;
                }
                return accumulator
            }, true);
            let form_valid = form.checkValidity();
            return valid_children && form_valid;
        },
        /**
         * Send a command from this interface. This calls into the loader to send the command, and locks-out until the
         * command reaches the ground system.
         */
        sendCommand() {

            // Validate the command before sending anything
            if (!this.validate()) {
                return;
            }
            let form = this.$el.getElementsByClassName("command-input-form")[0];
            form.classList.remove('was-validated');

            // Send the command and respond to results
            let _self = this;
            _self.active = true;
            let command = this.selected;
            let squashed_args = command.args.map(serialize_arg);
            this.loader.load("/commands/" + command.full_name, "PUT",
                {"key":0xfeedcafe, "arguments": squashed_args})
                .then(function() {
                    _self.active = false;
                    // Clear errors, as there is not a problem further
                    for (let i = 0; i < command.args.length; i++) {
                        command.args[i].error = "";
                    }
                })
                .catch(function(err) {
                    // Log all errors incoming
                    console.error("[ERROR] Failed to send command: " + err);
                    let errors = JSON.parse(err).errors || [{"message": "Unknown error"}];
                    for (let i = 0; i < errors.length; i++) {
                        let error_message = errors[i].message || errors[i];
                        error_message = error_message.replace("400 Bad Request:", "");
                        let argument_errors = errors[i].args || [];
                        for (let j = 0; j < argument_errors.length; j++) {
                            command.args[j].error =argument_errors[j];
                        }
                        command.error = error_message;
                        _self.error = error_message;
                    }
                    _self.active = false;
                });
        },
        /**
         * Function used to set the currently active command give a name and a set of arguments. This function will find
         * the command via name and override the arguments to be supplied.  If the command is not found, an invalid
         * "fake" command will be passed in.
         * @param desired_command_name: full name of command to find
         * @param desired_command_args": arguments to pass to command
         */
        selectCmd(desired_command_name, desired_command_args) {
            let found_command = command_assignment_helper(desired_command_name, desired_command_args);
            if (found_command !== null) {
                this.selected = found_command;
            } else {
                this.selected = {"full_name": desired_command_name, "args":[], "error": "Invalid command"};
            }
            this.$nextTick(() => {
                this.validate();
            });
        }
    },
    computed: {
        /**
         * List out the usable commands to be sent by the ground system.
         * @return {unknown[]}
         */
        commandList() {
            return Object.values(this.commands).sort(
                /**
                 * Compare objects by full_name
                 * @param obj1: first object
                 * @param obj2: second object
                 * @return {number} -1 or 1
                 */
                function(obj1, obj2) {
                    if (obj1.full_name.toLowerCase() <= obj2.full_name.toLowerCase()) {
                        return -1;
                    }
                    return 1;
                });
        }
    }
});
