/**
 * Templates file for the sequencer plugin.  Contains the HTML template setup.
 */
export let sequencer_template = `
<div class="fp-flex-repeater">
    <div class="fp-flex-header">
        <h2>Command Sequencer</h2>
        <form v-on:submit.prevent="() => { return false;}" class="was-validated" novalidate>
            <div class="form-group row">
                <div class="col-4" for="sequence">
                    <input type="text" id="sequence" class="form-control" v-model="sequence.name" :disabled="active"
                        pattern="[^;\\\\\\/]+\\.seq" placeholder="Sequence name ending in .seq" required />
                    <div class="invalid-feedback">{{ (messages.error) ? messages.error : "Supply filename ending with .seq" }}</div>
                </div>
                <div class="col col-2 custom-file">
                    <input type="file" id="sequenceUpload" accept=".seq"
                    v-on:change="setSequence($event.target.files[0])" >
                    <label class="custom-file-label" for="sequenceUpload">Upload a sequence file</label>
                </div>
                <div class="col-4 offset-2 align-right">
                <button class="btn btn-secondary mb-1 mr-1 float-right" v-on:click="builder = !builder"><i class="fas fa-tools"></i></button>
                <button class="btn btn-secondary mb-1 mr-1 float-right" :disabled="active" v-on:click="download"><i class="fas fa-download"></i></button>
                <button class="col-5 btn btn-primary mb-1 mr-1 float-right" :disabled="active" v-on:click="sendSequence(true)">Uplink</button>
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