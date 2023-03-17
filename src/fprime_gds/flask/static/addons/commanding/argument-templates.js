/**
 * commanding/addon-templates.js:
 *
 * Contains the templates used to render the various commanding views on the commanding tab.
 */

/**
 * Enum argument uses the v-select dropdown to render the various choices while providing search and match capabilities.
 */
export let command_enum_argument_template = `
<v-select :id="argument.name" style="flex: 1 1 auto; background-color: white;"
          :clearable="false" :searchable="true" @input="validate"
          :filterable="true"  label="full_name" :options="Object.keys(argument.type.ENUM_DICT)"
          v-model="argument.value" class="fprime-input" :class="argument.error == '' ? '' : 'is-invalid'" required>
</v-select>
`;

/**
 * Serializable arguments "flatten" the structure into a list of fields.
 */
export let command_serializable_argument_template = `
<div style="display: contents;">
    <command-argument :argument="pseudo_arg" v-for="pseudo_arg in argument.value"></command-argument>
</div>
`;

/**
 * Array arguments "flatten" the array into a list of fields.
 */
export let command_array_argument_template = `
<div style="display: contents;">
    <command-argument :argument="pseudo_arg" v-for="pseudo_arg in argument.value"></command-argument>
</div>
`;

/**
 * Scalar argument own the actual input data. Therefore, they print the necessary label, input box/dropdown, etc. Note:
 * enumerations are handled here as they represent a single scalar input.
 */
export let command_scalar_argument_template = `
<div style="display: contents;">
    <div class="form-group col-md-6">
        <label :for="argument.name" class="control-label font-weight-bold">
            {{ argument.name + ((argument.description != null) ? ": " + argument.description : "") }}
        </label>
        
        <command-enum-argument v-if="argument.type.ENUM_DICT" :argument="argument"></command-enum-argument>
        <input v-else :type="inputType[0]" v-bind:id="argument.name" class="form-control fprime-input"
               :placeholder="argument.name" :pattern="inputType[1]" :step="inputType[2]" v-on:input="validate"
               v-model="argument.value"  :class="argument.error == '' ? '' : 'is-invalid'" required>
        <div class="invalid-feedback">{{ argument.error }}</div>
    </div>
</div>
`;

/**
 * Command arguments have inherently three options: array, serializable, or scalar. Arrays and serializableses are
 * recursive in that they will use this component within their templates.
 */
export let command_argument_template = `
<div style="display: contents;">
    <command-array-argument v-if="argument.type.LENGTH" :argument="argument"></command-array-argument>
    <command-serializable-argument v-else-if="argument.type.MEMBER_LIST" :argument="argument"></command-serializable-argument>
    <command-scalar-argument v-else :argument="argument"></command-scalar-argument>
</div>
`;