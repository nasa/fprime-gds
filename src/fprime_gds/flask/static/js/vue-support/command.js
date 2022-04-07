/**
 * command.js:
 *
 * Contains the Vue components for displaying the command history, and the command sending form.
 */
// Setup component for select
import "../../third-party/js/vue-select.js"
import {listExistsAndItemNameNotInList, timeToString} from "./utils.js";
import {_datastore} from "../datastore.js";
import {_loader} from "../loader.js";
import {find_case_insensitive, validate_input} from "../validate.js"


/**
 * This helper will help assign command and values in a safe manner by searching the command store, finding a reference,
 * and then setting the arguments as supplied.
 */
function command_assignment_helper(desired_command_name, desired_command_args, partial_command) {
    desired_command_args = (typeof(desired_command_args) == "undefined")? [] : desired_command_args;

    // Keys should be exact matches
    let command_name = find_case_insensitive(desired_command_name, Object.keys(_datastore.commands));
    if (command_name == null && typeof(partial_command) != "undefined") {
        // Finally commands that "start with" after the component name "."
        let keys = Object.keys(_datastore.commands).filter(command_name => {
            let tokens = command_name.split(".");
            return tokens[tokens.length - 1].startsWith(partial_command);
        });
        command_name = (keys.length > 0)? keys[0] : null;
    }
    // Command not found, return null
    if (command_name == null) {
        return null;
    }
    let selected = _datastore.commands[command_name];
    // Set arguments here
    for (let i = 0; i < selected.args.length; i++) {
        let assign_value = (desired_command_args.length > i)? desired_command_args[i] : "";
        selected.args[i].value = assign_value;
    }
    return selected;
}

function parse_with_strings(remaining) {
    let tokens = [];
    while (remaining !== "") {
        let reg = /([, ] *)/;
        if (remaining.startsWith("\"")) {
            remaining = remaining.slice(1);
            reg = /"([, ] *|$)/;
        }
        let match = remaining.match(reg);
        let index = (match !== null) ? match.index : remaining.length;
        let first = remaining.slice(0, index);
        tokens.push(first);
        remaining = remaining.slice(index + ((match !== null) ? match[0].length : remaining.length));
    }
    return tokens;
}

Vue.component('v-select', VueSelect.VueSelect);
/**
 * Command argument component
 */
Vue.component("command-argument", {
    props:["argument"],
    template: "#command-argument-template",
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
        },
        /**
         * Unpack errors on arguments, for display in this GUI.
         */
        argumentError() {
            if ("error" in this.argument) {
                return this.argument.error;
            }
            return "NO ERROR!!!";
        }
    },
    methods: {
        /**
         * Validate selected element.  This patches the missing validation of text->vue select.  Otherwise it defers to
         * the normal form validation
         */
        validate() {
            let input_element = this.$el.getElementsByClassName("fprime-input")[0];
            this.argument.error = "";
            validate_input(this.argument);
            // Not all base elements support errors
            if (typeof(input_element.setCustomValidity) !== "undefined") {
                input_element.setCustomValidity(this.argument.error);
            }
        }
    }
});
/**
 * Component to show the command text and allow textual input.
 */
Vue.component("command-text", {
    props:["selected"],
    template: "#command-text-template",
    computed: {
        text: {
            // Get the expected text from the command and inject it into the box
            get: function () {
                let tokens = [this.selected.full_name].concat(Array.from(this.selected.args,
                    (arg) => {return (arg.type === "String" && arg.value != null) ? '"' + arg.value + '"' : arg.value}));
                let cli = tokens.filter(val => {return val !== "";}).join(" ");
                return cli;
            },
            // Pull the box and send it into the command setup
            set: function (inputValue) {
                let tokens = parse_with_strings(inputValue);
                let name = tokens[0];
                let cargs = tokens.splice(1);
                this.$parent.selectCmd(name, cargs);
            }
        }
    }
});


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
        }
    },
    created: function() {
        // Make command-input component accessible from other components
        this.$root.$refs.command_input = this;
    },
    data: function() {
        let selected = command_assignment_helper(null, [], "CMD_NO_OP");
        selected = (selected != null)? selected : Object.values(_datastore.commands)[0];
        return {
            "commands": _datastore.commands,
            "loader": _loader,
            "selected": selected,
            "active": false,
            "error": ""
        }
    },
    template: "#command-input-template",
    methods: {
        /**
         * Clear the arguments to the command.
         */
        clearArguments() {
            // Clear arguments
            for (let i = 0; i < this.selected.args.length; i++) {
                this.selected.args[i].error = "";
                if ("possible" in this.selected.args[i]) {
                    this.selected.args[i].value = this.selected.args[i].possible[0];
                } else {
                    this.selected.args[i].value = "";
                }
            }
        },
        /**
         * Validate the form inputs using the browser validation method. Additionally validates the command input and
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
            let args = this.selected.args;
            for (let i = 0; i < args.length; i++) {
                let current_valid = validate_input(args[i]);

                valid = valid && current_valid;
            }
            let form_valid = form.checkValidity();
            return valid && form_valid;
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
            this.loader.load("/commands/" + command.full_name, "PUT",
                {"key":0xfeedcafe, "arguments": command.args.map(arg => {return arg.value;})})
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
            if (found_command != null) {
                this.selected = found_command;
            } else {
                this.selected = {"full_name": desired_command_name, "args":[], "error": "Invalid command"};
            }
            this.validate();
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
                    if (obj1.full_name <= obj2.full_name) {
                        return -1;
                    }
                    return 1;
                });
        }
    }
});



/**
 * command-item:
 *
 * For displaying commands in the historical list of commands.
 */
Vue.component("command-item", {
    props:["command"],
    template: "#command-item-template",
    computed: {
        /**
         * Produces the channel's time in the form of a string.
         * @return {string} seconds.microseconds
         */
        calculateCommandTime: function() {
            return timeToString(this.command.datetime || this.command.time);
        }
    }
});

/**
 * command-history:
 *
 * Displays a list of previously-sent commands to the GDS. This is a reuse of the fptable defining functions and
 * properties needed to allow for the command history to be displayed.
 */
Vue.component("command-history", {
    props: {
        /**
         * fields:
         *
         * Fields to display on this object. This should be null, unless the user is specifically trying to minimize
         * this object's display.
         */
        fields: {
            type: [Array, String],
            default: ""
        },
        /**
         * The search text to initialize the table filter with (defaults to
         * nothing)
         */
        filterText: {
            type: String,
            default: ""
        },
        /**
         * A list of item ID names saying what rows in the table should be
         * shown; defaults to an empty list, meaning "show all items"
         */
        itemsShown: {
            type: [Array, String],
            default: ""
        },
        /**
         * 'compact' allows the user to hide filters/buttons/headers/etc. to
         * only show the table itself for a cleaner view
         */
        compact: {
            type: Boolean,
            default: false
        }
    },
    data: function() {
        return {
            "cmdhist": _datastore.command_history,
            "matching": ""
        }
    },
    template: "#command-history-template",
    methods: {
        /**
         * Converts a given item into columns.
         * @param item: item to convert to columns
         */
        columnify(item) {
            let values = [];
            for (let i = 0; i < item.arg_vals.length; i++) {
                values.push(item.arg_vals[i]);
            }
            return [timeToString(item.datetime || item.time), "0x" + item.id.toString(16), item.template.full_name, values.join(" ")];
        },
        /**
         * Take the given item and converting it to a unique key by merging the id and time together with a prefix
         * indicating the type of the item. Also strip spaces.
         * @param item: item to convert
         * @return {string} unique key
         */
        keyify(item) {
            return "cmd-" + item.id + "-" + item.time.seconds + "-"+ item.time.microseconds;
        },
        /**
         * Returns if the given item should be hidden in the data table; by
         * default, shows all items. If the "itemsShown" property is set, only
         * show items with the given names
         *
         * @param item: The given F' data item
         * @return {boolean} Whether or not the item is shown
         */
        isItemHidden(item) {
            return listExistsAndItemNameNotInList(this.itemsShown, item);;
        },
        /**
        * On double click on a row in command history table populate the 
        * command and its arguments in the command input template
        */
        clickAction(item) {
            let cmd = item;
            cmd.full_name = item.template.full_name;
            // Can only set command if it is a child of a command input
            if (this.$parent.selectCmd) {
                this.$parent.selectCmd(cmd.full_name, cmd.arg_vals, arg => arg);
            }
        }
    }
});
