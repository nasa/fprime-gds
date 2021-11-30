/**
 * Templates file for the sequencer plugin.  Contains the HTML template setup.
 */
export let sequencer_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2>Command Sequencer</h2>
        <form v-on:submit.prevent="() => { return false;}" class="was-validated" novalidate>
            <div class="form-group form-row">
                <div class="form-group col-md-4 mt-2" for="sequence">
                    <input type="text" id="sequence" class="form-control" v-model.trim="sequence.name" :disabled="active"
                        pattern="[^;\\\\\\/]+\\.seq" placeholder="Sequence name ending in .seq" required />
                    <div class="invalid-feedback">{{ (messages.error) ? messages.error : "Supply filename ending with .seq" }}</div>
                </div>
                <div class="form-group col-md-4 mt-2">
                    <button class="col-md-5 btn btn-primary ml-1" :disabled="active" v-on:click="sendSequence(true)">
                        <i class="fas fa-satellite-dish"></i> <span class="d-md-none d-lg-inline">Uplink</span>
                    </button>
                </div>
                <div class="form-group col-md-4 mt-2">
                    <div class="form-row">
                        <div class="col-md-4 mb-1">
                            <button class="btn btn-secondary btn-block" v-on:click="builder = !builder">
                                <i class="fas fa-tools"></i> 
                                <span class="d-md-none d-lg-inline">Build</span>
                            </button>
                        </div>
                        <div class="col-md-4 mb-1">
                            <button class="btn btn-secondary btn-block" :disabled="active" v-on:click="download">
                                <i class="fas fa-save"></i>
                                <span class="d-md-none d-lg-inline">Save As</span>
                            </button>
                        </div>
                        <div class="col-md-4 mb-1">
                            <input type="file" id="sequenceUpload" accept=".seq"
                                v-on:change="setSequence($event.target.files[0])" style="display: none;"/>
                            <label for="sequenceUpload" class="btn btn-secondary  btn-block">
                                <i class="fas fa-folder-open"></i>
                                <span class="d-md-none d-lg-inline">Open</span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>
        </form>
    </div>
    <transition name="fade">
        <div class="alert alert-warning" role="alert" v-show="builder">
            <h4>Command Builder</h4>
            <command-input :builder="true"></command-input>
        </div>
    </transition>

    <div class="fp-scroll-container">
        <div class="code-parent fp-scrollable"></div>
    </div>
    <div class="fp-flex-header">
        <textarea class="form-control" id="out" style="height:100%" v-model="messages.validation" readonly></textarea>
    </div>
    <small class="form-text text-muted">
        Sequence compilation output
    </small>
</div>
`;
