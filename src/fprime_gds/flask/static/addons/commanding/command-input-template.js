/**
 * commanding/command-input-templates.js:
 *
 * Contains the templates used to render the command input form.
 */
export let command_input_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2 v-if="!builder">Sending Command: {{ selected.full_name }}</h2>
        <form v-on:submit.prevent="() => {return false;}" class="command-input-form" novalidate>
            <div class="form-row">
                <div class="form-group col-md-4">
                    <label for="mnemonic" class="control-label font-weight-bold">Mnemonic</label>
                    <v-select id="mnemonic" style="flex: 1 1 auto; background-color: white;" :clearable="false"
                        :searchable="true" @input="validateTrigger" :filterable="true" label="full_name"
                        :options="commandList" v-model="selected" :class="this.error == '' ? '' : 'is-invalid'"
                        required>
                    </v-select>
                    <div class="invalid-feedback">{{ (this.error != '')? this.error : "Supply valid command"}}</div>
                </div>
            </div>
            <div class="form-row" v-if="selected.description != null">
                <label class="control-label font-weight-bold">Description: </label>
                {{ selected.description }}
            </div>
            <div class="form-row" v-if="selected.args.length > 0">
                <Label class="control-label font-weight-bold"l>Arguments</Label>
            </div>
            <div class="form-row"> 
                <command-argument :compact="compact" :argument="argument"
                    v-for="argument in selected.args">
                </command-argument>
            </div>
            <div class="form-row">
                <div class="form-group col-md-4">
                    <div class="form-row">
                        <div class="col-md-6 mb-1">
                            <button type="button" class="btn btn-outline-secondary btn-block"
                                v-on:click="clearArguments">
                                <i class="fas fa-eraser"></i>
                                <span class="d-md-none d-lg-inline">Clear Arguments</span>
                            </button>
                        </div>
                        <div class="col-md-6 mb-1">
                            <button type="button" v-if="!builder" v-on:click="sendCommand" :disabled="active"
                                class="btn btn-primary btn-block">
                                <i class="fas fa-paper-plane"></i>
                                <span class="d-md-none d-lg-inline">Send Command</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
    <command-text :selected="selected"></command-text>
    <command-history v-if="!builder"></command-history>
</div>
`;