/**
 * fp-row:
 *
 * Component representing a single row of the table. This allows independent styling and computed functions applied to
 * the row. Will be composed (en masse) into the full fp-table. It has several properties that are required to be
 * supplied:
 *
 * -item: a single item object to bind into the row
 * -itemToColumns: a function harvesting out data from an item into the columns
 *
 * Note: fp-row is broken up such that other row implementations can inherit the base properties.
 */

let headerRegex = new RegExp("&lt;h([1-6])&gt;([^&]*)&lt;/h[1-6]&gt;", "g");
let spanRegex = new RegExp("&lt;span( title=\"[^\"]*\")?&gt;([^&]*)&lt;/span&gt;", "g");

/**
 * Replace strings keeping <h1> - <h6> and <span...> tags.
 * @param {*} item: display item 
 * @returns: sanitized display item
 */
function sanitize(item) {
    if (typeof(item) !== "string") {
        return item;
    }
    // Remove all HTML tags
    item = item.replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    // Put back in h[1-6] and span tags
    item = item.replaceAll(headerRegex, "<h$1>$2</h$1>")
               .replaceAll(spanRegex, "<span $1>$2</span>");
    return item;
}


export let fp_row_base_component = {
    template: "#fp-row-template",
    props: {
        /**
         * item:
         *
         * 'item' will be automatically bound to each item in the 'items' list of the consuming table. It is the loop
         * variable, and will be passed into the 'itemToColumns' function to produce columns.
         */
        item: Object,
        /**
         * itemToColumns:
         *
         * 'itemToColumns' will be bound to a function taking one item from the parent fp-table object. See fp-table.
         */
        itemToColumns: [Array, Function],
        /**
         * rowStyle:
         *
         * 'rowStyle' should be bound to a string of static style for the given row, or a Function taking a single item
         * as input and used to calculate that style. If a Function is used, it should return a string. The String or
         * return value must be compatible with the HTML class attribute. This will be passed to the child fp-row.
         *
         * See: fp-table
         */
        rowStyle: [String, Function],
        /**
         * 'editing':
         *
         * Has the parent entered editing mode to select rows for views.
         */
        editing: Boolean,
        /**
         * inView:
         *
         * A boolean showing if this row is in the current view.
         */
        inView: {
            type: Boolean,
            default: true
        },
        /**
         * Action to perform when the clicked row has been clicked.
         */
        clickAction: {
            type: Function,
            default: (item) => {},
        },
        /**
         * An array of indices that are visible.
         */
        visible: {
            type: Array,
            default: null
        },
    },
    methods: {
        /**
         * Function handling inputs on child and emitting them back to the parent to select this row as selected. This
         * allows the parent to track the selected list.
         * @param event: event kicking off this change
         */
        onInput: function(event) {
            this.$emit("row-checked", {"child": this.item, "value": event.target.checked});
        }
    },
    computed: {
        /**
         * Calls the itemToColumns function to return the columns Array. This is *required* and will raise an error if
         * the itemToColumns variable has not been bound to.
         */
        calculatedColumns: function () {
            if (typeof (this.itemToColumns) !== "function") {
                throw Error("Failed to define required 'itemToColumns' function on fp-table")
            }
            return this.itemToColumns(this.item)
                .map(sanitize)
                .filter((item, index) => this.visible == null || this.visible.indexOf(index) !== -1);
        },
        /**
         * Calculates the style of the row based on a given item. This is optional and will not raise an error if the
         * rowStyle function has not been bound to.
         */
        calculateStyle: function () {
            if (typeof (this.rowStyle) === "function") {
                return this.rowStyle(this.item);
            }
            return this.rowStyle;
        }
    }
}
// Create the real component
Vue.component("fp-row", {...fp_row_base_component});