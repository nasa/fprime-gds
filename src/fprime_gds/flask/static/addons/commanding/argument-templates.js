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
          :clearable="false" :searchable="true" @input="validateTrigger"
          :filterable="true"  label="full_name" :options="Object.keys(argument.type.ENUM_DICT)"
          v-model="argument.value" class="fprime-input" :class="argument.error == '' ? '' : 'is-invalid'" required>
</v-select>
`;

/**
 * Enum argument uses the v-select dropdown to render the various choices while providing search and match capabilities.
 */
export let command_bool_argument_template = `
<v-select :id="argument.name" style="flex: 1 1 auto; background-color: white;"
          :clearable="false" :searchable="true" @input="validateTrigger"
          :filterable="true"  label="full_name" :options="['True', 'False']"
          v-model="argument.value" class="fprime-input" :class="argument.error == '' ? '' : 'is-invalid'" required>
</v-select>
`;

/**
 * Serializable arguments "flatten" the structure into a list of fields.
 */
export let command_serializable_argument_template = `
<div v-if="compact" style="display: contents;">
    <command-argument :compact="compact" :argument="pseudo_arg" v-for="pseudo_arg in argument.value">
    </command-argument>
</div>
<fieldset v-else class="form-row fp-subform">
    <legend> {{ argument.name + " (" + argument.type.name + ")"}}</legend>
    <div v-if="argument.description != ''" class="form-row"><span class="font-weight-bold">Description:</span>
        {{ argument.description }}
    </div>
    <div class="form-row">
        <command-argument :compact="compact" :argument="pseudo_arg" v-for="pseudo_arg in argument.value">
        </command-argument>
    </div>
    <div class="form-row fp-error">{{ argument.error }}</div>
</fieldset>
`;

/**
 * Array arguments "flatten" the array into a list of fields.
 */
export let command_array_argument_template = `
<div v-if="compact" style="display: contents;">
    <command-argument :compact="compact" :argument="pseudo_arg" v-for="pseudo_arg in argument.value">
    </command-argument>
</div>
<fieldset v-else class="form-row fp-subform">
    <legend>{{ argument.name + " (" + argument.type.name + ")"}}</legend>
    <div class="form-row">
        <command-argument :compact="compact" :argument="pseudo_arg" v-for="pseudo_arg in argument.value">
        </command-argument>
    </div>
    <div class="form-row fp-error">{{ argument.error }}</div>
</fieldset>
`;

/**
 * Scalar argument own the actual input data. Therefore, they print the necessary label, input box/dropdown, etc. Note:
 * enumerations are handled here as they represent a single scalar input.
 */
export let command_scalar_argument_template = `
<div style="display: contents;" class="fprime-scalar-argument">
    <div class="form-group col-md-6">
        <label :for="argument.name" class="control-label font-weight-bold">
            {{ argument.name + ((argument.description != null) ? ": " + argument.description : "") }}
        </label>
        <command-bool-argument v-if="argument.type.name == 'BoolType'" :argument="argument"></command-bool-argument>
        <command-enum-argument v-else-if="argument.type.ENUM_DICT" :argument="argument"></command-enum-argument>
        <input v-else :type="inputType[0]" v-bind:id="argument.name" class="form-control fprime-input"
               :placeholder="argument.name" :pattern="inputType[1]" :step="inputType[2]" v-on:input="validateTrigger"
               v-model="argument.value"  :class="argument.error == '' ? '' : 'is-invalid'" required>
        <div class="invalid-feedback">{{ argument.error }}</div>
    </div>
</div>
`;

/**
 * Command arguments have inherently three options: array, serializable, or scalar. Arrays and serializables are
 * recursive in that they will use this component within their templates.
 */
export let command_argument_template = `
<command-array-argument v-if="argument.type.LENGTH" :argument="argument" :compact="compact">
</command-array-argument>
<command-serializable-argument v-else-if="argument.type.MEMBER_LIST" :argument="argument" :compact="compact">
</command-serializable-argument>
<command-scalar-argument v-else :argument="argument" :compact="compact"></command-scalar-argument>
`;
