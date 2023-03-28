/**
 * channel-render-template.js:
 *
 * Contains template data for channel-render including the replacement fp-row template called channel-row and the
 * recursive rendering channel-render element designed to render a single channel.
 *
 * @author lestarch
 */

/**
 * channel-render displays a single channel item. If that channel happens to be a complex type, then the channel is
 * recursively rendered using channel-render itself.
 *
 * When a channel has nothing to display, then the field is kept blank and does not recurse.
 */
export let channel_render_template = `
<span v-if="!(type?.LENGTH || type?.MEMBER_LIST)">{{ displayText }}</span>
<table v-else-if="type?.LENGTH || type?.MEMBER_LIST" class="embedded_table table">
    <thead>
        <tr>
            <th class="sorttable_nosort">
                <i v-show="!expanded" class="fas fa-plus" @click="expand"></i>
                <i v-show="expanded" class="fas fa-minus" @click="collapse"></i>
            </th>
            <th>{{ displayText }}</th>
        </tr>
    </thead>
    <tbody>
        <tr v-show="expanded" v-for="element_index in childIndices">
            <th>{{element_index}}</th>
            <td>
                <channel-render :element_type="childType(element_index)" :val="(val || [])[element_index]">
                </channel-render>
            </td>
        </tr>
    </tbody>
</table>
`;

/**
 * Channel row display. Same template as fp-row, except for the cell element of index -1 which is rendered as the
 * channel-render element instead.
 */
export let channel_row_template = `
<tr :class="calculateStyle">
    <th v-if="editing" v-on:input="onInput"><input type="checkbox" :checked="inView"></th>
    <td v-for="(column, index) in calculatedColumns" v-on:dblclick="clickAction(item)">
        <channel-render :item="item" :val="item.val" v-if="index == calculatedColumns.length - 1">
        </channel-render>
        <span v-else>{{ column }}</span>
    </td>
</tr>
`;