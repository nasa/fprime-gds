/**
 * commanding/command-history-templates.js:
 *
 * Contains the templates used to render the command history table using the fp-table table component.
 */
export let command_history_template = `
<div class="fp-flex-repeater">
    <fp-table :header-columns="['Command Time', 'Command String']"
              :items-key="'command_history'"
              :item-to-columns="columnify"
              :item-to-unique="keyify"
              :item-hide="isItemHidden"
              :initial-fields="fields"
              :filter-text="filterText"
              :initial-views="itemsShown"
              :compact="compact"
              :click-action="clickAction"
              :reverse="true"
              class="click-able-item">
    </fp-table>
</div>
`;