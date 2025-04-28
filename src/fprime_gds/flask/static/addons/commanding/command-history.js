/**
 * commanding/command-history.js:
 *
 * Vue JS components for handling the command history table.
 *
 * @author lestarch
 */
import {_datastore, _dictionaries} from "../../js/datastore.js";
import {command_argument_assignment_helper} from "./arguments.js";
import {listExistsAndItemNameNotInList, timeToString} from "../../js/vue-support/utils.js";
import {command_history_template} from "./command-history-template.js";
import {command_display_string} from "./command-string.js";
import { SaferParser } from "../../js/json.js";
SaferParser.register();

/**
 * command-history:
 *
 * Displays a list of previously-sent commands to the GDS. This is a reuse of the fptable defining functions and
 * properties needed to allow for the command history to be displayed.
 */
Vue.component("command-history", {
    props: {
        /**
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
    template: command_history_template,
    methods: {
        /**
         * Converts a given item into columns.
         * @param item: item to convert to columns
         */
        columnify(item) {
            let command_copy = JSON.parse(JSON.stringify(_dictionaries.commands_by_id[item.id]));
            for (let i = 0; i < command_copy.args.length; i++) {
                command_argument_assignment_helper(command_copy.args[i], item.args[i]);
            }
            return [timeToString(item.datetime || item.time), command_display_string(command_copy)];
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
        * On double-click on a row in command history table populate the
        * command and its arguments in the command input template
        */
        clickAction(item) {
            let cmd = item;
            let template = _dictionaries.commands_by_id[item.id];
            cmd.full_name = template.full_name;
            // Can only set command if it is a child of a command input
            if (this.$parent.selectCmd) {
                // command-input expects an array of strings as arguments
                this.$parent.selectCmd(cmd.full_name, cmd.args);
            }
        }
    }
});
