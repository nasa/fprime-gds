/**
 * commanding/command-string-templates.js:
 *
 * Contains the templates used to render the command string input box.
 */
export let COMMAND_FORMAT_SPEC = "FULL_COMMAND_NAME[[[, ARG1], ARG2], ...] " +
    "where ARGN is a decimal number, quoted string, or an enumerated constant";

export let command_string_template = `
<div class="fp-flex-repeater">
    <div class="form-row">
        <div class="form-group col-12">
            <h5>Command String</h5>
            <input type="text" name="command-text" class="form-control fprime-input" v-model.lazy="text"
                placeholder="Command string of the form: ${COMMAND_FORMAT_SPEC}"
                :class="this.error == '' ? '' : 'is-invalid'" @focus="validate">
            <div class="invalid-feedback">{{ this.error }}</div>
        </div>
    </div>
</div>
`;